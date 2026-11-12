"""Make MapHide's bundled images from the full-size artwork.

    python tools/make_assets.py --logo LOGO.png --watermark WATERMARK.png --mapbox MAPBOX.webp

Writes MapHide.ico and the files in assets/ at the sizes the app shows them.
Every file it writes carries the picture and nothing else: no text, color,
resolution or provenance metadata from whatever program exported the artwork.
"""

import argparse
import io
import struct
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# The logo in Settings > About, drawn at 28px: 64 keeps it sharp on a
# high-DPI screen. The window, taskbar and tray use MapHide.ico.
ICON_PNG_SIZES = {"MapHide_Icon_64.png": 64}
WATERMARK_SIZE = 56

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# The chunks that make up the picture itself. Anything else is metadata.
PNG_IMAGE_CHUNKS = frozenset({b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"})
# A WebP's picture is one of these. VP8X, ICCP, EXIF and XMP around it are not.
WEBP_IMAGE_CHUNKS = frozenset({b"VP8 ", b"VP8L"})


def png_chunks(data):
    """The (type, length) of every chunk in a PNG file's bytes."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG file")
    chunks, pos = [], len(PNG_SIGNATURE)
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        chunks.append((data[pos + 4 : pos + 8], length))
        pos += 12 + length
    return chunks


def webp_chunks(data):
    """The (type, length) of every chunk in a WebP file's bytes."""
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("not a WebP file")
    chunks, pos = [], 12
    while pos < len(data):
        kind = data[pos : pos + 4]
        (length,) = struct.unpack("<I", data[pos + 4 : pos + 8])
        chunks.append((kind, length))
        pos += 8 + length + (length & 1)
    return chunks


def clean_webp(data):
    """The same WebP with every chunk but the picture dropped. The picture
    is kept byte for byte, so there is no re-encoding loss. Pictures that
    need the extended format (transparency, animation) are refused, since
    dropping VP8X would break them."""
    chunks, pos = [], 12
    for kind, length in webp_chunks(data):
        size = 8 + length + (length & 1)
        chunks.append((kind, data[pos : pos + size]))
        pos += size
    if {kind for kind, _ in chunks} & {b"ALPH", b"ANIM", b"ANMF"}:
        raise ValueError("WebPs with transparency or animation are not supported")
    pictures = [raw for kind, raw in chunks if kind in WEBP_IMAGE_CHUNKS]
    if len(pictures) != 1:
        raise ValueError("expected exactly one picture in the WebP")
    body = b"WEBP" + pictures[0]
    return b"RIFF" + struct.pack("<I", len(body)) + body


def png_bytes(image):
    """`image` as a PNG holding only the picture."""
    out = io.BytesIO()
    # A fresh image has an empty info dict, so nothing from the source's
    # metadata can ride along into the save.
    Image.frombytes(image.mode, image.size, image.tobytes()).save(out, "PNG", optimize=True)
    return out.getvalue()


def square(image):
    """`image` centered on a transparent square canvas."""
    side = max(image.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(image, ((side - image.width) // 2, (side - image.height) // 2))
    return canvas


def scaled(image, size):
    """`image` resized to fit within `size` x `size`, keeping its shape.
    Scaled with premultiplied alpha, so edges against transparency don't
    pick up a dark fringe."""
    ratio = size / max(image.size)
    target = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    return image.convert("RGBa").resize(target, Image.Resampling.LANCZOS).convert("RGBA")


def make_icons(logo):
    """{file name: PNG bytes} for the icon PNGs, plus the .ico's bytes."""
    master = square(logo.convert("RGBA"))
    pngs = {name: png_bytes(scaled(master, size)) for name, size in ICON_PNG_SIZES.items()}
    frames = [Image.open(io.BytesIO(png_bytes(scaled(master, size)))) for size in ICO_SIZES]
    out = io.BytesIO()
    frames[-1].save(
        out,
        "ICO",
        sizes=[frame.size for frame in frames],
        append_images=frames[:-1],
    )
    return pngs, out.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--logo", type=Path, required=True, help="full-size logo, PNG")
    parser.add_argument("--watermark", type=Path, required=True, help="full-size watermark, PNG")
    parser.add_argument("--mapbox", type=Path, required=True, help="map box picture, WebP")
    args = parser.parse_args(argv)

    pngs, ico = make_icons(Image.open(args.logo))
    pngs["MapHide_Watermark.png"] = png_bytes(
        scaled(Image.open(args.watermark).convert("RGBA"), WATERMARK_SIZE)
    )
    outputs = {ASSETS / name: data for name, data in pngs.items()}
    outputs[ROOT / "MapHide.ico"] = ico
    outputs[ASSETS / "MapBox.webp"] = clean_webp(args.mapbox.read_bytes())

    for path, data in outputs.items():
        path.write_bytes(data)
        print(f"{path.relative_to(ROOT)}  {len(data):,} bytes")


if __name__ == "__main__":
    main()
