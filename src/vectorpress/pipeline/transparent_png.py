"""The transparent PNG generator (§6.1, issue #23).

Decodes the selected source, normalises it to 8-bit RGBA with a transparent
background, crops to the tight bounding box of its non-transparent pixels
(clean bounds, no stray padding), and encodes it byte-deterministically: no
resampling, and no ancillary chunks (timestamps, ICC profiles, DPI) carried
over from the source, so the same source always produces the same bytes on
any platform (§36).

Pillow decodes, normalises and crops, but does **not** encode the PNG: its
PNG encoder delegates compression to whichever zlib its wheel bundles, and
that bundled zlib differs between Pillow's linux and windows wheels, so the
same pixels produced different IDAT bytes on ubuntu vs. windows CI (issue
#23 fix round 1). Encoding the PNG here instead, with CPython's own stdlib
``zlib`` at a fixed level, is byte-deterministic across platforms: the
interpreter's ``zlib`` module is classic zlib on every CI runner this
project targets, and DEFLATE output depends only on the input bytes, level
and strategy -- never on the OS. This is the same minimal PNG encoder the
committed fixture script (``tests/fixtures/catalog/generate_source_pngs.py``)
already uses for exactly this reason.
"""

import struct
import zlib
from collections.abc import Mapping
from pathlib import Path

import PIL
from PIL import Image

from vectorpress.pipeline.generator import GeneratorOutput

#: This recipe's generator name (:attr:`vectorpress.domain.recipe.Recipe.generator`).
GENERATOR_NAME = "transparent_png"

#: A fixed, deterministic zlib level -- part of what makes the encoder
#: byte-deterministic (§36): the same pixels always compress to the same
#: bytes given the same level and strategy (zlib's default strategy).
_ZLIB_LEVEL = 9


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def _encode_rgba_png(width: int, height: int, raw_rgba: bytes) -> bytes:
    """Encode raw, unpadded RGBA pixel bytes (row-major, 4 bytes/pixel) as a
    minimal PNG: IHDR, a single IDAT, IEND -- no ancillary chunks, ever,
    since none is ever written. Every row uses PNG filter type 0 (None):
    simplicity over compression ratio, since a tiny craft-catalog image
    gains little from adaptive filtering and a fixed filter keeps the
    encoding trivially deterministic.
    """
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    row_stride = width * 4
    raw = b"".join(
        b"\x00" + raw_rgba[row * row_stride : (row + 1) * row_stride] for row in range(height)
    )
    idat = zlib.compress(raw, _ZLIB_LEVEL)
    return (
        b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
    )


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
        width, height = cropped.size
        raw_rgba = cropped.tobytes()

    output_bytes = _encode_rgba_png(width, height, raw_rgba)
    return GeneratorOutput(
        output_bytes=output_bytes,
        library_versions={"Pillow": PIL.__version__, "zlib": zlib.ZLIB_VERSION},
    )
