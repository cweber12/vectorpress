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

The build report names every catalog override actually used (ADR 0015): a
file under ``templates/<kind>/`` that some render of that environment
loaded, whether by a direct lookup or only reached through
``{% extends %}``/``{% include %}`` -- never one merely sitting in the
folder unread. :func:`used_overrides` reads this back off the environment
:func:`template_environment` built.

The presentation hash (ADR 0014) needs the same "actually loaded, not
merely present" tracking for the shipped side too -- a build's presentation
covers every template file it used, shipped or override. :func:`used_template_files`
reads both loaders back off the environment, each entry keyed by a
catalog- or package-relative identifier that never carries the catalog
root's own absolute path, so the same catalog hashes the same on any
machine.
"""

from collections.abc import Callable
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


class _TrackingLoader(FileSystemLoader):
    """A :class:`~jinja2.FileSystemLoader` recording the template name and
    on-disk path of every file it actually serves. ``get_source`` is the
    one point every lookup against this folder passes through -- a plain
    top-level request, or one reached only via ``{% extends %}``/
    ``{% include %}`` -- whether or not :class:`~jinja2.Environment` later
    serves the compiled template from its own cache on a repeat request. A
    file this loader never finds (missing, so :class:`~jinja2.ChoiceLoader`
    falls through to the next one) is never recorded: only a name it
    actually resolved counts as "in use"."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.loaded: list[tuple[str, Path]] = []

    def get_source(
        self, environment: Environment, template: str
    ) -> tuple[str, str, Callable[[], bool]]:
        source, filename, uptodate = super().get_source(environment, template)
        assert filename is not None  # FileSystemLoader always sets its own file path
        entry = (template, Path(filename))
        if entry not in self.loaded:
            self.loaded.append(entry)
        return source, filename, uptodate


class _TrackingCatalogLoader(_TrackingLoader):
    """The catalog's own ``templates/<kind>/`` loader (ADR 0015's build
    report list): :attr:`used` names every file this loader actually
    served, catalog-relative (``templates/<kind>/<file>``)."""

    def __init__(self, path: Path, kind: str) -> None:
        super().__init__(path)
        self.kind = kind
        self._catalog_relative_prefix = f"{CATALOG_TEMPLATES_DIRNAME}/{kind}"

    @property
    def used(self) -> list[str]:
        return [f"{self._catalog_relative_prefix}/{name}" for name, _ in self.loaded]


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

    Both the catalog and the shipped loader are :class:`_TrackingLoader`s
    (the catalog one specifically :class:`_TrackingCatalogLoader`, for
    :func:`used_overrides`'s own catalog-relative naming) -- the *same*
    shipped loader instance backs both the plain shipped fallback and the
    ``shipped/`` prefix, so a file reached either way is recorded once.
    Every render through the returned environment can later be asked, via
    :func:`used_overrides` or :func:`used_template_files`, which files it
    actually used.
    """
    catalog_dir = root / CATALOG_TEMPLATES_DIRNAME / kind
    shipped_dir = _SHIPPED_TEMPLATES_ROOT / kind
    shipped_loader = _TrackingLoader(shipped_dir)
    loader = ChoiceLoader(
        [
            _TrackingCatalogLoader(catalog_dir, kind),
            shipped_loader,
            PrefixLoader({SHIPPED_TEMPLATE_PREFIX: shipped_loader}),
        ]
    )
    return Environment(
        loader=loader, undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True
    )


def used_overrides(environment: Environment) -> list[str]:
    """The catalog-relative paths (``templates/<kind>/<file>``) of every
    catalog override ``environment`` actually used, sorted for a stable
    build report (ADR 0015: "the build report lists every catalog override
    in use"). ``environment`` must be one :func:`template_environment`
    built -- its first loader is always the kind's own
    :class:`_TrackingCatalogLoader`."""
    loader = environment.loader
    assert isinstance(loader, ChoiceLoader)
    catalog_loader = loader.loaders[0]
    assert isinstance(catalog_loader, _TrackingCatalogLoader)
    return sorted(catalog_loader.used)


def used_template_files(environment: Environment) -> list[tuple[str, Path]]:
    """Every template file -- shipped or catalog override -- ``environment``
    actually loaded (ADR 0014's presentation hash: "every template file the
    build used, shipped or override"). Each entry pairs a stable identifier
    (``"catalog:<kind>/<name>"`` or ``"shipped:<kind>/<name>"`` -- never the
    catalog root's own absolute path, so the same catalog hashes the same on
    any machine) with the file's own path on disk, to hash its bytes.
    Sorted by identifier. ``environment`` must be one :func:`template_environment`
    built -- its first two loaders are always the kind's own
    :class:`_TrackingCatalogLoader` and shipped :class:`_TrackingLoader`.
    """
    loader = environment.loader
    assert isinstance(loader, ChoiceLoader)
    catalog_loader = loader.loaders[0]
    shipped_loader = loader.loaders[1]
    assert isinstance(catalog_loader, _TrackingCatalogLoader)
    assert isinstance(shipped_loader, _TrackingLoader)
    kind = catalog_loader.kind
    entries = [(f"catalog:{kind}/{name}", path) for name, path in catalog_loader.loaded]
    entries += [(f"shipped:{kind}/{name}", path) for name, path in shipped_loader.loaded]
    return sorted(entries, key=lambda entry: entry[0])
