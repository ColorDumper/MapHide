"""MapHide's version, and which kind of build this copy is.

VERSION is the only place the version number is written. The exe's file
properties are generated from it at build time, and a release tag must
match it.
"""

import re

from .paths import APP_DIR

VERSION = "0.3.0"
APP_VERSION = f"v{VERSION}"

# Where a packaged copy came from. The build writes one of these into
# channel.txt next to the bundled files; a copy run from source has none.
CHANNEL_GITHUB = "github"
CHANNEL_STORE = "store"
CHANNEL_STEAM = "steam"
CHANNELS = (CHANNEL_GITHUB, CHANNEL_STORE, CHANNEL_STEAM)
CHANNEL_SOURCE = "source"
CHANNEL_FILE = "channel.txt"


def version_parts(version=VERSION):
    """`version` ("1.2.3") as the four numbers Windows file properties use:
    (1, 2, 3, 0). Raises ValueError for anything not in that form."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Not a version number: {version!r}")
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch, 0


def read_channel(path):
    """The channel named in the file at `path`, or CHANNEL_SOURCE when there
    is no such file or it names no known channel."""
    try:
        name = path.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return CHANNEL_SOURCE
    return name if name in CHANNELS else CHANNEL_SOURCE


CHANNEL = read_channel(APP_DIR / CHANNEL_FILE)
