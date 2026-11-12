import io
import struct
from pathlib import Path

import pytest
from PIL import Image, ImageFont

from tools.make_assets import (
    ICO_SIZES,
    PNG_IMAGE_CHUNKS,
    WEBP_IMAGE_CHUNKS,
    clean_webp,
    png_chunks,
    webp_chunks,
)

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICO = ROOT / "MapHide.ico"


def ico_frames(data):
    """The bytes of each frame stored in an .ico file."""
    _reserved, _kind, count = struct.unpack("<HHH", data[:6])
    frames = []
    for i in range(count):
        entry = 6 + 16 * i
        size, offset = struct.unpack("<II", data[entry + 8 : entry + 16])
        frames.append(data[offset : offset + size])
    return frames


def metadata_chunks(data):
    if data.startswith(b"RIFF"):
        return [kind for kind, _ in webp_chunks(data) if kind not in WEBP_IMAGE_CHUNKS]
    return [kind for kind, _ in png_chunks(data) if kind not in PNG_IMAGE_CHUNKS]


@pytest.mark.parametrize(
    "path",
    sorted(ASSETS.glob("*.png")) + sorted(ASSETS.glob("*.webp")),
    ids=lambda path: path.name,
)
def test_bundled_images_carry_no_metadata(path):
    assert metadata_chunks(path.read_bytes()) == []


def test_icon_holds_every_size_as_a_clean_png_frame():
    sizes = []
    for frame in ico_frames(ICO.read_bytes()):
        assert metadata_chunks(frame) == []
        sizes.append(struct.unpack(">II", frame[16:24]))
    assert sorted(sizes) == [(size, size) for size in ICO_SIZES]


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("MapHide_Icon.png", (256, 256)),
        ("MapHide_Icon_64.png", (64, 64)),
        ("MapHide_Icon_32.png", (32, 32)),
    ],
)
def test_icon_pngs_are_square_at_their_size(name, size):
    assert Image.open(ASSETS / name).size == size


@pytest.mark.parametrize(
    ("file", "family", "style"),
    [
        ("Barlow-Regular.ttf", "Barlow", "Regular"),
        ("Barlow-Medium.ttf", "Barlow", "Medium"),
        ("BarlowCondensed-SemiBold.ttf", "Barlow Condensed", "SemiBold"),
        ("BarlowCondensed-Bold.ttf", "Barlow Condensed", "Bold"),
        ("IBMPlexMono-Regular.ttf", "IBM Plex Mono", "Regular"),
        ("IBMPlexMono-Medium.ttf", "IBM Plex Mono", "Medium"),
    ],
)
def test_fonts_load(file, family, style):
    assert ImageFont.truetype(str(ASSETS / "fonts" / file), 12).getname() == (family, style)


def test_every_bundled_font_has_its_license_beside_it():
    fonts = ASSETS / "fonts"
    # Barlow's license covers Barlow Condensed too: one project, one license.
    licensed = {path.name.removesuffix("-OFL.txt") for path in fonts.glob("*-OFL.txt")}
    for font in fonts.glob("*.ttf"):
        family = font.name.split("-")[0].removesuffix("Condensed")
        assert family in licensed, font.name


def riff(*chunks):
    body = b"WEBP" + b"".join(
        kind + struct.pack("<I", len(data)) + data + b"\0" * (len(data) & 1)
        for kind, data in chunks
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_clean_webp_keeps_only_the_picture_byte_for_byte():
    picture = b"\x01\x02\x03"
    source = riff(
        (b"VP8X", b"\0" * 10),
        (b"ICCP", b"profile"),
        (b"VP8 ", picture),
        (b"EXIF", b"camera"),
        (b"XMP ", b"<c2pa/>"),
    )

    assert clean_webp(source) == riff((b"VP8 ", picture))


def test_clean_webp_refuses_a_picture_that_needs_the_extended_format():
    with pytest.raises(ValueError):
        clean_webp(riff((b"VP8X", b"\0" * 10), (b"ALPH", b"a"), (b"VP8 ", b"p")))


def test_cleaned_map_box_still_decodes():
    cleaned = clean_webp((ASSETS / "MapBox.webp").read_bytes())
    assert Image.open(io.BytesIO(cleaned)).convert("RGB").size == (960, 540)
