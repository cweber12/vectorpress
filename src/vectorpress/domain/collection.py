"""The collection metadata model.

No I/O here (ADR 0006): this module only defines and validates the shape of
one collection's ``<slug>.toml``. Finding collection files and reading them
off disk is the ``catalog`` layer's job.

A collection is a membership, not a sellable thing (ADR 0008, CONTEXT.md):
it carries name, slug, description, tags and intended marketplace category
plus a ``Membership`` (explicit list, metadata rule, union, or a mix).
Fields §11 lists that ADR 0008 moves to the product — included variants,
formats, tier, price — are not collection fields; neither is a version
field (ADR 0004, content-addressed provenance, has no version numbers).
"""

from pydantic import BaseModel, ConfigDict, Field

from vectorpress.domain.membership import Membership

#: A collection's stable identifier; also its file's stem (CONTEXT.md).
CollectionSlug = str


class Collection(BaseModel):
    """One collection's hand-authored metadata (``<slug>.toml``).

    Read-only to the tool (ADR 0005): loading validates this shape, nothing
    in this codebase writes it back. ``slug`` is always the file's stem; the
    ``catalog`` layer is responsible for checking that a ``slug`` key
    present in the file agrees with the stem before constructing this model.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    slug: CollectionSlug
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    marketplace_category: str
    membership: Membership
