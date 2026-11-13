"""Settings in the installer script that keep an install or update from
leaving MapHide unable to start."""

import re
from pathlib import Path

INSTALLER = (Path(__file__).resolve().parent.parent / "installer" / "MapHide.iss").read_text(
    encoding="utf-8"
)


def setup_directive(name):
    match = re.search(rf"^{name}=(.*)$", INSTALLER, re.MULTILINE)
    return match.group(1).strip() if match else None


def test_an_install_cant_be_cancelled_halfway():
    # The old program files are deleted before the new ones are copied, so
    # stopping in between would leave a MapHide that can't start.
    assert setup_directive("AllowCancelDuringInstall") == "no"
    assert 'Type: filesandordirs; Name: "{app}\\_internal"' in INSTALLER
