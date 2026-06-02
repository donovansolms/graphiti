from datetime import datetime, timezone

from pydantic import BaseModel, Field

from graph_service.dto.common import Message


class SearchQuery(BaseModel):
    group_ids: list[str] | None = Field(
        None, description='The group ids for the memories to search'
    )
    query: str
    max_facts: int = Field(default=10, description='The maximum number of facts to retrieve')


class NodeResult(BaseModel):
    """The identity of one end of a fact's edge. `attributes` carries whatever
    was stamped at write time (e.g. Butler's `subject_id` / `contact_id`), so a
    consumer maps a fact back to a subject/contact by an explicit field rather
    than by parsing the fact text or reverse-decoding a key."""

    uuid: str
    name: str
    labels: list[str] = Field(default_factory=list)
    attributes: dict = Field(default_factory=dict)


class FactResult(BaseModel):
    uuid: str
    name: str
    fact: str
    # Identity handles the edge already carries — surfaced so a search result is
    # self-describing. group_id is the perspective/owner (a Butler subject id);
    # source_node/target_node carry the entities the fact connects.
    group_id: str | None = None
    source_node_uuid: str | None = None
    target_node_uuid: str | None = None
    source_node: NodeResult | None = None
    target_node: NodeResult | None = None
    valid_at: datetime | None
    invalid_at: datetime | None
    created_at: datetime
    expired_at: datetime | None

    class Config:
        json_encoders = {datetime: lambda v: v.astimezone(timezone.utc).isoformat()}


class SearchResults(BaseModel):
    facts: list[FactResult]


class GetMemoryRequest(BaseModel):
    group_id: str = Field(..., description='The group id of the memory to get')
    max_facts: int = Field(default=10, description='The maximum number of facts to retrieve')
    center_node_uuid: str | None = Field(
        ..., description='The uuid of the node to center the retrieval on'
    )
    messages: list[Message] = Field(
        ..., description='The messages to build the retrieval query from '
    )


class GetMemoryResponse(BaseModel):
    facts: list[FactResult] = Field(..., description='The facts that were retrieved from the graph')
