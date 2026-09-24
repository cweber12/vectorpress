"""The common generator interface every derivative-type module implements
(ADR 0006: "pipeline: derivative generators, one module per derivative type
behind a common interface").

No filesystem writes here: a generator only decodes a source file and
returns bytes plus the library versions it used; persisting those bytes
alongside a provenance record is ``catalog.provenance``'s job (ADR 0006's
"catalog... the only layer touching catalog files"), driven by
:mod:`vectorpress.pipeline.generate`.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GeneratorOutput:
    """What one generator run produced.

    ``library_versions`` names every third-party library the generator used
    and the version it ran with (e.g. ``{"Pillow": "12.3.0"}``), recorded in
    provenance alongside vectorpress's own version (ADR 0004).
    """

    output_bytes: bytes
    library_versions: dict[str, str]


#: A generator decodes the source file at ``Path``, applies ``parameters``
#: (a recipe's :attr:`~vectorpress.domain.recipe.Recipe.parameters`), and
#: returns the encoded output plus the library versions it used.
Generator = Callable[[Path, Mapping[str, object]], GeneratorOutput]
