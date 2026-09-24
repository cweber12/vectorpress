"""validate._svg_document: one ``validate_cut_file`` call parses its SVG's
XML exactly once, and each ``<path>``'s ``d`` at most once, however many
views (pieces, subpaths, document elements) are derived from it."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import svgelements as se  # pyright: ignore[reportMissingTypeStubs]

from vectorpress.validate.cut_file import validate_cut_file

_FINDINGS_FIXTURES = Path(__file__).parent.parent / "fixtures" / "findings"


@pytest.mark.parametrize("fixture", sorted(_FINDINGS_FIXTURES.glob("*.svg")), ids=lambda p: p.stem)
def test_validate_cut_file_parses_xml_once_and_each_path_once(
    fixture: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svg_bytes = fixture.read_bytes()
    path_count = sum(
        1 for element in ET.fromstring(svg_bytes).iter() if element.tag.rsplit("}", 1)[-1] == "path"
    )

    fromstring_calls = 0
    real_fromstring = ET.fromstring

    def counting_fromstring(*args: object, **kwargs: object) -> ET.Element:
        nonlocal fromstring_calls
        fromstring_calls += 1
        return real_fromstring(*args, **kwargs)  # type: ignore[arg-type]

    path_parses = 0
    real_path = se.Path

    def counting_path(*args: object, **kwargs: object) -> se.Path:
        nonlocal path_parses
        path_parses += 1
        return real_path(*args, **kwargs)

    monkeypatch.setattr(ET, "fromstring", counting_fromstring)
    monkeypatch.setattr(se, "Path", counting_path)

    validate_cut_file(svg_bytes, 3.0)

    assert fromstring_calls == 1
    assert path_parses == path_count
