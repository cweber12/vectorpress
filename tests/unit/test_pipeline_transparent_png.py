"""pipeline.transparent_png: the transparent PNG generator (§6.1, issue #23).

Builds its own tiny source PNGs with Pillow, in memory, rather than reading
the fixture catalog: this module's job is the generator's pixel behaviour,
not catalog wiring (that is ``tests/integration/test_generate.py``'s job).
No filesystem is touched anywhere in this file -- the generator takes bytes,
not a path (ADR 0006, issue #23 review fix round 2).
"""

import struct
from io import BytesIO

from PIL import Image

from vectorpress.pipeline.transparent_png import generate

Rgba = tuple[int, int, int, int]

TRANSPARENT: Rgba = (0, 0, 0, 0)
OPAQUE: Rgba = (196, 93, 38, 255)


def _source_bytes(pixels: list[list[Rgba]]) -> bytes:
    """An RGBA PNG's bytes, from a row-major grid of ``(r, g, b, a)`` pixels."""
    height = len(pixels)
    width = len(pixels[0])
    image = Image.new("RGBA", (width, height))
    for y, row in enumerate(pixels):
        for x, pixel in enumerate(row):
            image.putpixel((x, y), pixel)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _open_bytes(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data))


def _pixel(image: Image.Image, xy: tuple[int, int]) -> Rgba:
    pixel = image.convert("RGBA").getpixel(xy)
    assert isinstance(pixel, tuple) and len(pixel) == 4
    r, g, b, a = pixel
    return (int(r), int(g), int(b), int(a))


def test_output_is_8_bit_rgba() -> None:
    source_bytes = _source_bytes([[OPAQUE, OPAQUE], [OPAQUE, OPAQUE]])

    result = generate(source_bytes, {})

    with _open_bytes(result.output_bytes) as out:
        assert out.mode == "RGBA"
        assert _pixel(out, (0, 0)) == OPAQUE


def test_crops_to_the_tight_bounding_box_of_non_transparent_pixels() -> None:
    """A 4x4 canvas with a 2x2 opaque block in one corner and transparent
    padding everywhere else crops down to just the 2x2 content (clean
    bounds, §8)."""
    grid = [
        [TRANSPARENT, TRANSPARENT, TRANSPARENT, TRANSPARENT],
        [TRANSPARENT, OPAQUE, OPAQUE, TRANSPARENT],
        [TRANSPARENT, OPAQUE, OPAQUE, TRANSPARENT],
        [TRANSPARENT, TRANSPARENT, TRANSPARENT, TRANSPARENT],
    ]
    source_bytes = _source_bytes(grid)

    result = generate(source_bytes, {})

    with _open_bytes(result.output_bytes) as out:
        assert out.size == (2, 2)
        assert all(_pixel(out, (x, y)) == OPAQUE for x in range(2) for y in range(2))


def test_transparent_background_outside_the_shape_is_preserved() -> None:
    """A ring (a shape with a hole) keeps its hole transparent after
    cropping -- the crop is a bounding box, not a re-fill."""
    grid = [
        [OPAQUE, OPAQUE, OPAQUE],
        [OPAQUE, TRANSPARENT, OPAQUE],
        [OPAQUE, OPAQUE, OPAQUE],
    ]
    source_bytes = _source_bytes(grid)

    result = generate(source_bytes, {})

    with _open_bytes(result.output_bytes) as out:
        assert out.size == (3, 3)
        assert _pixel(out, (1, 1))[3] == 0  # the hole stays transparent
        assert _pixel(out, (0, 0)) == OPAQUE


def test_generation_is_byte_deterministic() -> None:
    """§36: unchanged input produces byte-identical output, every time."""
    source_bytes = _source_bytes([[OPAQUE, TRANSPARENT], [TRANSPARENT, OPAQUE]])

    first = generate(source_bytes, {})
    second = generate(source_bytes, {})

    assert first.output_bytes == second.output_bytes


def test_reports_the_pillow_and_zlib_versions_it_used() -> None:
    """Pillow decodes and crops; the encoder is our own, over the stdlib
    ``zlib`` (fix round 1) -- provenance's generator_versions must name both,
    since both actually produced the output bytes."""
    import zlib

    import PIL

    source_bytes = _source_bytes([[OPAQUE]])

    result = generate(source_bytes, {})

    assert result.library_versions == {"Pillow": PIL.__version__, "zlib": zlib.ZLIB_VERSION}


def _chunk_types(png_bytes: bytes) -> list[bytes]:
    """Every chunk type tag in a PNG, in order, by walking its length-
    prefixed chunk stream (a minimal, test-only PNG chunk walker)."""
    types: list[bytes] = []
    offset = 8  # skip the 8-byte PNG signature
    while offset < len(png_bytes):
        (length,) = struct.unpack(">I", png_bytes[offset : offset + 4])
        chunk_type = png_bytes[offset + 4 : offset + 8]
        types.append(chunk_type)
        offset += 4 + 4 + length + 4  # length + type + data + CRC
    return types


def test_writes_no_ancillary_chunks() -> None:
    """§6.1, §20's "predictable naming" cousin for bytes: only the three
    critical chunks every PNG needs, no tEXt/tIME/pHYs/iCCP carried over
    from the source or added by the encoder."""
    source_bytes = _source_bytes([[OPAQUE, OPAQUE], [OPAQUE, OPAQUE]])

    result = generate(source_bytes, {})

    assert _chunk_types(result.output_bytes) == [b"IHDR", b"IDAT", b"IEND"]
