import asyncio
import logging
import os
from contextlib import asynccontextmanager
from functools import partial
from uuid import uuid4

from fastapi import APIRouter, FastAPI, status
from graphiti_core.edges import EntityEdge  # type: ignore
from graphiti_core.nodes import EntityNode, EpisodeType  # type: ignore
from graphiti_core.utils.datetime_utils import utc_now  # type: ignore
from graphiti_core.utils.maintenance.graph_data_operations import clear_data  # type: ignore

from graph_service.dto import (
    AddEntityNodeRequest,
    AddMessagesRequest,
    AddTextEpisodesRequest,
    AddTripletRequest,
    Message,
    Result,
    TextEpisode,
)
from graph_service.entity_types import BUTLER_ENTITY_TYPES
from graph_service.zep_graphiti import ZepGraphitiDep

logger = logging.getLogger(__name__)

# Number of concurrent queue workers. Each drains the same queue, so this is the
# max number of episodes processed in parallel.
#
# Default is 1 (serial) ON PURPOSE: add_episode is incremental and dedups
# extracted entities/edges against the current graph, so two episodes for the
# SAME group_id running concurrently can fail to see each other's writes and
# create duplicate entities / miss edge invalidations. Our current workload uses
# a single group_id, so raising this would corrupt dedup.
#
# Only raise WORKER_CONCURRENCY once ingestion is spread across many groups AND
# the queue is sharded so each group_id is pinned to one worker (otherwise the
# same-group race above reappears).
WORKER_CONCURRENCY = int(os.getenv('WORKER_CONCURRENCY', 1))


class AsyncWorker:
    def __init__(self, concurrency: int = WORKER_CONCURRENCY):
        self.queue = asyncio.Queue()
        self.concurrency = concurrency
        self.tasks: list[asyncio.Task] = []

    async def worker(self, worker_id: int):
        while True:
            # Wait for the next job. A cancel here (shutdown while idle) is the
            # only thing that should stop the worker.
            try:
                job = await self.queue.get()
            except asyncio.CancelledError:
                break

            try:
                print(
                    f'worker {worker_id} got a job: '
                    f'(size of remaining queue: {self.queue.qsize()})'
                )
                await job()
            except asyncio.CancelledError:
                # Shutdown cancel landed while a job was running — stop the worker.
                break
            except Exception:
                # CRITICAL: a failing job must never kill the worker. Previously
                # the only handler was CancelledError, so any error raised by
                # add_episode (e.g. an OpenAI 431/429, an LLM schema failure, a
                # Neo4j blip) propagated out of worker() and the task died — the
                # queue then filled forever while /text kept returning 202. Log
                # and move on to the next job instead.
                logger.exception('episode job failed; worker %s continuing', worker_id)

    async def start(self):
        # Defaults to a single worker (serial) — see WORKER_CONCURRENCY above for
        # why same-group_id workloads must not run episodes in parallel.
        self.tasks = [
            asyncio.create_task(self.worker(i)) for i in range(max(1, self.concurrency))
        ]

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.tasks = []
        while not self.queue.empty():
            self.queue.get_nowait()


async_worker = AsyncWorker()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await async_worker.start()
    yield
    await async_worker.stop()


router = APIRouter(lifespan=lifespan)


@router.post('/messages', status_code=status.HTTP_202_ACCEPTED)
async def add_messages(
    request: AddMessagesRequest,
    graphiti: ZepGraphitiDep,
):
    async def add_messages_task(m: Message):
        await graphiti.add_episode(
            uuid=m.uuid,
            group_id=request.group_id,
            name=m.name,
            episode_body=f'{m.role or ""}({m.role_type}): {m.content}',
            reference_time=m.timestamp,
            source=EpisodeType.message,
            source_description=m.source_description,
            entity_types=BUTLER_ENTITY_TYPES,
        )

    for m in request.messages:
        await async_worker.queue.put(partial(add_messages_task, m))

    return Result(message='Messages added to processing queue', success=True)


@router.post('/text', status_code=status.HTTP_202_ACCEPTED)
async def add_text_episodes(
    request: AddTextEpisodesRequest,
    graphiti: ZepGraphitiDep,
):
    """Add plain-text episodes — bodies are stored verbatim with no
    actor/role prefix. Use this when the body is already a narrative
    sentence (e.g. produced by a third-party framer) and the
    "{role}(role_type):" prefix from /messages would leak into entity
    extraction."""

    async def add_text_task(t: TextEpisode):
        await graphiti.add_episode(
            uuid=t.uuid,
            group_id=request.group_id,
            name=t.name,
            episode_body=t.content,
            reference_time=t.timestamp,
            source=EpisodeType.text,
            source_description=t.source_description,
            entity_types=BUTLER_ENTITY_TYPES,
        )

    for t in request.episodes:
        await async_worker.queue.put(partial(add_text_task, t))

    return Result(message='Text episodes added to processing queue', success=True)


@router.post('/entity-node', status_code=status.HTTP_201_CREATED)
async def add_entity_node(
    request: AddEntityNodeRequest,
    graphiti: ZepGraphitiDep,
):
    node = await graphiti.save_entity_node(
        uuid=request.uuid,
        group_id=request.group_id,
        name=request.name,
        summary=request.summary,
        labels=request.labels,
        attributes=request.attributes,
    )
    return node


@router.post('/add-triplet', status_code=status.HTTP_201_CREATED)
async def add_triplet(
    request: AddTripletRequest,
    graphiti: ZepGraphitiDep,
):
    """Add an entity->entity relationship directly, no LLM extraction.
    add_triplet embeds the source/target names + the edge fact and resolves
    each node against existing entities, so e.g. a contact merges with the
    same entity already extracted from messages."""

    # "Entity" is graphiti's base label; any caller-supplied label (e.g.
    # "Person") is what makes this node a registered entity_type, so its
    # stamped attributes (subject_id/contact_id) survive later episode ingest.
    def _labels(custom: list[str]) -> list[str]:
        return list(dict.fromkeys(['Entity', *custom]))

    now = utc_now()
    source = EntityNode(
        uuid=request.source.uuid,
        name=request.source.name,
        group_id=request.group_id,
        labels=_labels(request.source.labels),
        summary=request.source.summary,
        attributes=request.source.attributes,
    )
    target = EntityNode(
        uuid=request.target.uuid,
        name=request.target.name,
        group_id=request.group_id,
        labels=_labels(request.target.labels),
        summary=request.target.summary,
        attributes=request.target.attributes,
    )
    edge = EntityEdge(
        uuid=request.edge.uuid or str(uuid4()),
        group_id=request.group_id,
        source_node_uuid=request.source.uuid,
        target_node_uuid=request.target.uuid,
        created_at=now,
        name=request.edge.name,
        fact=request.edge.fact,
        # Butler-supplied event time (when the relationship became true). When set,
        # core add_triplet uses it as the episode reference and the edge skips LLM
        # timestamp extraction, so the edge is dated by the event, not by ingest.
        valid_at=request.edge.valid_at,
    )
    await graphiti.add_triplet(source, edge, target)
    return Result(message='Triplet added', success=True)


@router.delete('/entity-edge/{uuid}', status_code=status.HTTP_200_OK)
async def delete_entity_edge(uuid: str, graphiti: ZepGraphitiDep):
    await graphiti.delete_entity_edge(uuid)
    return Result(message='Entity Edge deleted', success=True)


@router.delete('/group/{group_id}', status_code=status.HTTP_200_OK)
async def delete_group(group_id: str, graphiti: ZepGraphitiDep):
    await graphiti.delete_group(group_id)
    return Result(message='Group deleted', success=True)


@router.delete('/episode/{uuid}', status_code=status.HTTP_200_OK)
async def delete_episode(uuid: str, graphiti: ZepGraphitiDep):
    await graphiti.delete_episodic_node(uuid)
    return Result(message='Episode deleted', success=True)


@router.post('/clear', status_code=status.HTTP_200_OK)
async def clear(
    graphiti: ZepGraphitiDep,
):
    await clear_data(graphiti.driver)
    await graphiti.build_indices_and_constraints()
    return Result(message='Graph cleared', success=True)
