"""The template lookup ADR 0015 defines, shared by every kind of shipped
template (``listing`` here; ``previews`` and ``export`` in later PRD 7
slices).

A file at ``<catalog>/templates/<kind>/<name>`` replaces the shipped file of
that name under ``vectorpress/build/templates/<kind>/`` by file name: the
catalog folder is searched first, so requesting ``<name>`` directly (the way
:func:`~vectorpress.build.listing_draft.draft_listing` looks up
``title.txt.j2``) resolves to the override when one exists, else the shipped
file. The folder name is fixed (ADR 0015): not configured in
``catalog.toml`` or ``brand.toml``, so this takes only ``root`` and ``kind``.

A plain ``ChoiceLoader`` alone cannot give ``{% extends %}`` partial
overrides (ADR 0015): a catalog file extending its own name by that name
would resolve back to itself and recurse. The shipped folder is therefore
also reachable under the fixed ``shipped/`` prefix -- part of the ADR 0015
contract alongside the folder names themselves -- so a catalog override
reaches the file it replaces with ``{% extends "shipped/<name>" %}`` and
overrides one ``{% block %}`` at a time.

Every template renders against a fixed, documented context specific to its
own kind (``build.listing_draft``'s for ``listing``) with strict undefined
variables: reading anything else fails the render naming the template,
rather than silently printing an empty string.
"""

from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PrefixLoader, StrictUndefined

#: The shipped templates' own root, one subfolder per kind (ADR 0015).
_SHIPPED_TEMPLATES_ROOT = Path(__file__).parent / "templates"

#: The catalog's own template override folder, relative to its root (ADR 0015).
CATALOG_TEMPLATES_DIRNAME = "templates"

#: The fixed prefix a catalog override uses to reach the shipped file it
#: replaces (ADR 0015's contract, alongside the ``<kind>`` folder names):
#: ``{% extends "shipped/title.txt.j2" %}`` always means the shipped
#: template, never whichever file -- catalog or shipped -- a plain
#: unprefixed lookup of that name would otherwise resolve to.
SHIPPED_TEMPLATE_PREFIX = "shipped"


def template_name_from_traceback(exc: BaseException, root: Path, kind: str) -> str | None:
    """The catalog- or shipped-relative template file name responsible for a
    Jinja render-time error (typically ``jinja2.UndefinedError`` under
    ``StrictUndefined``): the deepest frame in ``exc``'s own traceback whose
    source file sits under the catalog's ``templates/<kind>/`` or the
    shipped ``<kind>/`` folder, named the same way a catalog override's own
    file is named -- relative to whichever folder it came from. ``None``
    when no frame in the traceback belongs to either folder (the error did
    not originate inside a template render at all).

    A plain traceback walk, not a Jinja API: :class:`~jinja2.loaders.
    FileSystemLoader` compiles each template with its real file path as the
    frame's ``co_filename`` (unlike, say, a ``DictLoader``'s templates,
    which have none), so every frame already carries the name this needs.
    Works for a failure inside ``{% extends %}``/``{% include %}`` chain
    too: the last matching frame is the innermost template actually being
    evaluated when the error was raised, not the top-level one requested.
    """
    catalog_dir = root / CATALOG_TEMPLATES_DIRNAME / kind
    shipped_dir = _SHIPPED_TEMPLATES_ROOT / kind
    name: str | None = None
    traceback = exc.__traceback__
    while traceback is not None:
        filename = Path(traceback.tb_frame.f_code.co_filename)
        for template_dir in (catalog_dir, shipped_dir):
            try:
                name = filename.relative_to(template_dir).as_posix()
            except ValueError:
                continue
        traceback = traceback.tb_next
    return name


def template_environment(root: Path, kind: str) -> Environment:
    """A Jinja environment rendering ``kind`` templates: the catalog's own
    ``templates/<kind>/`` first, then the shipped ``<kind>/`` folder, so a
    catalog override wins by file name on a plain lookup. The shipped folder
    is additionally reachable under the fixed ``shipped/`` prefix
    (:data:`SHIPPED_TEMPLATE_PREFIX`), so a catalog override can
    ``{% extends "shipped/<name>" %}`` the exact file it replaces and
    override one block at a time, without the self-recursion a plain
    ``{% extends "<name>" %}`` would hit. Undefined variables raise instead
    of rendering blank (``StrictUndefined``); autoescaping is off, since
    every kind so far renders plain text or is escaped by its own markup
    rules, not HTML read back from user data.
    """
    catalog_dir = root / CATALOG_TEMPLATES_DIRNAME / kind
    shipped_dir = _SHIPPED_TEMPLATES_ROOT / kind
    shipped_loader = FileSystemLoader(shipped_dir)
    loader = ChoiceLoader(
        [
            FileSystemLoader(catalog_dir),
            shipped_loader,
            PrefixLoader({SHIPPED_TEMPLATE_PREFIX: shipped_loader}),
        ]
    )
    return Environment(
        loader=loader, undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True
    )
