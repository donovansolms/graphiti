from datetime import datetime
from typing import Literal

from graphiti_core.utils.datetime_utils import utc_now
from pydantic import BaseModel, Field


class Result(BaseModel):
    message: str
    success: bool


class Message(BaseModel):
    content: str = Field(..., description='The content of the message')
    uuid: str | None = Field(default=None, description='The uuid of the message (optional)')
    name: str = Field(
        default='', description='The name of the episodic node for the message (optional)'
    )
    role_type: Literal['user', 'assistant', 'system'] = Field(
        ..., description='The role type of the message (user, assistant or system)'
    )
    role: str | None = Field(
        description='The custom role of the message to be used alongside role_type (user name, bot name, etc.)',
    )
    timestamp: datetime = Field(default_factory=utc_now, description='The timestamp of the message')
    source_description: str = Field(
        default='', description='The description of the source of the message'
    )


class TextEpisode(BaseModel):
    """A plain-text episode — no actor/role prefix is added to the body.
    Use this when the body is already a narrative sentence and you don't
    want the chat-message extractor's "{role}(role_type):" prefix to leak
    into entity extraction."""

    content: str = Field(..., description='The plain-text body of the episode')
    uuid: str | None = Field(default=None, description='Episodic node uuid (optional)')
    name: str = Field(
        default='',
        description='Human-readable label for the episode (e.g. "Message from Sarah", "Missed call from Mom")',
    )
    timestamp: datetime = Field(default_factory=utc_now, description='Reference time of the episode')
    source_description: str = Field(
        default='', description='Description of the source of the episode'
    )
