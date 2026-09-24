"""Look up a generator by the name a :class:`~vectorpress.domain.recipe.Recipe`
names (issue #23).

The only place that maps a generator name to the module that implements it,
so adding a derivative type's generator (PRD 3, PRD 10) means adding one
entry here plus the module it points to, not touching every caller.
"""

from vectorpress.pipeline import transparent_png
from vectorpress.pipeline.generator import Generator

GENERATORS: dict[str, Generator] = {
    transparent_png.GENERATOR_NAME: transparent_png.generate,
}


def get_generator(name: str) -> Generator | None:
    """The generator function named ``name``, or ``None`` if there isn't
    one (a recipe with no generator yet, or an unrecognised name)."""
    return GENERATORS.get(name)
