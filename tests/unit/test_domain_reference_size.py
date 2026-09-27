"""domain.reference_size: the functions that resolve a reference size in
effect -- product override else catalog default (§9.1, ADR 0008, issue #38),
and an asset's own cleanup size (ADR 0012, issue #91)."""

from vectorpress.domain.asset import AccuracyStatus, Asset, DerivativePin, RightsStatus
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.product import Product
from vectorpress.domain.reference_size import resolve_cleanup_size_in, resolve_reference_size_in

VALID_PRODUCT: dict[str, object] = {
    "slug": "test_product",
    "collection_slug": "some_collection",
    "derivative_types": ["cut_svg"],
    "formats": ["svg"],
    "tier": "individual",
    "price": 5.0,
}


def _asset(derivatives: dict[str, DerivativePin] | None = None) -> Asset:
    return Asset(
        id="test_asset",
        common_name="Test Asset",
        display_name="Test Asset",
        description="A fabricated asset for pure resolver tests.",
        subject_category="Test",
        taxonomic_group="Test",
        rights_status=RightsStatus.ORIGINAL_ARTWORK,
        accuracy_status=AccuracyStatus.NOT_REVIEWED,
        derivatives=derivatives or {},
    )


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


# --- resolve_cleanup_size_in: asset's own cut_svg reference_size_in, else the
# catalog default (ADR 0012, issue #91) -------------------------------------


def test_cleanup_size_returns_the_assets_own_setting_when_set() -> None:
    config = CatalogConfig(name="Test Catalog", reference_size_in=3.0)
    asset = _asset({"cut_svg": DerivativePin(reference_size_in=6.0)})

    assert resolve_cleanup_size_in(config, asset) == 6.0


def test_cleanup_size_returns_the_catalog_default_with_no_asset_setting() -> None:
    config = CatalogConfig(name="Test Catalog", reference_size_in=3.0)
    asset = _asset()

    assert resolve_cleanup_size_in(config, asset) == 3.0


def test_cleanup_size_returns_the_catalog_default_when_the_pin_sets_no_size() -> None:
    """A ``[derivatives.cut_svg]`` table pinning only a ``source`` (no
    ``reference_size_in``) resolves the same as no table at all."""
    config = CatalogConfig(name="Test Catalog", reference_size_in=3.0)
    asset = _asset({"cut_svg": DerivativePin(source="silhouette.png")})

    assert resolve_cleanup_size_in(config, asset) == 3.0


def test_cleanup_size_never_reads_a_pin_on_a_different_type() -> None:
    """Only the ``cut_svg`` table's own setting counts -- a pin on another
    type (however it got there) never leaks into the cleanup size."""
    config = CatalogConfig(name="Test Catalog", reference_size_in=3.0)
    asset = _asset({"silhouette_svg": DerivativePin(source="silhouette.png")})

    assert resolve_cleanup_size_in(config, asset) == 3.0
