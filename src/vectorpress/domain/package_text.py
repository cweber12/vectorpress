"""Compose a build's two brand-supplied plain-text package files (§14, §27,
CONTEXT.md "Brand config", "Package"): ``LICENSE.txt`` from the catalog's
license template, and ``README.txt`` from brand wording plus what the build
actually contains.

No I/O here (ADR 0006): both functions take already-loaded strings and
already-resolved build facts. Reading the license template off disk, and
gathering which files and formats a build contains, is the build layer's
job.
"""

import json
import re
from collections.abc import Mapping

from vectorpress.domain.numeric_format import format_number

#: Matches one ``{placeholder}`` token in a license template: an opening
#: brace, an identifier, a closing brace. Anything else in curly braces
#: (there is no escape syntax) is left untouched by :func:`render_license_text`.
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class UnknownLicensePlaceholderError(Exception):
    """A license template names a placeholder besides ``brand``, ``product``,
    ``copyright`` or ``year`` (§27). Carries every such name found, sorted,
    so a build refuses and names all of them at once rather than shipping a
    license with a literal, unfilled ``{...}`` in it.
    """

    def __init__(self, placeholders: list[str]) -> None:
        self.placeholders = placeholders
        super().__init__(f"unknown license placeholder(s): {', '.join(placeholders)}")


def render_license_text(
    template: str,
    *,
    brand_name: str,
    product_title: str,
    copyright_wording: str,
    year: int,
) -> str:
    """``template`` with every ``{brand}``, ``{product}``, ``{copyright}``
    and ``{year}`` substituted (§27) -- the same substitution regardless of
    an included asset's rights status; the tool never varies license
    wording by it. Raises :class:`UnknownLicensePlaceholderError` naming
    every other ``{placeholder}`` the template uses instead of substituting
    it.
    """
    substitutions = {
        "brand": brand_name,
        "product": product_title,
        "copyright": copyright_wording,
        "year": str(year),
    }
    unknown: set[str] = set()

    def _substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in substitutions:
            return substitutions[name]
        unknown.add(name)
        return match.group(0)

    rendered = _PLACEHOLDER_RE.sub(_substitute, template)
    if unknown:
        raise UnknownLicensePlaceholderError(sorted(unknown))
    return rendered


def render_readme_text(
    *,
    intro: str,
    standard_wording: str,
    copyright_wording: str,
    included_formats: list[str],
    files_by_folder: Mapping[str, list[str]],
    reference_size_in: float,
) -> str:
    """``README.txt``'s full text (§27): the brand's own ``readme_text``
    (``intro``) and ``standard_wording``, the package's included formats
    and file list by folder, the reference size the files are checked at
    (the packaged SVG itself carries no physical units), and
    ``copyright_wording``.

    Plain text with stable ordering -- formats and folders alphabetically,
    filenames alphabetically within each folder -- so an unchanged build's
    ``README.txt`` is byte-identical every time (§36).
    """
    lines: list[str] = [intro.strip(), "", standard_wording, ""]
    lines.append(f"Included formats: {', '.join(sorted(included_formats))}")
    lines.append("")
    lines.append("Included files:")
    for folder in sorted(files_by_folder):
        lines.append(f"{folder}/")
        lines.extend(f"  {filename}" for filename in sorted(files_by_folder[folder]))
    lines.append("")
    lines.append(f"Files checked at reference size: {format_number(reference_size_in)}in")
    lines.append("")
    lines.append(copyright_wording)
    return "\n".join(lines) + "\n"


def readme_wording_fingerprint(intro: str, standard_wording: str, copyright_wording: str) -> str:
    """A stable string over README.txt's brand-authored wording alone --
    ``intro``, ``standard_wording`` and ``copyright_wording`` -- distinct
    from the file list and reference size :func:`render_readme_text` also
    weaves in, which come from what a build actually contains rather than
    from the brand (§23, §27, ADR 0004). A build's manifest hashes this, so
    a wording edit is a needs-rebuild reason on its own, never conflated
    with a membership change. ``json.dumps(..., sort_keys=True)`` makes it
    independent of argument order."""
    payload = {
        "intro": intro,
        "standard_wording": standard_wording,
        "copyright_wording": copyright_wording,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
