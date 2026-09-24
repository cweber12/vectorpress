"""The transparent PNG generator (§6.1, issue #23).

Decodes the selected source, normalises it to 8-bit RGBA with a transparent
background, crops to the tight bounding box of its non-transparent pixels
(clean bounds, no stray padding), and encodes it byte-deterministically: no
resampling, and no ancillary chunks (timestamps, ICC profiles, DPI) carried
over from the source, so the same source always produces the same bytes on
any platform (§36).
"""

from collections.abc import Mapping
from io import BytesIO
from pathlib import Path

import PIL
from PIL import Image

from vectorpress.pipeline.generator import GeneratorOutput

#: This recipe's generator name (:attr:`vectorpress.domain.recipe.Recipe.generator`).
GENERATOR_NAME = "transparent_png"


def generate(source_path: Path, parameters: Mapping[str, object]) -> GeneratorOutput:
    """Produce a transparent PNG from ``source_path`` (§6.1).

    ``parameters`` is unused: this generator has none yet, but takes the
    common generator signature (:data:`vectorpress.pipeline.generator.Generator`)
    so a later parameter (e.g. a padding margin) can be added without
    changing the interface.
    """
    with Image.open(source_path) as source:
        rgba = source.convert("RGBA")
        bbox = rgba.getchannel("A").getbbox()
        cropped = rgba.crop(bbox) if bbox is not None else rgba
        # Rebuild from raw pixel bytes rather than saving ``cropped``
        # directly: the decoded source can carry ancillary info (DPI, ICC
        # profile, text chunks) in ``.info`` that Pillow would otherwise
        # re-encode into the output, breaking byte-determinism and
        # violating "no ancillary chunks".
        clean = Image.frombytes("RGBA", cropped.size, cropped.tobytes())

    buffer = BytesIO()
    clean.save(buffer, format="PNG")
    return GeneratorOutput(
        output_bytes=buffer.getvalue(),
        library_versions={"Pillow": PIL.__version__},
    )
