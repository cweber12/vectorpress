"""Reference size resolution: catalog default, product override, per-asset
cleanup size (CONTEXT.md "Reference size", "Cleanup size", §9.1, ADR 0008,
ADR 0012, issue #38).

No I/O here (ADR 0006): pure functions over already-loaded domain models.
The one place each decision is made -- every caller (``vpress
validate --product``, and PRD 6's build) uses :func:`resolve_reference_size_in`,
and generation and validation both use :func:`resolve_cleanup_size_in` --
and never re-derives the same rule inline, the same reasoning
:mod:`vectorpress.domain.numeric_format` documents for its own single
fixed-precision rule.
"""

from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_type import DerivativeType
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


def resolve_cleanup_size_in(config: CatalogConfig, asset: Asset) -> float:
    """``asset``'s **cleanup size** (CONTEXT.md, ADR 0012): the size its one
    ``cut_svg`` is cleaned at -- ``asset``'s own
    ``[derivatives.cut_svg] reference_size_in`` when set, else
    ``config.reference_size_in``.

    Unlike :func:`resolve_reference_size_in`, this never varies by product:
    ADR 0012 keeps a product's own reference size override validation-only,
    never a generation input.
    """
    pin = asset.derivatives.get(DerivativeType.CUT_SVG.value)
    if pin is not None and pin.reference_size_in is not None:
        return pin.reference_size_in
    return config.reference_size_in
