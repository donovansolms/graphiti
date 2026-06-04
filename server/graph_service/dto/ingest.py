from datetime import datetime

from pydantic import BaseModel, Field

from graph_service.dto.common import Message, TextEpisode


class AddMessagesRequest(BaseModel):
    group_id: str = Field(..., description='The group id of the messages to add')
    messages: list[Message] = Field(..., description='The messages to add')


class AddTextEpisodesRequest(BaseModel):
    group_id: str = Field(..., description='The group id of the episodes to add')
    episodes: list[TextEpisode] = Field(..., description='The text episodes to add')


class AddEntityNodeRequest(BaseModel):
    uuid: str = Field(..., description='The uuid of the node to add')
    group_id: str = Field(..., description='The group id of the node to add')
    name: str = Field(..., description='The name of the node to add')
    summary: str = Field(default='', description='The summary of the node to add')
    labels: list[str] = Field(
        default_factory=list,
        description='Entity type labels (e.g. ["Place", "Area"]). Tags the node as a '
        'registered entity_type so its stamped FK attributes survive later episode '
        'ingest (untyped nodes get their attributes reset to {}).',
    )
    attributes: dict = Field(
        default_factory=dict,
        description='Plain node attributes, e.g. the Butler FK {"subject_id": "area__bedroom"}. '
        'Must NOT be declared entity-type fields — the FK rides as a non-schema attribute.',
    )


class TripletNode(BaseModel):
    uuid: str = Field(..., description='Stable uuid for the node (idempotent re-sync)')
    name: str = Field(..., description='Entity name (node name + resolution key)')
    summary: str = Field(default='', description='Optional node summary')
    labels: list[str] = Field(
        default_factory=list,
        description='Entity type labels (e.g. ["Person"]). Tags the node as a '
        'registered entity_type so its stamped attributes survive episode ingest.',
    )
    attributes: dict = Field(default_factory=dict, description='Optional node attributes')


class TripletEdge(BaseModel):
    name: str = Field(..., description='Relation type / edge name (e.g. FRIEND_OF)')
    fact: str = Field(..., description='Natural-language fact (embedded + searchable)')
    uuid: str | None = Field(default=None, description='Optional stable edge uuid')
    valid_at: datetime | None = Field(
        default=None,
        description="When the relationship became true — Butler sets this to the source "
        "envelope's event_time so a deterministic edge is dated by the event, not by ingest "
        "time. When present it is used verbatim and the edge skips LLM timestamp extraction "
        "(see _extract_edge_timestamps, which short-circuits when valid_at is already set). "
        'When absent, graphiti falls back to utc_now() as before.',
    )


class AddTripletRequest(BaseModel):
    group_id: str = Field(..., description='The group id for the triplet')
    source: TripletNode = Field(..., description='Source entity node')
    target: TripletNode = Field(..., description='Target entity node')
    edge: TripletEdge = Field(..., description='Relationship edge from source to target')
