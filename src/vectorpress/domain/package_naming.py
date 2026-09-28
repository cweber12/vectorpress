"""Customer-facing package and ZIP naming (§15, §20, CONTEXT.md "Package").

A build's package directory and ZIP, and the ZIP's single top-level folder,
share one name: the product's listing ``short_title`` when it has one, else
the product slug, rendered Title-Case-Hyphen (``"Rock-Climbing-Icons"``). No
version or date, so a rebuild replaces the previous package and ZIP in place
(§4, §36).

No I/O here (ADR 0006): a pure string transform over an already-loaded
listing's ``short_title`` and the product's own slug.
"""

import re

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def title_case_hyphen(text: str) -> str:
    """``text``'s words, capitalized and hyphen-joined: ``"tide pool"`` and
    ``"tide_pool"`` both become ``"Tide-Pool"``. A word is a run of ASCII
    letters or digits; anything else (space, underscore, hyphen) separates
    words rather than surviving into the result."""
    return "-".join(word.capitalize() for word in _WORD_RE.findall(text))


def package_name(short_title: str | None, slug: str) -> str:
    """The package directory / ZIP base name for a product (§15): its
    listing's ``short_title`` when it has one, else its ``slug`` -- either
    way, rendered :func:`title_case_hyphen`."""
    return title_case_hyphen(short_title if short_title else slug)
