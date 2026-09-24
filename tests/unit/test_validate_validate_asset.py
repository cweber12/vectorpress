"""validate.validate_asset: the per-asset ``vpress validate`` orchestration
(§9, §35, ADR 0004, ADR 0006, ADR 0007, issue #37 fix round 1).

Calls :func:`validate_asset_cut_file` directly against a fabricated asset
and a temp-path catalog layout -- never through the CLI (``tests/
integration/test_validate.py`` exercises the CLI end to end) -- proving the
whole read-validate-persist cycle works as a plain function any caller
(``cli``, and eventually a ``ui``) can use without duplicating it."""

from pathlib import Path

import pytest

from vectorpress.catalog.findings import read_findings_report
from vectorpress.catalog.provenance import DERIVED_DIRNAME
from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.finding import FindingKind, ValidationOutcome
from vectorpress.validate.validate_asset import AssetValidationOutcome, validate_asset_cut_file

REFERENCE_SIZE_IN = 3.0

_ONE_PIECE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="10" height="10">'
    b'<path d="M0,0 L10,0 L10,10 L0,10 Z"/></svg>'
)

_TWO_PIECE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 10" width="30" height="10">'
    b'<path d="M0,0 L10,0 L10,10 L0,10 Z M20,2 L28,2 L28,8 L20,8 Z"/></svg>'
)


def _asset(sources: list[Source], display_name: str = "Test Asset") -> Asset:
    return Asset(
        id="test_asset",
        common_name="Test Asset",
        display_name=display_name,
        description="A fabricated asset for validate_asset_cut_file tests.",
        subject_category="Test",
        taxonomic_group="Test",
        rights_status=RightsStatus.ORIGINAL_ARTWORK,
        accuracy_status=AccuracyStatus.NOT_REVIEWED,
        sources=sources,
    )


def _catalog(root: Path) -> CatalogConfig:
    (root / "assets" / "test_asset" / "sources").mkdir(parents=True)
    return CatalogConfig(name="Test Catalog")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path


# --- impossible / missing: no file to validate, so nothing is persisted --------------------


def test_impossible_when_the_asset_has_no_silhouette_source(root: Path) -> None:
    """``cut_svg``'s recipe accepts only ``silhouette`` (ADR 0003) -- an
    asset with only a ``lineart`` source can never have one, whether or not
    anything has been generated yet."""
    config = _catalog(root)
    asset = _asset([Source(role="lineart", file="lineart.png")])

    result = validate_asset_cut_file(root, config, asset, REFERENCE_SIZE_IN)

    assert result.outcome is AssetValidationOutcome.IMPOSSIBLE
    assert result.reason is not None
    assert result.filename is None
    assert result.validation is None


def test_missing_when_the_source_is_selectable_but_no_file_exists_yet(root: Path) -> None:
    config = _catalog(root)
    asset = _asset([Source(role="silhouette", file="silhouette.png")])

    result = validate_asset_cut_file(root, config, asset, REFERENCE_SIZE_IN)

    assert result.outcome is AssetValidationOutcome.MISSING
    assert result.filename == "test-asset-cut.svg"
    assert result.validation is None
    # nothing was written -- there was nothing to validate.
    derived_dir = root / "assets" / "test_asset" / DERIVED_DIRNAME
    assert read_findings_report(derived_dir, "test-asset-cut.svg") is None


# --- validated: reads through catalog, writes through catalog ------------------------------


def test_validates_an_existing_cut_file_and_persists_its_findings_report(root: Path) -> None:
    config = _catalog(root)
    asset = _asset([Source(role="silhouette", file="silhouette.png")])
    derived_dir = root / "assets" / "test_asset" / DERIVED_DIRNAME
    derived_dir.mkdir(parents=True)
    (derived_dir / "test-asset-cut.svg").write_bytes(_ONE_PIECE_SVG)

    result = validate_asset_cut_file(root, config, asset, REFERENCE_SIZE_IN)

    assert result.outcome is AssetValidationOutcome.VALIDATED
    assert result.filename == "test-asset-cut.svg"
    assert result.validation is not None
    assert result.validation.outcome is ValidationOutcome.PASS

    report = read_findings_report(derived_dir, "test-asset-cut.svg")
    assert report is not None
    assert report.result is ValidationOutcome.PASS
    assert report.reference_size_in == REFERENCE_SIZE_IN


def test_a_two_piece_cut_file_needs_review_with_a_persisted_finding(root: Path) -> None:
    config = _catalog(root)
    asset = _asset([Source(role="silhouette", file="silhouette.png")])
    derived_dir = root / "assets" / "test_asset" / DERIVED_DIRNAME
    derived_dir.mkdir(parents=True)
    (derived_dir / "test-asset-cut.svg").write_bytes(_TWO_PIECE_SVG)

    result = validate_asset_cut_file(root, config, asset, REFERENCE_SIZE_IN)

    assert result.outcome is AssetValidationOutcome.VALIDATED
    assert result.validation is not None
    assert result.validation.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.validation.findings) == 1
    assert result.validation.findings[0].kind is FindingKind.DISCONNECTED_FRAGMENTS

    report = read_findings_report(derived_dir, "test-asset-cut.svg")
    assert report is not None
    assert len(report.findings) == 1


# --- failed: a validation failure is reported, nothing is persisted ------------------------


def test_an_unparseable_cut_file_fails_and_persists_nothing(root: Path) -> None:
    config = _catalog(root)
    asset = _asset([Source(role="silhouette", file="silhouette.png")])
    derived_dir = root / "assets" / "test_asset" / DERIVED_DIRNAME
    derived_dir.mkdir(parents=True)
    (derived_dir / "test-asset-cut.svg").write_bytes(b"not xml at all <<<")

    result = validate_asset_cut_file(root, config, asset, REFERENCE_SIZE_IN)

    assert result.outcome is AssetValidationOutcome.FAILED
    assert result.filename == "test-asset-cut.svg"
    assert result.reason
    assert result.validation is None
    assert read_findings_report(derived_dir, "test-asset-cut.svg") is None


# --- the reference size is taken explicitly, never defaulted internally --------------------


def test_a_different_reference_size_changes_the_persisted_report(root: Path) -> None:
    config = _catalog(root)
    asset = _asset([Source(role="silhouette", file="silhouette.png")])
    derived_dir = root / "assets" / "test_asset" / DERIVED_DIRNAME
    derived_dir.mkdir(parents=True)
    (derived_dir / "test-asset-cut.svg").write_bytes(_ONE_PIECE_SVG)

    validate_asset_cut_file(root, config, asset, 6.0)

    report = read_findings_report(derived_dir, "test-asset-cut.svg")
    assert report is not None
    assert report.reference_size_in == 6.0
