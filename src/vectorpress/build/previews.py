"""Render a product's marketplace preview images (§14, §16, ADR 0014, ADR
0015).

One rendering path shared by every preview type (:data:`PREVIEW_TYPES`),
never copied per type: each is a fixed context (ADR 0015) rendered through
its own shipped ``<type>.html.j2`` and screenshotted at both fixed canvases
by Playwright's headless Chromium (ADR 0014) -- no network, no system
fonts. Every image a template needs (the brand mark, a member's effective
derivative, the two shipped fonts) is embedded as a ``data:`` URI computed
here in Python, never referenced by a relative or absolute path: a template
has nothing to link to outside its own inline content, so the only way a
render can still reach the network is a catalog override writing a URL of
its own -- exactly what the Chromium request guard below exists to catch.

The context's canvas- and page-independent parts (``brand``, ``product``,
``members``, ``featured``) are computed once per build
(:func:`_preview_context`) and reused for every type/canvas combination --
recomputing a member's own image data URIs per render would redo the
expensive part of this module's work once per canvas per type for nothing.

``brand`` and ``product`` context values are content, not brand/product
model instances: this module fills the exact fixed shape ADR 0015 documents
(``canvas``, ``brand``, ``product``, ``members``, ``featured``, ``page``),
never the domain objects themselves, so a template can never read a field
the ADR does not name -- and never anything beyond that shape, including
through a mechanism StrictUndefined would not catch (Jinja's per-template
``globals``): ``brand.heading_font`` and ``brand.body_font`` are this
shape's own two existing fields, resolved to a :class:`PreviewFont` rather
than a plain string (this module's own decision, not a new context field --
see :class:`PreviewFont`).

The ADR 0014 presentation hash (:func:`current_presentation_hash`,
:func:`_presentation_hash`) covers every template file a build loaded
(shipped or catalog override), the brand fields above, the mark and font
file bytes, and the two listing fields templates print -- never a member
image, never rights status. It never launches Chromium: the template set a
render would use is decided entirely by Jinja, so a pure Jinja render
(sharing :func:`_preview_context` and the same render loop) is enough to
learn it.
"""

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, UndefinedError
from playwright.sync_api import Browser, Playwright, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from vectorpress.build.product_resolution import ProductMember
from vectorpress.build.template_lookup import (
    template_environment,
    template_name_from_traceback,
    used_overrides,
    used_template_files,
)
from vectorpress.catalog.provenance import sha256_bytes
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.brand import Brand
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.format import Format
from vectorpress.domain.product import Product

#: The template lookup "kind" previews render through (ADR 0015): catalog
#: ``templates/previews/`` first, then the shipped folder of the same name.
PREVIEWS_KIND = "previews"


@dataclass(frozen=True)
class PreviewType:
    """One §16 preview type: its fixed upload-order number and its own
    shipped ``<name>.html.j2`` template (ADR 0015). ``variants`` and
    ``contents`` still have an entry here even though they are conditional
    (:func:`_renders`) -- a left-out one simply renders nothing, so its
    number stays unused (§16) rather than reserved by a placeholder file."""

    number: str
    name: str
    template_name: str


#: Every preview type this build renders, in upload-order (§16 "nn sets
#: upload order"). ``included`` and ``formats`` cap or select what they show
#: inside their own shipped template (§16's "up to 12 members" and its
#: per-format one-line use text), not through a context field ADR 0015 does
#: not document. ``variants`` and ``contents`` are conditional (§16: "a
#: left-out type leaves its number unused") -- :func:`render_previews` skips
#: either one whose condition (:func:`_renders`) the product does not meet.
PREVIEW_TYPES: tuple[PreviewType, ...] = (
    PreviewType(number="01", name="main", template_name="main.html.j2"),
    PreviewType(number="02", name="included", template_name="included.html.j2"),
    PreviewType(number="03", name="formats", template_name="formats.html.j2"),
    PreviewType(number="04", name="variants", template_name="variants.html.j2"),
    PreviewType(number="05", name="contents", template_name="contents.html.j2"),
)

#: §16: ``contents`` shows every member at this many per page.
CONTENTS_PAGE_SIZE = 48


@dataclass(frozen=True)
class Canvas:
    """One of §16's two fixed preview image sizes (CONTEXT.md "Canvas")."""

    name: str
    width: int
    height: int


#: Every preview type renders at both fixed canvases (§16).
CANVASES: tuple[Canvas, ...] = (
    Canvas("square", 2000, 2000),
    Canvas("landscape", 2400, 1600),
)


class PreviewRenderError(Exception):
    """One preview failed to render (ADR 0014): an undefined template
    variable, a template requesting a remote or otherwise disallowed URL, or
    Chromium itself failing to launch or render. ``template_name`` is set
    whenever the failure traces to one template file; ``None`` for a
    Chromium-level failure (no Chromium installed) that names no template."""

    def __init__(self, message: str, template_name: str | None = None) -> None:
        super().__init__(message)
        self.template_name = template_name


# --- the fixed preview context (ADR 0015) -----------------------------------


@dataclass(frozen=True)
class PreviewBrandColors:
    background_color: str
    accent_color: str
    text_color: str


@dataclass(frozen=True)
class PreviewFont:
    """One of ``brand``'s two ADR 0015 font fields (``heading_font``,
    ``body_font``), resolved to the font this module actually embeds: a
    catalog font file when the brand names one, else one of the two fonts
    this tool ships (ADR 0014). ``load_brand`` has already refused a brand
    naming neither, so this module never falls back to a font of its own
    choosing. ``family`` is the CSS family name ``brand.css``'s own
    ``@font-face`` rules declare and the *only* one the CSS ever references
    -- never a generic fallback (``sans-serif``): pairing one risks matching
    a same-named font already installed on the machine, exactly what ADR
    0014's "no system fonts" forbids. ``regular_url`` and ``bold_url`` are
    each a ``data:`` URI -- a catalog font file's one file serves both,
    since a brand supplies only one file per role. ``format`` is the CSS
    ``@font-face`` format keyword matching that file (``woff2``,
    ``truetype``, ``opentype``)."""

    family: str
    regular_url: str
    bold_url: str
    format: str


@dataclass(frozen=True)
class PreviewBrand:
    """The preview context's ``brand`` (ADR 0015): ``mark_url`` is the mark
    file's own bytes as a ``data:`` URI, never a path -- a template has no
    other way to reach it (this module's own docstring)."""

    name: str
    mark_url: str
    heading_font: PreviewFont
    body_font: PreviewFont
    colors: PreviewBrandColors


@dataclass(frozen=True)
class PreviewDerivativeType:
    value: str
    label: str


@dataclass(frozen=True)
class PreviewFormat:
    value: str
    label: str
    file_count: int


@dataclass(frozen=True)
class PreviewProduct:
    """The preview context's ``product`` (ADR 0015)."""

    slug: str
    title: str
    short_title: str
    tier: str
    family: str | None
    member_count: int
    derivative_types: list[PreviewDerivativeType]
    formats: list[PreviewFormat]


@dataclass(frozen=True)
class PreviewPage:
    """The preview context's ``page`` (ADR 0015): "exists for ``contents``"
    -- every other type's context carries ``None`` instead. ``number`` is
    1-based; ``count`` is the total number of pages this build's ``contents``
    has, so the last page's template can tell itself apart from a full one."""

    number: int
    count: int


@dataclass(frozen=True)
class PreviewMember:
    """The preview context's one member entry (ADR 0015): ``image_url`` is
    the one image that stands for this member -- the first included type in
    the fixed order ``flatcolor_svg``, ``transparent_png``, ``silhouette_svg``,
    ``cut_svg`` (§16) -- and ``images_by_type`` holds every included type's
    own image, which ``variants`` reads to show one derivative type's image
    per card. Both are ``data:`` URIs (this module's own docstring)."""

    display_name: str
    image_url: str
    images_by_type: dict[str, str]


#: §16's customer-facing label for each derivative type, shown on a
#: preview's own badges (never a filename or a listing tag word -- those are
#: :mod:`vectorpress.build.listing_draft`'s own, separate concern).
_DERIVATIVE_TYPE_LABELS: dict[DerivativeType, str] = {
    DerivativeType.TRANSPARENT_PNG: "Transparent PNG",
    DerivativeType.SILHOUETTE_SVG: "Silhouette SVG",
    DerivativeType.CUT_SVG: "Cut File SVG",
    DerivativeType.FLATCOLOR_SVG: "Flat Color SVG",
    DerivativeType.OUTLINE_SVG: "Outline SVG",
    DerivativeType.DETAILED_MONO_SVG: "Detailed Mono SVG",
    DerivativeType.LAYERED_SVG: "Layered SVG",
}

#: §16's customer-facing label for each deliverable format, shown on a
#: preview's own format badges.
_FORMAT_LABELS: dict[Format, str] = {
    Format.SVG: "SVG",
    Format.PNG: "PNG",
    Format.DXF: "DXF",
    Format.PDF: "PDF",
    Format.EPS: "EPS",
}

#: §16's fixed stand-in preference order: the first of these a member has
#: included is the one image representing it on ``main``, ``included`` and
#: ``contents``.
_STAND_IN_PREFERENCE: tuple[DerivativeType, ...] = (
    DerivativeType.FLATCOLOR_SVG,
    DerivativeType.TRANSPARENT_PNG,
    DerivativeType.SILHOUETTE_SVG,
    DerivativeType.CUT_SVG,
)


def _data_uri(mime: str, content: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


def _derivative_mime(derivative_type: DerivativeType) -> str:
    """Every derivative type but ``transparent_png`` is one of the ``*_svg``
    types (CONTEXT.md "Derivative type"): a plain two-way split is enough,
    with no per-type table to keep in sync as new SVG types land."""
    return "image/png" if derivative_type is DerivativeType.TRANSPARENT_PNG else "image/svg+xml"


def _mark_data_uri(root: Path, brand: Brand) -> str:
    """The brand mark as a ``data:`` URI (ADR 0014: "may be PNG or SVG").
    ``load_brand`` has already confirmed ``mark_file`` exists under the
    catalog root before a build ever reaches here."""
    path = root / brand.mark_file
    mime = "image/svg+xml" if path.suffix.lower() == ".svg" else "image/png"
    return _data_uri(mime, path.read_bytes())


#: The two shipped fonts' own files, package data beside the previews
#: templates (ADR 0014): real upstream releases (rsms/inter,
#: floriankarsten/space-grotesk), SIL Open Font License, license text
#: committed alongside each.
_FONTS_ROOT = Path(__file__).parent / "templates" / "previews" / "fonts"
_SHIPPED_FONT_FILES: dict[str, Path] = {
    "inter_regular": _FONTS_ROOT / "inter" / "Inter-Regular.woff2",
    "inter_bold": _FONTS_ROOT / "inter" / "Inter-Bold.woff2",
    "space_grotesk_regular": _FONTS_ROOT / "space-grotesk" / "SpaceGrotesk-Regular.woff2",
    "space_grotesk_bold": _FONTS_ROOT / "space-grotesk" / "SpaceGrotesk-Bold.woff2",
}


@lru_cache(maxsize=1)
def _shipped_font_data_uris() -> dict[str, str]:
    """The shipped fonts' own bytes as ``data:`` URIs, cached for the life
    of the process (package data never changes underneath a running
    build)."""
    return {
        key: _data_uri("font/woff2", path.read_bytes()) for key, path in _SHIPPED_FONT_FILES.items()
    }


#: The shipped-font data-URI keys (:func:`_shipped_font_data_uris`) for each
#: :data:`~vectorpress.domain.brand.SHIPPED_FONT_FAMILIES` name.
_SHIPPED_FONT_KEYS: dict[str, tuple[str, str]] = {
    "Inter": ("inter_regular", "inter_bold"),
    "Space Grotesk": ("space_grotesk_regular", "space_grotesk_bold"),
}

#: A catalog font file's ``(data: URI mime type, CSS @font-face format
#: keyword)`` by its extension -- the three ADR 0014 allows
#: (:data:`~vectorpress.domain.brand.FONT_FILE_EXTENSIONS`).
_FONT_FILE_FORMATS: dict[str, tuple[str, str]] = {
    ".ttf": ("font/ttf", "truetype"),
    ".otf": ("font/otf", "opentype"),
    ".woff2": ("font/woff2", "woff2"),
}


def _shipped_font(family: str) -> PreviewFont:
    """The :class:`PreviewFont` for a family this tool ships. ``load_brand``
    has already refused any brand naming a family that is neither this nor
    backed by its own font file (ADR 0014), so ``family`` is always one of
    :data:`~vectorpress.domain.brand.SHIPPED_FONT_FAMILIES` by the time a
    build reaches here."""
    data_uris = _shipped_font_data_uris()
    regular_key, bold_key = _SHIPPED_FONT_KEYS[family]
    return PreviewFont(
        family=family,
        regular_url=data_uris[regular_key],
        bold_url=data_uris[bold_key],
        format="woff2",
    )


def _catalog_font(root: Path, family: str, font_file: str) -> PreviewFont:
    """A brand's own font file as a :class:`PreviewFont` (ADR 0014): the one
    file it names serves both weights, since a brand supplies only one file
    per role. ``load_brand`` has already confirmed the file exists under the
    catalog root and has one of the three allowed extensions before a build
    ever reaches here."""
    path = root / font_file
    mime, css_format = _FONT_FILE_FORMATS[path.suffix.lower()]
    data_uri = _data_uri(mime, path.read_bytes())
    return PreviewFont(family=family, regular_url=data_uri, bold_url=data_uri, format=css_format)


def _preview_font(root: Path, family: str, font_file: str | None) -> PreviewFont:
    """One ADR 0015 typography role's :class:`PreviewFont`: its own catalog
    font file when the brand names one, else the shipped font of that name
    -- ``load_brand`` guarantees one or the other holds before a build ever
    reaches here (ADR 0014: "a font never silently falls back")."""
    if font_file is not None:
        return _catalog_font(root, family, font_file)
    return _shipped_font(family)


def _font_presentation_inputs(root: Path, brand: Brand) -> list[tuple[str, bytes]]:
    """``(identifier, bytes)`` for the file(s) backing each of ``brand``'s
    two typography roles (ADR 0014's presentation hash: "the mark and font
    file bytes"): a catalog font file's own bytes, or the shipped font's
    regular and bold files when the brand names none -- the same choice
    :func:`_preview_font` makes for the template context, returning raw
    file identity here instead of a ``data:`` URI."""
    inputs: list[tuple[str, bytes]] = []
    for role, family, font_file in (
        ("heading", brand.typography.heading_font, brand.typography.heading_font_file),
        ("body", brand.typography.body_font, brand.typography.body_font_file),
    ):
        if font_file is not None:
            inputs.append((f"font:{role}:{font_file}", (root / font_file).read_bytes()))
        else:
            for key in _SHIPPED_FONT_KEYS[family]:
                inputs.append((f"font:{role}:shipped:{key}", _SHIPPED_FONT_FILES[key].read_bytes()))
    return inputs


def _preview_brand(root: Path, brand: Brand) -> PreviewBrand:
    return PreviewBrand(
        name=brand.name,
        mark_url=_mark_data_uri(root, brand),
        heading_font=_preview_font(
            root, brand.typography.heading_font, brand.typography.heading_font_file
        ),
        body_font=_preview_font(root, brand.typography.body_font, brand.typography.body_font_file),
        colors=PreviewBrandColors(
            background_color=brand.card_style.background_color,
            accent_color=brand.card_style.accent_color,
            text_color=brand.card_style.text_color,
        ),
    )


def _preview_product(
    product: Product, files_by_folder: dict[str, list[str]], member_count: int
) -> PreviewProduct:
    assert product.listing is not None  # build_product's own listing gate already refused
    return PreviewProduct(
        slug=product.slug,
        title=product.listing.title,
        short_title=product.listing.short_title,
        tier=product.tier.value,
        family=product.family,
        member_count=member_count,
        derivative_types=[
            PreviewDerivativeType(value=t.value, label=_DERIVATIVE_TYPE_LABELS[t])
            for t in product.derivative_types
        ],
        formats=[
            PreviewFormat(
                value=fmt.value,
                label=_FORMAT_LABELS[fmt],
                file_count=len(files_by_folder.get(fmt.value.upper(), [])),
            )
            for fmt in product.formats
        ],
    )


def _stand_in_image_url(content_by_type: dict[DerivativeType, bytes]) -> str:
    for candidate in _STAND_IN_PREFERENCE:
        content = content_by_type.get(candidate)
        if content is not None:
            return _data_uri(_derivative_mime(candidate), content)
    # None of the four stand-in types is included: no product in this
    # slice's own fixtures hits this (every fixture includes at least one),
    # so a blank image is the documented fallback rather than a raised error.
    return ""


def _images_by_type(content_by_type: dict[DerivativeType, bytes]) -> dict[str, str]:
    return {
        derivative_type.value: _data_uri(_derivative_mime(derivative_type), content)
        for derivative_type, content in content_by_type.items()
    }


def _members_by_display_name(
    eligible_members: list[ProductMember], assets_by_id: dict[AssetId, Asset]
) -> list[ProductMember]:
    return sorted(eligible_members, key=lambda member: assets_by_id[member.asset_id].display_name)


def _preview_member(
    member: ProductMember,
    assets_by_id: dict[AssetId, Asset],
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
) -> PreviewMember:
    asset = assets_by_id[member.asset_id]
    content_by_type = content_by_member.get(member.asset_id, {})
    return PreviewMember(
        display_name=asset.display_name,
        image_url=_stand_in_image_url(content_by_type),
        images_by_type=_images_by_type(content_by_type),
    )


def preview_members(
    eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
) -> list[PreviewMember]:
    """Every eligible member as a :class:`PreviewMember` (§16: "drawn only
    from the manifest's included members... using each member's effective
    derivative"), in display-name order -- the order ``included`` and
    ``contents`` read directly. ``main`` and ``variants`` read ``featured``
    instead (:func:`_featured_members`), a reordering of this same list, not
    a second, separately-built one."""
    return [
        _preview_member(member, assets_by_id, content_by_member)
        for member in _members_by_display_name(eligible_members, assets_by_id)
    ]


def _featured_asset_ids(
    product: Product, members_by_display_name: list[ProductMember]
) -> list[AssetId]:
    """§16's featured order: ``[previews] featured``'s own asset IDs, in
    listed order, then the rest of this build's eligible members in
    ``members_by_display_name``'s own order (CONTEXT.md "Featured member").
    A listed ID resolved but excluded from this build is simply absent from
    ``members_by_display_name``, so it drops out here without error -- an
    ID that names no resolved member at all is a product metadata problem
    product resolution already reported
    (:func:`~vectorpress.build.product_resolution.featured_reference_problems`).
    """
    eligible_ids = {member.asset_id for member in members_by_display_name}
    listed = product.previews.featured if product.previews is not None else []
    leading = [asset_id for asset_id in listed if asset_id in eligible_ids]
    leading_ids = set(leading)
    rest = [
        member.asset_id for member in members_by_display_name if member.asset_id not in leading_ids
    ]
    return [*leading, *rest]


def _featured_members(
    product: Product,
    members_by_display_name: list[ProductMember],
    previews_by_asset_id: dict[AssetId, PreviewMember],
) -> list[PreviewMember]:
    return [
        previews_by_asset_id[asset_id]
        for asset_id in _featured_asset_ids(product, members_by_display_name)
    ]


def _render_html(
    environment: Environment, root: Path, template_name: str, **context: object
) -> str:
    # Every value a template can read arrives through this one ``context``
    # (ADR 0015's own fixed shape) -- nothing is ever added to the
    # environment's or the template's own globals, which StrictUndefined
    # does not gate: a catalog override reading anything else must still
    # fail, exactly the same as reading an unrelated undefined name.
    template = environment.get_template(template_name)
    try:
        return template.render(**context)
    except UndefinedError as exc:
        name = template_name_from_traceback(exc, root, PREVIEWS_KIND) or template_name
        raise PreviewRenderError(str(exc), template_name=name) from exc


@dataclass(frozen=True)
class _PreviewContext:
    """The parts of the ADR 0015 context that never vary by canvas or page:
    computed once per build (:func:`_preview_context`), never rebuilt per
    (type, canvas) render."""

    brand: PreviewBrand
    product: PreviewProduct
    members: list[PreviewMember]
    featured: list[PreviewMember]


def _preview_context(
    root: Path,
    product: Product,
    brand: Brand,
    eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
    files_by_folder: dict[str, list[str]],
) -> _PreviewContext:
    ordered_members = _members_by_display_name(eligible_members, assets_by_id)
    previews_by_asset_id = {
        member.asset_id: _preview_member(member, assets_by_id, content_by_member)
        for member in ordered_members
    }
    members = [previews_by_asset_id[member.asset_id] for member in ordered_members]
    return _PreviewContext(
        brand=_preview_brand(root, brand),
        product=_preview_product(product, files_by_folder, len(eligible_members)),
        members=members,
        featured=_featured_members(product, ordered_members, previews_by_asset_id),
    )


def _template_context(
    context: _PreviewContext, canvas: Canvas, page: PreviewPage | None
) -> dict[str, object]:
    # ``page`` is ``None`` for every type but ``contents`` (ADR 0015: "exists
    # for contents"). It is still passed for the rest, since ADR 0015 fixes
    # ``page`` as part of every preview's context, read or not.
    return {
        "canvas": canvas,
        "brand": context.brand,
        "product": context.product,
        "members": context.members,
        "featured": context.featured,
        "page": page,
    }


def render_preview_html(
    root: Path,
    preview_type: PreviewType,
    canvas: Canvas,
    product: Product,
    brand: Brand,
    eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
    files_by_folder: dict[str, list[str]],
    page: PreviewPage | None = None,
) -> str:
    """One preview type's rendered HTML for one canvas (§16) -- Jinja only,
    no Chromium, so a template's own undefined-variable problem is caught
    here without ever launching a browser. The same fixed context (ADR
    0015) serves every type; only ``preview_type.template_name`` differs.
    ``page`` is only ever set for ``contents`` (ADR 0015: "exists for
    contents"). Raises :class:`PreviewRenderError` naming the offending
    template."""
    environment = template_environment(root, PREVIEWS_KIND)
    context = _preview_context(
        root, product, brand, eligible_members, assets_by_id, content_by_member, files_by_folder
    )
    return _render_html(
        environment, root, preview_type.template_name, **_template_context(context, canvas, page)
    )


# --- Chromium rendering: one reused browser per process, no network (ADR 0014) --

_playwright: Playwright | None = None
_browser: Browser | None = None


def _browser_instance() -> Browser:
    """The one Chromium instance every preview render reuses -- launched on
    first use and kept for the life of the process (many builds render
    previews in one ``vpress`` invocation or test run; a fresh browser per
    build would dominate the cost). Relaunched whenever the cached one is no
    longer connected (a crashed or killed browser process), so a retry after
    a transient failure (:func:`_screenshot`) always gets a live browser.
    Never explicitly closed otherwise: process exit tears it down, the same
    lifetime Playwright's own examples use for a long-lived host process."""
    global _playwright, _browser
    if _browser is not None and _browser.is_connected():
        return _browser
    try:
        if _playwright is None:
            _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch()
    except PlaywrightError as exc:
        raise PreviewRenderError(f"Chromium is unavailable: {exc}") from exc
    return _browser


def _guard_disallowed_requests(violations: list[str]) -> Callable[[Route], None]:
    def handle(route: Route) -> None:
        url = route.request.url
        # Every shipped template embeds its own images and fonts as data:
        # URIs (this module's own docstring): the only way a render ever
        # asks for anything else is a catalog override linking out.
        if url.startswith("data:") or url.startswith("about:"):
            route.continue_()
            return
        violations.append(url)
        route.abort()

    return handle


class _DisallowedRequestError(Exception):
    """One render requested a URL the Chromium route guard does not allow
    (ADR 0014). Its own exception, never a :class:`PlaywrightError`
    subclass, so :func:`_screenshot` can never mistake a route-guard
    violation for a transient Chromium failure worth retrying."""

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.url = url


def _render_screenshot(html: str, canvas: Canvas) -> bytes:
    """One attempt at screenshotting already-rendered ``html`` on a fresh
    page (ADR 0014: no network, no system fonts). Raises
    :class:`_DisallowedRequestError` for a route-guard violation, or lets a
    Chromium :class:`PlaywrightError` propagate -- :func:`_screenshot` is
    the one that decides whether either is worth a retry."""
    browser = _browser_instance()
    page = browser.new_page(viewport={"width": canvas.width, "height": canvas.height})
    violations: list[str] = []
    try:
        page.route("**/*", _guard_disallowed_requests(violations))
        page.set_content(html, wait_until="load")
        png_bytes = page.screenshot(type="png")
    finally:
        page.close()

    if violations:
        raise _DisallowedRequestError(violations[0])
    return png_bytes


#: Substrings of a Chromium :class:`PlaywrightError` that mark it as a
#: transient renderer hiccup -- a dropped DevTools connection or a killed
#: render target -- rather than a real problem with the page: worth one
#: retry on a fresh page (and, if the browser itself is no longer connected,
#: a fresh browser) instead of refusing a real build over it. CI has hit
#: ``Page.screenshot: Protocol error (Page.captureScreenshot): Unable to
#: capture screenshot`` this way, with nothing wrong in the rendered page.
_TRANSIENT_CHROMIUM_ERROR_MARKERS = ("Protocol error", "Target closed", "has been closed")


def _is_transient_chromium_error(exc: PlaywrightError) -> bool:
    message = str(exc)
    return any(marker in message for marker in _TRANSIENT_CHROMIUM_ERROR_MARKERS)


def _screenshot(html: str, canvas: Canvas, template_name: str) -> bytes:
    """One canvas's PNG bytes for already-rendered ``html``. A transient
    Chromium failure (:func:`_is_transient_chromium_error`) is retried once,
    on a fresh page and, if the browser itself dropped, a fresh browser
    (:func:`_browser_instance`) -- a route-guard violation or a second
    failure still fails the render, naming the template."""
    attempts_left = 2
    while True:
        attempts_left -= 1
        try:
            return _render_screenshot(html, canvas)
        except _DisallowedRequestError as exc:
            raise PreviewRenderError(
                f"{template_name} requested a disallowed URL: {exc.url}",
                template_name=template_name,
            ) from exc
        except PlaywrightError as exc:
            if attempts_left <= 0 or not _is_transient_chromium_error(exc):
                raise PreviewRenderError(
                    f"Chromium failed to render {template_name}: {exc}",
                    template_name=template_name,
                ) from exc
            # One transient failure, one retry left: loop back for a fresh
            # page (and, via _browser_instance, a fresh browser if needed).


@dataclass(frozen=True)
class PreviewRenderResult:
    """:func:`render_previews`'s own result: the rendered preview files,
    the catalog ``templates/previews/`` overrides this render actually used
    (ADR 0015's build report list), and the ADR 0014 presentation hash --
    all drawn from the one environment every type/canvas render shares, so
    the override list and the hash reflect exactly this build's own
    renders, not merely what the catalog's ``templates/previews/`` folder
    happens to hold."""

    files: list[tuple[str, bytes]]
    template_overrides: list[str]
    presentation_hash: str


def _presentation_hash(root: Path, product: Product, brand: Brand, environment: Environment) -> str:
    """The ADR 0014 presentation hash: every template file ``environment``
    actually loaded (shipped or catalog override), brand's own ``name``,
    ``typography`` and ``card_style``, the mark and font file bytes, and
    the listing fields previews print (``title``, ``short_title``) -- never
    a member image, never rights status (ADR 0015: rights status is not in
    the preview context at all). ``environment`` must already have rendered
    every template a build would use -- :func:`render_previews` calls this
    once its own render loop is done; :func:`current_presentation_hash`
    drives an equivalent, Chromium-free render purely to populate one.
    """
    assert product.listing is not None  # build_product's own listing gate already refused
    payload = {
        "templates": [
            {"name": name, "content_hash": sha256_bytes(path.read_bytes())}
            for name, path in used_template_files(environment)
        ],
        "brand": {
            "name": brand.name,
            "typography": brand.typography.model_dump(),
            "card_style": brand.card_style.model_dump(),
        },
        "mark": sha256_bytes((root / brand.mark_file).read_bytes()),
        "fonts": [
            {"name": name, "content_hash": sha256_bytes(content)}
            for name, content in _font_presentation_inputs(root, brand)
        ],
        "listing": {
            "title": product.listing.title,
            "short_title": product.listing.short_title,
        },
    }
    return sha256_bytes(json.dumps(payload, sort_keys=True).encode("utf-8"))


def current_presentation_hash(
    root: Path,
    product: Product,
    brand: Brand,
    eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
    files_by_folder: dict[str, list[str]],
) -> str:
    """The presentation hash a build would currently write (ADR 0014),
    computed with a pure Jinja render of every preview type/page a build
    would render -- no Chromium -- so needs-rebuild can compare it without
    paying for a browser. Renders the identical loop
    :func:`render_previews` does, minus the screenshot step: the set of
    template files a render touches is decided entirely by Jinja
    (``{% extends %}``/``{% include %}``), never by Chromium.

    Raises :class:`PreviewRenderError` the same way :func:`render_previews`
    would, on an undefined template variable or a template naming a file
    that fails to load -- an actual rebuild would refuse identically.
    """
    environment = template_environment(root, PREVIEWS_KIND)
    context = _preview_context(
        root, product, brand, eligible_members, assets_by_id, content_by_member, files_by_folder
    )
    for preview_type in PREVIEW_TYPES:
        if not _renders(preview_type, product, len(context.members)):
            continue
        for page in _pages(preview_type, len(context.members)):
            for canvas in CANVASES:
                _render_html(
                    environment,
                    root,
                    preview_type.template_name,
                    **_template_context(context, canvas, page),
                )
    return _presentation_hash(root, product, brand, environment)


def render_previews(
    root: Path,
    product: Product,
    brand: Brand,
    eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
    files_by_folder: dict[str, list[str]],
) -> PreviewRenderResult:
    """Render every :data:`PREVIEW_TYPES` entry that applies at both fixed
    canvases (§16): ``(path under previews/, PNG bytes)`` pairs, sizes
    exactly matching each :data:`Canvas`. ``variants`` and ``contents`` are
    skipped (:func:`_renders`) when the product does not meet their own
    condition; ``contents`` otherwise renders once per page (:func:`_pages`).
    The canvas- and member-independent context is built once
    (:func:`_preview_context`) and reused across every type/page/canvas
    combination, not rebuilt per render.

    Raises :class:`PreviewRenderError` on an undefined template variable, a
    template requesting a disallowed URL, or Chromium itself failing --
    :func:`~vectorpress.build.product_build.build_product` turns any of
    these into a whole-build refusal, per this module's own docstring.
    The result's own presentation hash (:func:`_presentation_hash`, ADR
    0014) is computed once, after every render, from the one environment
    every type/canvas shares.
    """
    environment = template_environment(root, PREVIEWS_KIND)
    context = _preview_context(
        root, product, brand, eligible_members, assets_by_id, content_by_member, files_by_folder
    )
    results: list[tuple[str, bytes]] = []
    for preview_type in PREVIEW_TYPES:
        if not _renders(preview_type, product, len(context.members)):
            continue
        for page in _pages(preview_type, len(context.members)):
            name = preview_type.name
            if page is not None:
                name = f"{name}-{page.number}"
            for canvas in CANVASES:
                html = _render_html(
                    environment,
                    root,
                    preview_type.template_name,
                    **_template_context(context, canvas, page),
                )
                png_bytes = _screenshot(html, canvas, preview_type.template_name)
                results.append(
                    (f"previews/{preview_type.number}-{name}-{canvas.name}.png", png_bytes)
                )
    return PreviewRenderResult(
        files=results,
        template_overrides=used_overrides(environment),
        presentation_hash=_presentation_hash(root, product, brand, environment),
    )


def _renders(preview_type: PreviewType, product: Product, member_count: int) -> bool:
    """Whether one conditional preview type is rendered at all (§16): ``04
    variants`` needs 2 or more of the product's own derivative types; ``05
    contents`` needs more than 12 members. Every unconditional type (``01``-
    ``03``) always renders. A left-out type leaves its own number unused,
    rather than reserved by a placeholder file."""
    if preview_type.name == "variants":
        return len(product.derivative_types) >= 2
    if preview_type.name == "contents":
        return member_count > 12
    return True


def _pages(preview_type: PreviewType, member_count: int) -> list[PreviewPage | None]:
    """The pages one preview type renders at (§16): ``[None]`` for every
    type but ``contents``, which paginates at :data:`CONTENTS_PAGE_SIZE` per
    page -- ``ceil(member_count / CONTENTS_PAGE_SIZE)`` pages, numbered from
    1. The page's own member slice is the template's job (``members[start:
    start + page_size]``), the same way ``included`` caps to 12 inside its
    own template rather than through a context field ADR 0015 does not
    document."""
    if preview_type.name != "contents":
        return [None]
    page_count = -(-member_count // CONTENTS_PAGE_SIZE)  # ceiling division
    return [PreviewPage(number=number, count=page_count) for number in range(1, page_count + 1)]
