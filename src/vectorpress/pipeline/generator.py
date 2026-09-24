"""The common generator interface every derivative-type module implements
(ADR 0006: "pipeline: derivative generators, one module per derivative type
behind a common interface").

No filesystem access here at all -- not even a read: a generator takes the
source's bytes (already read by ``catalog.provenance.read_source_bytes``)
and returns output bytes plus the library versions it used. Persisting those
bytes alongside a provenance record is also ``catalog.provenance``'s job
(ADR 0006's "catalog... the only layer touching catalog files"); a generator
never opens a path itself, so it stays a pure bytes-in, bytes-out function
(issue #23 review fix round 2).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratorOutput:
    """What one generator run produced.

    ``library_versions`` names every third-party library the generator used
    and the version it ran with (e.g. ``{"Pillow": "12.3.0"}``), recorded in
    provenance alongside vectorpress's own version (ADR 0004).
    """

    output_bytes: bytes
    library_versions: dict[str, str]


#: A generator decodes ``source_bytes`` (already read off disk by the
#: catalog layer), applies ``parameters`` (a recipe's
#: :attr:`~vectorpress.domain.recipe.Recipe.parameters`), and returns the
#: encoded output plus the library versions it used -- no filesystem access.
Generator = Callable[[bytes, Mapping[str, object]], GeneratorOutput]
