"""Butler entity types for the knowledge graph.

Registered with graphiti on every episode ingest (`/text`, `/messages`) and used
to label nodes on `/add-triplet`. Two purposes:

1. Classification — extracted entities get a real type (Person, …) instead of a
   bare `Entity`, which improves dedup and enables typed/filterable queries.

2. **FK survival (load-bearing, and subtle).** Butler stamps foreign keys
   (`contact_id` -> contacts, `subject_id` -> subjects) onto nodes via
   `/add-triplet` so a fact can be mapped back to a Butler row. Those FKs are
   stored as plain node attributes that are DELIBERATELY NOT declared as fields
   on the entity type below:

   - graphiti's attribute extraction only reads/writes a type's *declared*
     fields. The overlay merge is
     `{**prior_attributes, **llm_response_capped_to_declared_fields}`, so any
     attribute NOT in the schema rides through untouched, and any value the LLM
     hallucinates for a non-field is dropped by the cap. The FKs survive and the
     LLM can't corrupt them.
   - if we DID declare the FKs as fields, the LLM would be asked to fill them
     from message text and would hallucinate (invent `subject_id="person__andre"`,
     copy the owner's id onto other people, null out a real `contact_id`). Don't.

   BUT graphiti resets a node's attributes to `{}` when its type has ZERO fields
   (the no-schema short-circuit in `_extract_entity_attributes`). So each type
   needs >=1 declared field purely to stay on the merge path. That's all
   `placeholder` is — an inert decoy whose value is unused; the real data (FKs)
   rides alongside as non-schema attributes.

Rule for any future FK-bearing entity (e.g. a Place carrying a subject_id):
register the type with a neutral placeholder field, and set the FK as a plain
node attribute on `/add-triplet` — never as a declared field.
"""

from pydantic import BaseModel, Field


# Every type below carries ONLY an inert `placeholder` field. The Butler FK it
# maps back to (`subject_id`, and `contact_id` for Person) rides as a NON-schema
# node attribute set by Butler via /add-triplet or /entity-node — never declared
# here. See the module docstring for why.


class Person(BaseModel):
    """A person — a Butler user or someone in their life (family, friends,
    colleagues, contacts). Use for any named human being."""

    # Inert decoy: exists only so this type has >=1 field, which keeps graphiti
    # on the attribute-merge path instead of the reset-to-{} path that would wipe
    # Butler's contact_id/subject_id (carried as non-schema node attributes set
    # by /add-triplet). Its value is never read.
    placeholder: str | None = Field(
        default=None,
        description='Unused internal placeholder — always leave this null.',
    )


class Place(BaseModel):
    """A place — a property or named location: the household's own home, or an
    external place it knows about (a friend's home, a shop, a venue). Maps back
    to a Butler `place__…` subject via the non-schema `subject_id` attribute."""

    placeholder: str | None = Field(
        default=None,
        description='Unused internal placeholder — always leave this null.',
    )


class Area(BaseModel):
    """An area — a physical space inside a place: a room (bedroom, kitchen) or an
    outdoor space (driveway, garden). Maps back to a Butler `area__…` subject via
    the non-schema `subject_id` attribute."""

    placeholder: str | None = Field(
        default=None,
        description='Unused internal placeholder — always leave this null.',
    )


# Passed to graphiti on every episode ingest + used to label triplet/seed nodes.
# The single source of truth for Butler's graph ontology types.
BUTLER_ENTITY_TYPES: dict[str, type[BaseModel]] = {
    'Person': Person,
    'Place': Place,
    'Area': Area,
}
