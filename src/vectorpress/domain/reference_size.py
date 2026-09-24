"""Reference size resolution: catalog default, product override (CONTEXT.md
"Reference size", §9.1, ADR 0008, issue #38).

No I/O here (ADR 0006): a pure function over two already-loaded domain
models. The one place this decision is made -- every caller (``vpress
validate --product``, and PRD 6's build) uses :func:`resolve_reference_size_in`
and never re-derives the same "product override, else catalog default" rule
inline, the same reasoning :mod:`vectorpress.domain.numeric_format` documents
for its own single fixed-precision rule.
"""

from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.product import Product


def resolve_reference_size_in(config: CatalogConfig, product: Product | None) -> float:
    """The reference size in effect (§9.1): ``product.reference_size_in``
    when ``product`` is given and sets one, otherwise ``config.reference_size_in``.

    ``product`` is ``None`` for a caller with no product in play at all (the
    catalog-default validation flow, ``vpress validate`` without
    ``--product``) -- resolves the same as a product that declared no
    override.
    """
    if product is not None and product.reference_size_in is not None:
        return product.reference_size_in
    return config.reference_size_in
