"""pipeline.eligibility: gathering one asset's publication-eligibility
inputs from disk (§10, §10.1, §6.8, ADR 0004).

Builds a real asset folder on disk under ``tmp_path`` (a source PNG plus a
fabricated :class:`~vectorpress.domain.asset.Asset`), the same fixture-free
shape ``tests/unit/test_pipeline_review.py`` uses -- this module's job is
the disk-to-domain-input wiring, not the eligibility decision itself
(``tests/unit/test_domain_eligibility.py`` covers that) or catalog loading
(``tests/integration/test_eligibility.py`` exercises the CLI end to end).
"""

from pathlib import Path

from PIL import Image

from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.overrides import override_path, write_override_status
from vectorpress.catalog.provenance import DERIVED_DIRNAME, sha256_bytes
from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.eligibility import Eligibility
from vectorpress.domain.status import Status, StatusRecord
from vectorpress.pipeline.eligibility import (
    asset_eligibility_for,
    eligible_derivative_types,
    included_derivatives,
)
from vectorpress.pipeline.generate import generate_asset
from vectorpress.pipeline.review import approve_derivative

SOURCES_DIRNAME = "sources"


def _write_source_png(path: Path, rgba: tuple[int, int, int, int] = (196, 93, 38, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), rgba).save(path, format="PNG")


def _asset(asset_id: str = "ochre_sea_star") -> Asset:
    return Asset(
        id=asset_id,
        common_name="Ochre sea star",
        display_name="Ochre Sea Star",
        description="A test asset.",
        subject_category="Echinoderm",
        taxonomic_group="Echinoderm",
        rights_status=RightsStatus.ORIGINAL_ARTWORK,
        accuracy_status=AccuracyStatus.NOT_REVIEWED,
        sources=[Source(role="silhouette", file="silhouette.png")],
    )


def _make_catalog_asset(tmp_path: Path, config: CatalogConfig, asset_id: str) -> tuple[Asset, Path]:
    asset = _asset(asset_id)
    asset_dir_path = asset_dir(tmp_path, config, asset_id)
    _write_source_png(asset_dir_path / SOURCES_DIRNAME / "silhouette.png")
    return asset, asset_dir_path


def _config() -> CatalogConfig:
    return CatalogConfig(name="test")


# --- eligible_derivative_types: every state but impossible ---------------------------


def test_eligible_derivative_types_excludes_impossible_types(tmp_path: Path) -> None:
    """This asset has only a ``silhouette`` source: ``flatcolor_svg`` (which
    needs a ``flatcolor`` source) is impossible and excluded; every other
    recipe-bearing type, still ``missing`` before generation, is included."""
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")

    types = eligible_derivative_types(asset, asset_dir_path, config)

    assert DerivativeType.FLATCOLOR_SVG not in types
    assert DerivativeType.TRANSPARENT_PNG in types
    assert DerivativeType.SILHOUETTE_SVG in types
    assert DerivativeType.CUT_SVG in types


# --- included_derivatives: state and effective status --------------------------------


def test_included_derivatives_reports_missing_with_no_status(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")

    result = included_derivatives(asset, asset_dir_path, [DerivativeType.CUT_SVG], config)

    assert result[0].derivative_type is DerivativeType.CUT_SVG
    assert result[0].state is DerivativeState.MISSING
    assert result[0].status is None


def test_included_derivatives_reports_a_type_with_no_recipe_as_impossible(
    tmp_path: Path,
) -> None:
    """A requested type absent from every recipe (``outline_svg`` has none
    yet) can never have an output either way -- reported ``impossible``,
    the same dead end a genuinely impossible type reaches."""
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")

    result = included_derivatives(asset, asset_dir_path, [DerivativeType.OUTLINE_SVG], config)

    assert result[0].derivative_type is DerivativeType.OUTLINE_SVG
    assert result[0].state is DerivativeState.IMPOSSIBLE
    assert result[0].status is None


def test_included_derivatives_reports_needs_review_after_generation(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)

    result = included_derivatives(asset, asset_dir_path, [DerivativeType.CUT_SVG], config)

    assert result[0].state is DerivativeState.CURRENT
    assert result[0].status is Status.NEEDS_REVIEW


def test_included_derivatives_reports_approved_after_approval(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)
    approve_derivative(asset, asset_dir_path, DerivativeType.CUT_SVG, None, config)

    result = included_derivatives(asset, asset_dir_path, [DerivativeType.CUT_SVG], config)

    assert result[0].status is Status.APPROVED


def test_included_derivatives_uses_the_overrides_own_status_not_the_generated_files(
    tmp_path: Path,
) -> None:
    """§6.8: once an override exists, its own status is what publication
    eligibility sees -- approving the generated file never leaks through."""
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)
    approve_derivative(asset, asset_dir_path, DerivativeType.CUT_SVG, None, config)

    filename = derivative_filename(asset.display_name, DerivativeType.CUT_SVG)
    override_bytes = b"<svg><!-- hand-edited --></svg>"
    override_file = override_path(asset_dir_path, filename)
    override_file.parent.mkdir(parents=True, exist_ok=True)
    override_file.write_bytes(override_bytes)
    write_override_status(
        asset_dir_path / DERIVED_DIRNAME,
        DerivativeType.CUT_SVG,
        StatusRecord(
            status=Status.NEEDS_REVIEW, note=None, output_hash=sha256_bytes(override_bytes)
        ),
    )

    result = included_derivatives(asset, asset_dir_path, [DerivativeType.CUT_SVG], config)

    assert result[0].status is Status.NEEDS_REVIEW


# --- asset_eligibility_for: gatherer and domain decision tied together ---------------


def test_asset_eligibility_for_is_blocked_until_every_included_type_is_approved(
    tmp_path: Path,
) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)

    types = [DerivativeType.TRANSPARENT_PNG, DerivativeType.CUT_SVG]
    blocked = asset_eligibility_for(asset, asset_dir_path, types, config)
    assert blocked.eligibility is Eligibility.BLOCKED
    assert len(blocked.blocking_reasons) == 2

    approve_derivative(asset, asset_dir_path, DerivativeType.TRANSPARENT_PNG, None, config)
    approve_derivative(asset, asset_dir_path, DerivativeType.CUT_SVG, None, config)

    eligible = asset_eligibility_for(asset, asset_dir_path, types, config)
    assert eligible.eligibility is Eligibility.ELIGIBLE
    assert eligible.blocking_reasons == []
