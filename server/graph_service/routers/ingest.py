import asyncio
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
from graph_service.zep_graphiti import ZepGraphitiDep


class AsyncWorker:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.task = None

    async def worker(self):
        while True:
            try:
                print(f'Got a job: (size of remaining queue: {self.queue.qsize()})')
                job = await self.queue.get()
                await job()
            except asyncio.CancelledError:
                break

    async def start(self):
        self.task = asyncio.create_task(self.worker())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await self.task
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

    now = utc_now()
    source = EntityNode(
        uuid=request.source.uuid,
        name=request.source.name,
        group_id=request.group_id,
        summary=request.source.summary,
        attributes=request.source.attributes,
    )
    target = EntityNode(
        uuid=request.target.uuid,
        name=request.target.name,
        group_id=request.group_id,
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
