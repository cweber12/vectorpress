"""domain.reference_size: the one function that resolves the reference size
in effect -- product override, else catalog default (§9.1, ADR 0008, issue
#38)."""

from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.product import Product
from vectorpress.domain.reference_size import resolve_reference_size_in

VALID_PRODUCT: dict[str, object] = {
    "slug": "test_product",
    "collection_slug": "some_collection",
    "derivative_types": ["cut_svg"],
    "formats": ["svg"],
    "tier": "individual",
    "price": 5.0,
}


def test_returns_the_product_override_when_set() -> None:
    config = CatalogConfig(name="Test Catalog", reference_size_in=3.0)
    product = Product.model_validate({**VALID_PRODUCT, "reference_size_in": 1.5})

    assert resolve_reference_size_in(config, product) == 1.5


def test_returns_the_catalog_default_when_the_product_has_no_override() -> None:
    config = CatalogConfig(name="Test Catalog", reference_size_in=3.0)
    product = Product.model_validate(VALID_PRODUCT)

    assert product.reference_size_in is None
    assert resolve_reference_size_in(config, product) == 3.0


def test_returns_the_catalog_default_when_there_is_no_product_at_all() -> None:
    config = CatalogConfig(name="Test Catalog", reference_size_in=4.5)

    assert resolve_reference_size_in(config, None) == 4.5


def test_a_zero_override_is_still_honored_not_treated_as_falsy() -> None:
    """``0.0`` is a valid (if useless) float override -- the resolver must
    check ``is not None``, never plain truthiness, or a product could never
    override down to a degenerate size."""
    config = CatalogConfig(name="Test Catalog", reference_size_in=3.0)
    product = Product.model_validate({**VALID_PRODUCT, "reference_size_in": 0.0})

    assert resolve_reference_size_in(config, product) == 0.0
