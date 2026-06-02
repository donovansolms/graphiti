"""Butler entity types for the knowledge graph.

These are registered with graphiti on every episode ingest (`/text`, `/messages`)
and used to label nodes on `/add-triplet`. Two reasons they matter:

1. Classification — extracted entities get a real type (Person, …) instead of a
   bare `Entity`, which improves dedup and enables typed/filterable queries.

2. **FK preservation (load-bearing).** Graphiti RESETS a node's `attributes` to
   `{}` during episode ingestion *unless* the node's type is a registered
   entity_type with those fields — see
   `graphiti_core/utils/maintenance/node_operations.py`:
   `_extract_entity_attributes` short-circuits to `{}` when `entity_type is None`
   (the no-schema path), but with a schema it takes the overlay-merge path where
   "LLM-omitted fields keep prior values". So Butler-stamped foreign keys
   (`subject_id` / `contact_id`) only survive messages mentioning that entity if
   the entity is a registered type carrying those fields.

   => Any future node that needs a Butler FK to survive (e.g. Place with a
   subject_id when we model places) MUST be added here as an entity_type with
   the FK field. Otherwise the next message about it wipes the FK.
"""

from pydantic import BaseModel, Field


class Person(BaseModel):
    """A human being — the Butler user(s) and the people in their life. The
    subject_id / contact_id below are foreign keys set by Butler, never inferred
    from message text: leave them unset when extracting from a message."""

    subject_id: str | None = Field(
        None,
        description='Butler subject id when this person is a declared subject '
        '(e.g. "person__donovan"). Set by Butler only — do NOT infer from text.',
    )
    contact_id: str | None = Field(
        None,
        description="Butler contact id when this person is in the user's contacts "
        '(e.g. "con_ab12cd34"). Set by Butler only — do NOT infer from text.',
    )


# Passed to graphiti on every episode ingest + used to label triplet nodes.
# The single source of truth for Butler's graph ontology types.
BUTLER_ENTITY_TYPES: dict[str, type[BaseModel]] = {
    'Person': Person,
}
