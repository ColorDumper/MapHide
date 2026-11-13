"""Names the installer, the build workflow and MapHide must agree on. Each
is written in more than one place, and a mismatch fails only on someone's
PC: the installer can't see MapHide running, or the updater can't find the
setup file and every installed copy stays on its version."""

import re
from pathlib import Path

from maphide.paths import APP_USER_MODEL_ID
from maphide.single_instance import MUTEX_NAME
from maphide.updates import INSTALLER_ARGUMENTS, REPO, SETUP_NAME, UNINSTALLER_NAME

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = (ROOT / "installer" / "MapHide.iss").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
ENTRY_POINT = (ROOT / "map_hider.py").read_text(encoding="utf-8")


def installer_define(name):
    match = re.search(rf'^#define {name} "([^"]*)"', INSTALLER, re.MULTILINE)
    assert match, f"{name} isn't defined in MapHide.iss"
    return match.group(1)


def test_the_installer_watches_the_lock_maphide_holds():
    # The .iss writes one backslash where Python's string escapes it.
    assert installer_define("AppMutexName") == MUTEX_NAME


def test_shortcuts_carry_the_app_id_maphide_runs_under():
    assert installer_define("AppUserModelID") == APP_USER_MODEL_ID


def test_the_setup_file_ci_publishes_is_one_the_updater_finds():
    template = re.search(
        r"\$name = '(MapHide-\$\{\{ steps\.package\.outputs\.version \}\}-setup)'", WORKFLOW
    )
    assert template, "the setup file name line in build.yml changed"
    published = (
        template.group(1).replace("${{ steps.package.outputs.version }}", "v1.2.3") + ".exe"
    )

    match = SETUP_NAME.fullmatch(published)

    assert match, f"the updater won't recognise {published}"
    assert match.group(1) == "1.2.3"


def test_the_workflow_names_releases_by_their_tag():
    # A release's version is its tag, as the updater reads it.
    assert "$version = '${{ github.ref_name }}'" in WORKFLOW


def test_the_installer_reopens_maphide_when_the_updater_asks():
    assert "/RELAUNCH=1" in INSTALLER_ARGUMENTS
    assert "{param:RELAUNCH|0}" in INSTALLER


def test_the_installer_closes_maphide_the_way_maphide_understands():
    assert "Exec(ExePath, '--quit'" in INSTALLER
    assert '"--quit" in sys.argv' in ENTRY_POINT


def test_the_uninstaller_keeps_the_name_that_marks_an_installed_copy():
    # Inno Setup names it unins000.exe in the app folder unless told otherwise.
    assert UNINSTALLER_NAME == "unins000.exe"
    assert not re.search(r"^\s*UninstallFilesDir\s*=", INSTALLER, re.MULTILINE)


def test_the_installer_points_at_the_repository_the_updater_reads():
    assert f"AppUpdatesURL=https://github.com/{REPO}/releases" in INSTALLER
