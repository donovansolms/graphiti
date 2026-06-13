import logging
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from graphiti_core import Graphiti  # type: ignore
from graphiti_core.edges import EntityEdge  # type: ignore
from graphiti_core.errors import EdgeNotFoundError, GroupsEdgesNotFoundError, NodeNotFoundError
from graphiti_core.llm_client import LLMClient  # type: ignore
from graphiti_core.nodes import EntityNode, EpisodicNode  # type: ignore

from graph_service.config import Settings
from graph_service.dto import FactResult, NodeResult

logger = logging.getLogger(__name__)


class ZepGraphiti(Graphiti):
    def __init__(self, uri: str, user: str, password: str, llm_client: LLMClient | None = None):
        super().__init__(uri, user, password, llm_client)

    async def save_entity_node(
        self,
        name: str,
        uuid: str,
        group_id: str,
        summary: str = '',
        labels: list[str] | None = None,
        attributes: dict | None = None,
    ):
        # "Entity" is graphiti's base label; any caller-supplied label (e.g.
        # "Place"/"Area") registers the node as an entity_type so its stamped FK
        # attributes survive later episode ingest (untyped nodes get reset to {}).
        node_labels = list(dict.fromkeys(['Entity', *(labels or [])]))
        new_node = EntityNode(
            name=name,
            uuid=uuid,
            group_id=group_id,
            summary=summary,
            labels=node_labels,
            attributes=attributes or {},
        )
        await new_node.generate_name_embedding(self.embedder)
        await new_node.save(self.driver)
        return new_node

    async def get_entity_edge(self, uuid: str):
        try:
            edge = await EntityEdge.get_by_uuid(self.driver, uuid)
            return edge
        except EdgeNotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e

    async def get_edges_by_created_at(
        self,
        group_ids: list[str],
        created_at_from: datetime | None = None,
        created_at_to: datetime | None = None,
        limit: int | None = None,
    ):
        """List edges whose created_at falls in the window for the given group_ids
        (non-semantic enumeration for Butler's cross_section whats_new). Returns []
        when nothing matches — a windowed query legitimately finds no new edges."""
        return await EntityEdge.get_by_group_ids(
            self.driver,
            group_ids,
            limit=limit,
            created_at_from=created_at_from,
            created_at_to=created_at_to,
        )

    async def delete_group(self, group_id: str):
        try:
            edges = await EntityEdge.get_by_group_ids(self.driver, [group_id])
        except GroupsEdgesNotFoundError:
            logger.warning(f'No edges found for group {group_id}')
            edges = []

        nodes = await EntityNode.get_by_group_ids(self.driver, [group_id])

        episodes = await EpisodicNode.get_by_group_ids(self.driver, [group_id])

        for edge in edges:
            await edge.delete(self.driver)

        for node in nodes:
            await node.delete(self.driver)

        for episode in episodes:
            await episode.delete(self.driver)

    async def delete_entity_edge(self, uuid: str):
        try:
            edge = await EntityEdge.get_by_uuid(self.driver, uuid)
            await edge.delete(self.driver)
        except EdgeNotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e

    async def delete_episodic_node(self, uuid: str):
        try:
            episode = await EpisodicNode.get_by_uuid(self.driver, uuid)
            await episode.delete(self.driver)
        except NodeNotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e


def build_graphiti(settings: Settings) -> ZepGraphiti:
    """Construct the single ZepGraphiti for the whole app lifetime — one Neo4j
    driver (one bounded connection pool) and one LLM/embedder client, shared by
    every request.

    This MUST be a singleton, not per-request. The old `get_graphiti` built a
    fresh ZepGraphiti (and thus a fresh Neo4j driver) on every request and closed
    it on teardown. But /text and /messages return 202 and defer the real work to
    the AsyncWorker queue, so the request-scoped close() fired while the queued
    job was still pending; the deferred add_episode then opened bolt connections
    on an already-torn-down driver that nothing would ever close again. Under bulk
    load (thousands of episodes queued at once, each pinning its own driver) those
    orphaned Neo4j connections outran GC finalization and exhausted the process
    file-descriptor limit — `socket.accept()` then failed and every request 500'd.
    A single shared instance caps Neo4j connections at the pool size, forever."""
    client = ZepGraphiti(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )
    if settings.openai_base_url is not None:
        client.llm_client.config.base_url = settings.openai_base_url
    if settings.openai_api_key is not None:
        client.llm_client.config.api_key = settings.openai_api_key
    if settings.model_name is not None:
        client.llm_client.model = settings.model_name
    return client


async def get_graphiti(request: Request) -> ZepGraphiti:
    # Return the shared app-lifetime instance built in the app lifespan
    # (main.lifespan -> app.state.graphiti). Never per-request — see build_graphiti.
    return request.app.state.graphiti


def get_fact_result_from_edge(edge: EntityEdge, nodes: dict[str, EntityNode] | None = None):
    """Project an edge to a FactResult. When `nodes` (a uuid->EntityNode map,
    e.g. from hydrate_nodes_for_edges) is supplied, the source/target entities
    are embedded so the result is self-describing; otherwise only the node uuids
    are returned and the *_node objects stay null."""
    nodes = nodes or {}

    def node_result(uuid: str | None) -> NodeResult | None:
        n = nodes.get(uuid) if uuid else None
        if n is None:
            return None
        return NodeResult(
            uuid=n.uuid,
            name=n.name,
            labels=list(n.labels or []),
            attributes=n.attributes or {},
        )

    return FactResult(
        uuid=edge.uuid,
        name=edge.name,
        fact=edge.fact,
        group_id=edge.group_id,
        source_node_uuid=edge.source_node_uuid,
        target_node_uuid=edge.target_node_uuid,
        source_node=node_result(edge.source_node_uuid),
        target_node=node_result(edge.target_node_uuid),
        valid_at=edge.valid_at,
        invalid_at=edge.invalid_at,
        created_at=edge.created_at,
        expired_at=edge.expired_at,
    )


async def hydrate_nodes_for_edges(
    graphiti: ZepGraphiti, edges: list[EntityEdge]
) -> dict[str, EntityNode]:
    """Batch-fetch the entity nodes referenced by a set of edges, returning a
    uuid->node map. One query regardless of edge count; lets fact results carry
    node identity (name + stamped attributes) without a per-fact lookup."""
    uuids = list({u for e in edges for u in (e.source_node_uuid, e.target_node_uuid) if u})
    if not uuids:
        return {}
    fetched = await EntityNode.get_by_uuids(graphiti.driver, uuids)
    return {n.uuid: n for n in fetched}


ZepGraphitiDep = Annotated[ZepGraphiti, Depends(get_graphiti)]
