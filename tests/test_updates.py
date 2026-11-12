"""Checking for and installing a newer MapHide, without the internet."""

import hashlib
import io
import json
import urllib.error

import pytest
from test_controller import ManualScheduler

from maphide import updates
from maphide.updates import (
    AVAILABLE,
    CHECKING,
    DOWNLOADING,
    FAILED,
    IDLE,
    INSTALLING,
    LATEST,
    Release,
    UpdateError,
    Updater,
    download_setup,
    fetch_latest,
    installed_by_setup,
    is_newer,
    launch_installer,
    release_from_json,
)

SETUP_BYTES = b"pretend installer" * 1000
SETUP_SHA = hashlib.sha256(SETUP_BYTES).hexdigest()
SETUP_URL = (
    "https://github.com/ColorDumper/MapHide/releases/download/v0.3.0/MapHide-v0.3.0-setup.exe"
)


def release_json(tag="v0.3.0", **asset):
    version = tag.lstrip("v")
    return {
        "tag_name": tag,
        "assets": [
            {"name": f"MapHide-{tag}-win64.zip", "browser_download_url": "https://x/zip"},
            {
                "name": f"MapHide-v{version}-setup.exe",
                "browser_download_url": SETUP_URL.replace("0.3.0", version),
                "size": len(SETUP_BYTES),
                "digest": f"sha256:{SETUP_SHA}",
                **asset,
            },
        ],
    }


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def opener_returning(body):
    requests = []

    def opener(request, timeout):
        requests.append(request)
        return Reply(body)

    opener.requests = requests
    return opener


def opener_raising(exc):
    def opener(request, timeout):
        raise exc

    return opener


# Versions.


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("0.3.0", "0.2.6", True),
        ("v0.10.0", "0.9.0", True),
        ("0.2.6", "0.2.6", False),
        ("0.2.5", "0.2.6", False),
        ("1.0.0", "0.99.99", True),
        ("nonsense", "0.2.6", False),
    ],
)
def test_version_numbers_compare_as_counters(candidate, current, newer):
    assert is_newer(candidate, current) is newer


# Reading GitHub's reply.


def test_a_release_with_a_setup_file_can_be_installed():
    release = release_from_json(release_json())

    assert release == Release("0.3.0", SETUP_URL, len(SETUP_BYTES), SETUP_SHA)


@pytest.mark.parametrize(
    "asset",
    [
        {"digest": None},
        {"digest": "md5:abc"},
        {"browser_download_url": "https://example.com/MapHide-v0.3.0-setup.exe"},
        {"name": "MapHide-v0.2.0-setup.exe"},
    ],
    ids=["no checksum", "wrong checksum kind", "elsewhere", "other version"],
)
def test_a_setup_file_maphide_cant_trust_is_not_offered(asset):
    release = release_from_json(release_json(**asset))

    assert release.version == "0.3.0"
    assert release.setup_url is None


@pytest.mark.parametrize("data", [[], {"tag_name": "latest"}, {}])
def test_a_reply_that_isnt_a_release_is_an_error(data):
    with pytest.raises(UpdateError):
        release_from_json(data)


def test_fetching_asks_github_and_names_maphide():
    opener = opener_returning(json.dumps(release_json()).encode())

    release = fetch_latest(opener)

    assert release.version == "0.3.0"
    request = opener.requests[0]
    assert request.full_url == updates.LATEST_RELEASE_API
    assert request.get_header("User-agent").startswith("MapHide/")


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (urllib.error.URLError("offline"), updates.NO_CONNECTION),
        (TimeoutError(), updates.NO_CONNECTION),
        (
            urllib.error.HTTPError(updates.LATEST_RELEASE_API, 403, "", {}, None),
            updates.GITHUB_UNAVAILABLE,
        ),
    ],
)
def test_fetch_failures_are_explained(exc, message):
    with pytest.raises(UpdateError, match=message.split(".")[0]):
        fetch_latest(opener_raising(exc))


def test_a_garbled_reply_is_explained():
    with pytest.raises(UpdateError, match="couldn't read"):
        fetch_latest(opener_returning(b"<html>"))


# Downloading.


def test_a_download_is_kept_once_its_checksum_matches(tmp_path):
    progress = []
    release = release_from_json(release_json())

    path = download_setup(release, tmp_path, progress.append, opener_returning(SETUP_BYTES))

    assert path.read_bytes() == SETUP_BYTES
    assert path.name == "MapHide-v0.3.0-setup.exe"
    assert progress[-1] == 1.0


def test_a_damaged_download_is_thrown_away(tmp_path):
    release = release_from_json(release_json())

    with pytest.raises(UpdateError, match="damaged"):
        download_setup(release, tmp_path, opener=opener_returning(b"not it"))

    assert list(tmp_path.iterdir()) == []


def test_a_broken_download_is_thrown_away(tmp_path):
    release = release_from_json(release_json())

    with pytest.raises(UpdateError, match="didn't finish"):
        download_setup(release, tmp_path, opener=opener_raising(ConnectionResetError()))

    assert list(tmp_path.iterdir()) == []


def test_only_this_projects_releases_are_downloaded(tmp_path):
    release = Release("0.3.0", "https://example.com/setup.exe", 1, SETUP_SHA)

    with pytest.raises(UpdateError):
        download_setup(release, tmp_path, opener=opener_returning(SETUP_BYTES))


def test_the_installer_runs_with_progress_only_and_reopens_maphide(tmp_path):
    launched = []

    launch_installer(tmp_path / "setup.exe", lambda args, **_: launched.append(args))

    assert launched == [[str(tmp_path / "setup.exe"), *updates.INSTALLER_ARGUMENTS]]
    assert "/SILENT" in launched[0] and "/RELAUNCH=1" in launched[0]


def test_an_installer_that_wont_start_is_explained(tmp_path):
    def popen(args, **_):
        raise FileNotFoundError

    with pytest.raises(UpdateError, match="couldn't start"):
        launch_installer(tmp_path / "setup.exe", popen)


# Which copies can install an update themselves.


def test_only_an_installed_github_copy_installs_updates(tmp_path):
    (tmp_path / updates.UNINSTALLER_NAME).touch()

    assert installed_by_setup("github", True, tmp_path) is True
    assert installed_by_setup("store", True, tmp_path) is False
    assert installed_by_setup("github", False, tmp_path) is False
    assert installed_by_setup("github", True, tmp_path / "unzipped") is False


# The Updater, one step at a time.


class Steps:
    def __init__(self, release=None, error=None, can_install=True):
        self.schedule = ManualScheduler()
        self.changes = 0
        self.downloads = []
        self.launched = []
        self.download_error = None
        self.release = release or release_from_json(release_json())
        self.error = error
        self.updater = Updater(
            self.schedule,
            on_change=self._changed,
            current="0.2.6",
            fetch=self._fetch,
            download=self._download,
            launch=self.launched.append,
            can_install=can_install,
            folder="downloads",
        )

    def _changed(self):
        self.changes += 1

    def _fetch(self):
        if self.error:
            raise UpdateError(self.error)
        return self.release

    def _download(self, release, folder, progress):
        if self.download_error:
            raise UpdateError(self.download_error)
        self.downloads.append((release.version, folder))
        progress(1.0)
        return "setup.exe"

    def finish(self):
        self.updater.thread.join(timeout=5)
        while self.schedule.pending:
            self.schedule.run_next()


def test_a_newer_version_is_found_and_reported():
    s = Steps()
    found = []

    assert s.updater.check(on_found=found.append) is True
    assert s.updater.state == CHECKING
    s.finish()

    assert s.updater.state == AVAILABLE
    assert found == [s.release]


def test_the_same_version_reads_as_up_to_date():
    s = Steps(release=Release("0.2.6"))

    s.updater.check()
    s.finish()

    assert s.updater.state == LATEST
    assert s.updater.release is None


def test_a_quiet_check_says_nothing_when_maphide_is_up_to_date():
    s = Steps(release=Release("0.2.6"))

    s.updater.check(quiet=True)
    s.finish()

    assert s.updater.state == IDLE


def test_up_to_date_is_only_said_for_a_moment():
    s = Steps(release=Release("0.2.6"))
    s.updater.check()
    s.finish()

    s.updater.clear_latest()

    assert s.updater.state == IDLE


def test_clearing_leaves_a_found_update_alone():
    s = Steps()
    s.updater.check()
    s.finish()

    s.updater.clear_latest()

    assert s.updater.state == AVAILABLE


def test_a_failed_check_says_why():
    s = Steps(error=updates.NO_CONNECTION)

    s.updater.check()
    s.finish()

    assert (s.updater.state, s.updater.message) == (FAILED, updates.NO_CONNECTION)


def test_a_quiet_check_that_fails_says_nothing():
    s = Steps(error=updates.NO_CONNECTION)

    s.updater.check(quiet=True)
    s.finish()

    assert (s.updater.state, s.updater.message) == (IDLE, "")


def test_a_second_check_while_one_runs_does_nothing():
    s = Steps()
    s.updater.check()

    assert s.updater.check() is False
    s.finish()


def test_installing_downloads_runs_the_installer_then_closes_maphide():
    s = Steps()
    s.updater.check()
    s.finish()
    closed = []

    assert s.updater.install(on_started=lambda: closed.append(True)) is True
    assert s.updater.state == DOWNLOADING
    s.finish()

    assert s.downloads == [("0.3.0", "downloads")]
    assert s.launched == ["setup.exe"]
    assert s.updater.state == INSTALLING
    assert closed == [True]


def test_a_failed_download_keeps_maphide_open_and_can_be_retried():
    s = Steps()
    s.updater.check()
    s.finish()
    s.download_error = updates.DOWNLOAD_FAILED
    closed = []

    s.updater.install(on_started=lambda: closed.append(True))
    s.finish()

    assert (s.updater.state, s.updater.message) == (FAILED, updates.DOWNLOAD_FAILED)
    assert closed == []
    s.download_error = None
    assert s.updater.install(on_started=lambda: closed.append(True)) is True
    s.finish()
    assert closed == [True]


@pytest.mark.parametrize(
    "steps",
    [
        lambda: Steps(can_install=False),
        lambda: Steps(release=Release("0.3.0")),
    ],
    ids=["unzipped copy", "no setup file"],
)
def test_nothing_is_installed_when_it_cant_be(steps):
    s = steps()
    s.updater.check()
    s.finish()

    assert s.updater.install(on_started=lambda: None) is False
    assert s.downloads == []


def test_nothing_is_installed_before_a_check_finds_something():
    s = Steps()

    assert s.updater.install(on_started=lambda: None) is False
