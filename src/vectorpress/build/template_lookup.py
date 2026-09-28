"""The template lookup ADR 0015 defines, shared by every kind of shipped
template (``listing`` here; ``previews`` and ``export`` in later PRD 7
slices).

A file at ``<catalog>/templates/<kind>/<name>`` replaces the shipped file of
that name under ``vectorpress/build/templates/<kind>/``; the catalog folder
is searched first, so ``{% extends %}`` can still reach the shipped file
underneath it. The folder name is fixed (ADR 0015): not configured in
``catalog.toml`` or ``brand.toml``, so this takes only ``root`` and ``kind``.

Every template renders against a fixed, documented context specific to its
own kind (``build.listing_draft``'s for ``listing``) with strict undefined
variables: reading anything else fails the render naming the template,
rather than silently printing an empty string.
"""

from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined

#: The shipped templates' own root, one subfolder per kind (ADR 0015).
_SHIPPED_TEMPLATES_ROOT = Path(__file__).parent / "templates"

#: The catalog's own template override folder, relative to its root (ADR 0015).
CATALOG_TEMPLATES_DIRNAME = "templates"


def template_environment(root: Path, kind: str) -> Environment:
    """A Jinja environment rendering ``kind`` templates: the catalog's own
    ``templates/<kind>/`` first, then the shipped ``<kind>/`` folder,
    so a catalog override wins by file name and ``{% extends %}`` can still
    reach the shipped file it overrides. Undefined variables raise instead
    of rendering blank (``StrictUndefined``); autoescaping is off, since
    every kind so far renders plain text or is escaped by its own markup
    rules, not HTML read back from user data.
    """
    catalog_dir = root / CATALOG_TEMPLATES_DIRNAME / kind
    shipped_dir = _SHIPPED_TEMPLATES_ROOT / kind
    loader = ChoiceLoader([FileSystemLoader(catalog_dir), FileSystemLoader(shipped_dir)])
    return Environment(
        loader=loader, undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True
    )
