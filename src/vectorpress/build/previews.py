"""Render a product's marketplace preview images (§14, §16, ADR 0014, ADR
0015).

The thinnest end-to-end slice: only the ``main`` preview type, at both fixed
canvases. Jinja HTML/CSS templates (:mod:`vectorpress.build.template_lookup`,
kind ``previews``) are screenshotted by Playwright's headless Chromium
(ADR 0014) -- no network, no system fonts. Every image a template needs
(the brand mark, a member's effective derivative, the two shipped fonts) is
embedded as a ``data:`` URI computed here in Python, never referenced by a
relative or absolute path: a template has nothing to link to outside its own
inline content, so the only way a render can still reach the network is a
catalog override writing a URL of its own -- exactly what the Chromium
request guard below exists to catch.

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
"""

import base64
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, UndefinedError
from playwright.sync_api import Browser, Playwright, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from vectorpress.build.product_resolution import ProductMember
from vectorpress.build.template_lookup import template_environment, template_name_from_traceback
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.brand import Brand
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.format import Format
from vectorpress.domain.product import Product

#: The template lookup "kind" previews render through (ADR 0015): catalog
#: ``templates/previews/`` first, then the shipped folder of the same name.
PREVIEWS_KIND = "previews"

#: §16's fixed upload-order number for the ``main`` preview type -- the only
#: type this slice renders.
MAIN_PREVIEW_NUMBER = "01"

#: §16's "up to 9 featured members" on ``main``.
FEATURED_LIMIT = 9


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
    """One of ``brand``'s two existing ADR 0015 font fields (``heading_font``,
    ``body_font``), resolved to a font this module actually ships (ADR
    0014): ``family`` is the CSS family name ``brand.css``'s own
    ``@font-face`` rules declare and the *only* one the CSS ever references
    -- never the brand's own raw, unvalidated font name (a brand naming a
    font this tool does not ship is a later slice's metadata problem to
    catch; until then it silently maps to Inter here rather than ever
    reaching a template). ``regular_url`` and ``bold_url`` are that shipped
    family's own two weights, each a ``data:`` URI. No generic CSS fallback
    is ever paired with ``family``: pairing one (``sans-serif``, or the raw
    brand name itself) risks matching a same-named font already installed
    on the machine, exactly what ADR 0014's "no system fonts" forbids."""

    family: str
    regular_url: str
    bold_url: str


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
class PreviewMember:
    """The preview context's one member entry (ADR 0015): ``image_url`` is
    the one image that stands for this member -- the first included type in
    the fixed order ``flatcolor_svg``, ``transparent_png``, ``silhouette_svg``,
    ``cut_svg`` (§16) -- and ``images_by_type`` holds every included type's
    own image, for a later preview type (``variants``) this slice does not
    render yet. Both are ``data:`` URIs (this module's own docstring)."""

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


def _shipped_font(requested_family: str) -> PreviewFont:
    """The :class:`PreviewFont` for one ADR 0015 ``brand.heading_font`` /
    ``body_font`` value: ``requested_family`` as shipped, when it names one
    of the two this tool ships; Inter otherwise. Brand-font validation
    (ADR 0014: "else it is a brand metadata problem") is a later slice, so
    an unshipped or misspelled name is never a build failure here -- but it
    is never passed through to ``brand.css`` either, since that would let
    a same-named system font render instead (this module's own point)."""
    data_uris = _shipped_font_data_uris()
    if requested_family == "Space Grotesk":
        return PreviewFont(
            family="Space Grotesk",
            regular_url=data_uris["space_grotesk_regular"],
            bold_url=data_uris["space_grotesk_bold"],
        )
    return PreviewFont(
        family="Inter", regular_url=data_uris["inter_regular"], bold_url=data_uris["inter_bold"]
    )


def _preview_brand(root: Path, brand: Brand) -> PreviewBrand:
    return PreviewBrand(
        name=brand.name,
        mark_url=_mark_data_uri(root, brand),
        heading_font=_shipped_font(brand.typography.heading_font),
        body_font=_shipped_font(brand.typography.body_font),
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


def preview_members(
    eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
) -> list[PreviewMember]:
    """Every eligible member as a :class:`PreviewMember` (§16: "drawn only
    from the manifest's included members... using each member's effective
    derivative"), in display-name order -- the order ``main`` leads with
    absent a hand-authored ``[previews] featured`` list, which this slice
    does not read yet (CONTEXT.md "Featured member": "until the featured
    slice lands, featured is the first 9 members in display-name order")."""
    ordered = sorted(
        eligible_members, key=lambda member: assets_by_id[member.asset_id].display_name
    )
    members: list[PreviewMember] = []
    for member in ordered:
        asset = assets_by_id[member.asset_id]
        content_by_type = content_by_member.get(member.asset_id, {})
        members.append(
            PreviewMember(
                display_name=asset.display_name,
                image_url=_stand_in_image_url(content_by_type),
                images_by_type=_images_by_type(content_by_type),
            )
        )
    return members


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


def render_main_html(
    root: Path,
    canvas: Canvas,
    product: Product,
    brand: Brand,
    eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
    files_by_folder: dict[str, list[str]],
) -> str:
    """The ``main`` preview's rendered HTML for one canvas (§16) -- Jinja
    only, no Chromium, so a template's own undefined-variable problem is
    caught here without ever launching a browser. Raises
    :class:`PreviewRenderError` naming the offending template."""
    environment = template_environment(root, PREVIEWS_KIND)
    members = preview_members(eligible_members, assets_by_id, content_by_member)
    context = {
        "canvas": canvas,
        "brand": _preview_brand(root, brand),
        "product": _preview_product(product, files_by_folder, len(eligible_members)),
        "members": members,
        "featured": members[:FEATURED_LIMIT],
        "page": None,
    }
    return _render_html(environment, root, "main.html.j2", **context)


# --- Chromium rendering: one reused browser per process, no network (ADR 0014) --

_playwright: Playwright | None = None
_browser: Browser | None = None


def _browser_instance() -> Browser:
    """The one Chromium instance every preview render reuses -- launched on
    first use and kept for the life of the process (many builds render
    previews in one ``vpress`` invocation or test run; a fresh browser per
    build would dominate the cost). Never explicitly closed: process exit
    tears it down, the same lifetime Playwright's own examples use for a
    long-lived host process."""
    global _playwright, _browser
    if _browser is not None:
        return _browser
    try:
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


def _screenshot(html: str, canvas: Canvas, template_name: str) -> bytes:
    """One canvas's PNG bytes for already-rendered ``html`` (ADR 0014: no
    network, no system fonts -- every request but the shipped templates'
    own ``data:`` URIs is aborted and fails the render, naming the URL)."""
    browser = _browser_instance()
    page = browser.new_page(viewport={"width": canvas.width, "height": canvas.height})
    violations: list[str] = []
    try:
        page.route("**/*", _guard_disallowed_requests(violations))
        page.set_content(html, wait_until="load")
        png_bytes = page.screenshot(type="png")
    except PlaywrightError as exc:
        raise PreviewRenderError(
            f"Chromium failed to render {template_name}: {exc}", template_name=template_name
        ) from exc
    finally:
        page.close()

    if violations:
        raise PreviewRenderError(
            f"{template_name} requested a disallowed URL: {violations[0]}",
            template_name=template_name,
        )
    return png_bytes


def render_main_previews(
    root: Path,
    product: Product,
    brand: Brand,
    eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
    files_by_folder: dict[str, list[str]],
) -> list[tuple[str, bytes]]:
    """Render the ``main`` preview at both fixed canvases (§16 nn=``01``,
    the only preview type this slice builds): ``(path under previews/,
    PNG bytes)`` pairs, sizes exactly matching each :data:`Canvas`.

    Raises :class:`PreviewRenderError` on an undefined template variable, a
    template requesting a disallowed URL, or Chromium itself failing --
    :func:`~vectorpress.build.product_build.build_product` turns any of
    these into a whole-build refusal, per this module's own docstring.
    """
    results: list[tuple[str, bytes]] = []
    for canvas in CANVASES:
        html = render_main_html(
            root,
            canvas,
            product,
            brand,
            eligible_members,
            assets_by_id,
            content_by_member,
            files_by_folder,
        )
        png_bytes = _screenshot(html, canvas, "main.html.j2")
        results.append((f"previews/{MAIN_PREVIEW_NUMBER}-main-{canvas.name}.png", png_bytes))
    return results
