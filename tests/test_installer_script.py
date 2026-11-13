"""Settings in the installer script: what an install, update or uninstall
does to the files MapHide leaves on your PC."""

import re
import tempfile
from pathlib import Path

from maphide.updates import download_folder

INSTALLER = (Path(__file__).resolve().parent.parent / "installer" / "MapHide.iss").read_text(
    encoding="utf-8"
)


def setup_directive(name):
    match = re.search(rf"^{name}=(.*)$", INSTALLER, re.MULTILINE)
    return match.group(1).strip() if match else None


def test_uninstalling_removes_the_update_downloads():
    # The same folder the updater downloads into.
    folder = download_folder()
    assert folder.parent == Path(tempfile.gettempdir())
    assert (
        f'[UninstallDelete]\nType: filesandordirs; Name: "{{app}}\\_internal"\n'
        f'Type: filesandordirs; Name: "{{%TEMP}}\\{folder.name}"\n'
    ) in INSTALLER


def test_an_install_cant_be_cancelled_halfway():
    # The old program files are deleted before the new ones are copied, so
    # stopping in between would leave a MapHide that can't start.
    assert setup_directive("AllowCancelDuringInstall") == "no"
    assert 'Type: filesandordirs; Name: "{app}\\_internal"' in INSTALLER
