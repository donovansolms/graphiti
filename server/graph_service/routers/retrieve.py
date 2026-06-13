from datetime import datetime, timezone

from fastapi import APIRouter, status

from graph_service.dto import (
    EdgesByTimeWindowQuery,
    GetMemoryRequest,
    GetMemoryResponse,
    Message,
    SearchQuery,
    SearchResults,
)
from graph_service.zep_graphiti import (
    ZepGraphitiDep,
    get_fact_result_from_edge,
    hydrate_nodes_for_edges,
)

router = APIRouter()


@router.post('/search', status_code=status.HTTP_200_OK)
async def search(query: SearchQuery, graphiti: ZepGraphitiDep):
    relevant_edges = await graphiti.search(
        group_ids=query.group_ids,
        query=query.query,
        num_results=query.max_facts,
    )
    nodes = await hydrate_nodes_for_edges(graphiti, relevant_edges)
    facts = [get_fact_result_from_edge(edge, nodes) for edge in relevant_edges]
    return SearchResults(
        facts=facts,
    )


@router.post('/edges-by-time-window', status_code=status.HTTP_200_OK)
async def edges_by_time_window(query: EdgesByTimeWindowQuery, graphiti: ZepGraphitiDep):
    """Non-semantic enumeration: edges whose created_at falls in the window for the
    given group_ids — Butler's cross_section `whats_new` (what was newly recorded)."""
    edges = await graphiti.get_edges_by_created_at(
        group_ids=query.group_ids,
        created_at_from=query.created_at_from,
        created_at_to=query.created_at_to,
        limit=query.max_facts,
    )
    nodes = await hydrate_nodes_for_edges(graphiti, edges)
    facts = [get_fact_result_from_edge(edge, nodes) for edge in edges]
    return SearchResults(facts=facts)


@router.get('/entity-edge/{uuid}', status_code=status.HTTP_200_OK)
async def get_entity_edge(uuid: str, graphiti: ZepGraphitiDep):
    entity_edge = await graphiti.get_entity_edge(uuid)
    nodes = await hydrate_nodes_for_edges(graphiti, [entity_edge])
    return get_fact_result_from_edge(entity_edge, nodes)


@router.get('/episodes/{group_id}', status_code=status.HTTP_200_OK)
async def get_episodes(group_id: str, last_n: int, graphiti: ZepGraphitiDep):
    episodes = await graphiti.retrieve_episodes(
        group_ids=[group_id], last_n=last_n, reference_time=datetime.now(timezone.utc)
    )
    return episodes


@router.post('/get-memory', status_code=status.HTTP_200_OK)
async def get_memory(
    request: GetMemoryRequest,
    graphiti: ZepGraphitiDep,
):
    combined_query = compose_query_from_messages(request.messages)
    result = await graphiti.search(
        group_ids=[request.group_id],
        query=combined_query,
        num_results=request.max_facts,
    )
    nodes = await hydrate_nodes_for_edges(graphiti, result)
    facts = [get_fact_result_from_edge(edge, nodes) for edge in result]
    return GetMemoryResponse(facts=facts)


def compose_query_from_messages(messages: list[Message]):
    combined_query = ''
    for message in messages:
        combined_query += f'{message.role_type or ""}({message.role or ""}): {message.content}\n'
    return combined_query
