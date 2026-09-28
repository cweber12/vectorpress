"""A product's listing metadata: the §18 fields (CONTEXT.md "Listing").

No I/O here (ADR 0006): this only defines and validates shape. Only the
hand-authored §18 fields live here; the derived listing values §18 also
lists (included asset count, included formats, asset names, collection
name, product version, creation/update date) are not stored — they are
computed at build time from other loaded state, in later PRDs (issue #7).

Hand-authored, and per ADR 0016 the one exception to "the tool never
rewrites a hand-authored file": ``vpress listing draft`` appends a
product's ``[listing]`` once, create-only, then it is user-owned and the
tool never touches it again. It is optional at load time for exactly that
reason — a product can exist before its listing has been drafted — but is
validated like any other hand-authored table whenever it is present.

No price here: ``product.price`` is the one price (§18); a ``[listing]``
that still carries ``suggested_price`` is a product metadata problem
(``domain.product``).
"""

from pydantic import BaseModel, ConfigDict, Field


class Listing(BaseModel):
    """One product's ``[listing]`` table (§18).

    ``region`` and ``species_names`` are the two fields §18 marks "when
    applicable"; every other field is required whenever a ``[listing]``
    table is present at all.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    title: str
    short_title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)
    intended_uses: list[str] = Field(default_factory=list)
    region: str | None = None
    species_names: list[str] = Field(default_factory=list)
    category: str
    license_type: str
    marketplace_notes: str = ""
