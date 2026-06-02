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


class TripletNode(BaseModel):
    uuid: str = Field(..., description='Stable uuid for the node (idempotent re-sync)')
    name: str = Field(..., description='Entity name (node name + resolution key)')
    summary: str = Field(default='', description='Optional node summary')
    attributes: dict = Field(default_factory=dict, description='Optional node attributes')


class TripletEdge(BaseModel):
    name: str = Field(..., description='Relation type / edge name (e.g. FRIEND_OF)')
    fact: str = Field(..., description='Natural-language fact (embedded + searchable)')
    uuid: str | None = Field(default=None, description='Optional stable edge uuid')


class AddTripletRequest(BaseModel):
    group_id: str = Field(..., description='The group id for the triplet')
    source: TripletNode = Field(..., description='Source entity node')
    target: TripletNode = Field(..., description='Target entity node')
    edge: TripletEdge = Field(..., description='Relationship edge from source to target')
