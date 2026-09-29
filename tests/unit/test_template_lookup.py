"""build.template_lookup: the ADR 0015 catalog-over-shipped lookup itself is
covered where it is used (``test_build_previews.py``,
``test_build_listing_draft.py``). This module covers
:func:`~vectorpress.build.template_lookup.used_overrides` alone: the build
report's list of catalog overrides "actually loaded during that render
(including via extends/include), not merely present in the folder" (ADR
0015, issue #121).

Every render here is plain Jinja against a bare ``tmp_path`` catalog root --
no Chromium, no brand/product context -- since tracking happens at template
*load* time (``Loader.get_source``), not at any particular variable a
template happens to read.
"""

from pathlib import Path

from vectorpress.build.template_lookup import template_environment, used_overrides


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_used_overrides_is_empty_with_no_catalog_templates_folder_at_all(tmp_path: Path) -> None:
    environment = template_environment(tmp_path, "listing")

    environment.get_template("title.txt.j2").render(name="Test", format_phrase="SVG Cut Files")

    assert used_overrides(environment) == []


def test_used_overrides_names_a_directly_requested_override(tmp_path: Path) -> None:
    _write(tmp_path / "templates" / "listing" / "title.txt.j2", "{{ name }} -- custom\n")
    environment = template_environment(tmp_path, "listing")

    environment.get_template("title.txt.j2").render(name="Test", format_phrase="SVG Cut Files")

    assert used_overrides(environment) == ["templates/listing/title.txt.j2"]


def test_used_overrides_never_names_a_catalog_file_the_render_never_reached(tmp_path: Path) -> None:
    """A catalog templates/ file that is merely present -- an override for a
    template this particular render never requests -- is not "in use"
    (ADR 0015): only ``title.txt.j2`` is rendered, so the sitting
    ``description.txt.j2`` override never appears."""
    _write(tmp_path / "templates" / "listing" / "description.txt.j2", "custom\n")
    environment = template_environment(tmp_path, "listing")

    environment.get_template("title.txt.j2").render(name="Test", format_phrase="SVG Cut Files")

    assert used_overrides(environment) == []


def test_used_overrides_names_an_override_reached_only_through_an_include(tmp_path: Path) -> None:
    """previews/_base.html.j2's own ``{% include "brand.css" %}`` (never a
    direct top-level lookup) still counts as in use once a catalog
    ``brand.css`` override answers it."""
    _write(tmp_path / "templates" / "previews" / "brand.css", "body { color: red; }\n")
    environment = template_environment(tmp_path, "previews")

    environment.get_template("_base.html.j2").render()

    assert used_overrides(environment) == ["templates/previews/brand.css"]


def test_used_overrides_names_every_file_in_an_extends_chain(tmp_path: Path) -> None:
    _write(
        tmp_path / "templates" / "previews" / "_base.html.j2",
        "<html>{% block content %}{% endblock %}</html>\n",
    )
    _write(
        tmp_path / "templates" / "previews" / "main.html.j2",
        '{% extends "_base.html.j2" %}\n{% block content %}hi{% endblock %}\n',
    )
    environment = template_environment(tmp_path, "previews")

    environment.get_template("main.html.j2").render()

    assert used_overrides(environment) == [
        "templates/previews/_base.html.j2",
        "templates/previews/main.html.j2",
    ]


def test_used_overrides_ignores_the_fixed_shipped_prefix_reaching_the_file_it_replaces(
    tmp_path: Path,
) -> None:
    """``{% extends "shipped/title.txt.j2" %}`` (ADR 0015's own escape hatch
    for a partial override) always means the shipped file, reached under
    its fixed prefix -- never itself counted as a catalog override in use.
    Only the catalog file actually requested, ``title.txt.j2``, is."""
    _write(
        tmp_path / "templates" / "listing" / "title.txt.j2",
        '{% extends "shipped/title.txt.j2" %}\n{% block title %}Custom{% endblock %}\n',
    )
    environment = template_environment(tmp_path, "listing")

    result = environment.get_template("title.txt.j2").render()

    assert result.strip() == "Custom"
    assert used_overrides(environment) == ["templates/listing/title.txt.j2"]
