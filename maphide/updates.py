"""Checking GitHub for a newer MapHide, and installing it.

Only the GitHub download updates itself this way. A Store copy is updated by
the Store. A copy unzipped by hand has no installer to update it with, so it
points to the download page instead.

Nothing here touches a widget. Network work runs on its own thread, and
results come back through the `schedule` callable, as in the controller.
"""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .version import CHANNEL, CHANNEL_GITHUB, CHANNEL_SOURCE, VERSION

REPO = "ColorDumper/MapHide"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
# Setup files are only ever downloaded from this repository's own releases.
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
SETUP_NAME = re.compile(r"MapHide-v(\d+\.\d+\.\d+)-setup\.exe")
TIMEOUT_SECONDS = 20
CHUNK_BYTES = 64 * 1024
POLL_INTERVAL_MS = 100
# Runs the installer showing only its progress, then reopens MapHide.
INSTALLER_ARGUMENTS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1")
UNINSTALLER_NAME = "unins000.exe"

NO_CONNECTION = "Couldn't reach GitHub. Check your internet connection."
GITHUB_UNAVAILABLE = "GitHub couldn't be checked right now. Try again later."
UNEXPECTED_REPLY = "GitHub sent a reply MapHide couldn't read. Try again later."
DOWNLOAD_FAILED = "The download didn't finish. Try again."
DOWNLOAD_DAMAGED = "The download was damaged. Try again."
INSTALLER_DIDNT_START = "The installer couldn't start."
CHECK_FAILED = "Couldn't check for updates."

# Updater states.
IDLE = "idle"
CHECKING = "checking"
LATEST = "latest"
AVAILABLE = "available"
DOWNLOADING = "downloading"
INSTALLING = "installing"
FAILED = "failed"


class UpdateError(Exception):
    """Something went wrong, with a message fit to show the user."""


@dataclass(frozen=True)
class Release:
    version: str
    # The setup file, when this release has one MapHide can install.
    setup_url: str | None = None
    setup_size: int = 0
    setup_sha256: str | None = None


def parse_version(text):
    """ "v1.2.3" or "1.2.3" as (1, 2, 3); None for anything else."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(text).strip())
    return tuple(int(part) for part in match.groups()) if match else None


def is_newer(candidate, current=VERSION):
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


def release_from_json(data):
    """A Release from GitHub's description of the latest release. Raises
    UpdateError if it isn't one MapHide understands."""
    if not isinstance(data, dict):
        raise UpdateError(UNEXPECTED_REPLY)
    version = parse_version(data.get("tag_name", ""))
    if version is None:
        raise UpdateError(UNEXPECTED_REPLY)
    version = ".".join(map(str, version))
    for asset in data.get("assets") or ():
        if not isinstance(asset, dict):
            continue
        match = SETUP_NAME.fullmatch(str(asset.get("name", "")))
        url = str(asset.get("browser_download_url", ""))
        digest = str(asset.get("digest") or "")
        if not match or match.group(1) != version or not url.startswith(DOWNLOAD_PREFIX):
            continue
        # Without a checksum to compare against, MapHide won't run the file.
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            continue
        return Release(version, url, int(asset.get("size") or 0), digest.split(":", 1)[1])
    return Release(version)


def _request(url):
    # Only ever https: the release API above, or a download checked against
    # DOWNLOAD_PREFIX.
    if not url.startswith("https://"):
        raise UpdateError(DOWNLOAD_FAILED)
    return urllib.request.Request(  # noqa: S310 - https only, checked above
        url,
        headers={"User-Agent": f"MapHide/{VERSION}", "Accept": "application/vnd.github+json"},
    )


def fetch_latest(opener=urllib.request.urlopen):
    """The latest release on GitHub. Raises UpdateError."""
    try:
        with opener(_request(LATEST_RELEASE_API), timeout=TIMEOUT_SECONDS) as reply:
            data = json.load(reply)
    except urllib.error.HTTPError as exc:
        # GitHub answered, but not with a release: none published yet, or
        # too many checks from this network in the last hour.
        raise UpdateError(GITHUB_UNAVAILABLE) from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise UpdateError(NO_CONNECTION) from exc
    except (ValueError, OSError) as exc:
        raise UpdateError(UNEXPECTED_REPLY) from exc
    return release_from_json(data)


def download_setup(release, folder, progress=None, opener=urllib.request.urlopen):
    """Download `release`'s setup file into `folder` and check it against
    GitHub's checksum. `progress(fraction)` is called as it arrives.
    Returns the file's path. Raises UpdateError."""
    if release.setup_url is None or not release.setup_url.startswith(DOWNLOAD_PREFIX):
        raise UpdateError(DOWNLOAD_FAILED)
    folder = Path(folder)
    target = folder / f"MapHide-v{release.version}-setup.exe"
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    received = 0
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with opener(_request(release.setup_url), timeout=TIMEOUT_SECONDS) as reply:
            with open(partial, "wb") as file:
                while chunk := reply.read(CHUNK_BYTES):
                    file.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if progress is not None and release.setup_size:
                        progress(min(received / release.setup_size, 1.0))
        if digest.hexdigest() != release.setup_sha256:
            partial.unlink(missing_ok=True)
            raise UpdateError(DOWNLOAD_DAMAGED)
        partial.replace(target)
    except UpdateError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(DOWNLOAD_FAILED) from exc
    return target


def launch_installer(path, popen=subprocess.Popen):
    """Start the setup file, which closes MapHide, installs over it and
    reopens it. Raises UpdateError if it can't start."""
    try:
        popen([str(path), *INSTALLER_ARGUMENTS], close_fds=True)
    except OSError as exc:
        raise UpdateError(INSTALLER_DIDNT_START) from exc


def checks_for_updates(channel=CHANNEL):
    """Whether this copy looks for updates on GitHub at all: the GitHub
    download does, and so does a copy run from source."""
    return channel in (CHANNEL_GITHUB, CHANNEL_SOURCE)


def installed_by_setup(channel=CHANNEL, frozen=None, exe_dir=None):
    """Whether this copy was installed by MapHide's setup file, and so can
    install an update itself."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    exe_dir = Path(sys.executable).parent if exe_dir is None else Path(exe_dir)
    return channel == CHANNEL_GITHUB and bool(frozen) and (exe_dir / UNINSTALLER_NAME).exists()


def download_folder():
    return Path(tempfile.gettempdir()) / "MapHide-update"


class Updater:
    """Checks for a new version and installs it, one step at a time.

    `schedule(milliseconds, callback)` runs `callback` later on the window's
    thread. `on_change()` asks the window to redraw.
    """

    def __init__(
        self,
        schedule,
        on_change=lambda: None,
        current=VERSION,
        fetch=fetch_latest,
        download=download_setup,
        launch=launch_installer,
        can_install=None,
        folder=None,
    ):
        self._schedule = schedule
        self._on_change = on_change
        self._current = current
        self._fetch = fetch
        self._download = download
        self._launch = launch
        self.can_install = installed_by_setup() if can_install is None else can_install
        self._folder = download_folder() if folder is None else folder
        self.state = IDLE
        self.message = ""
        self.release = None
        self.progress = 0.0
        self.thread = None

    @property
    def busy(self):
        return self.state in (CHECKING, DOWNLOADING, INSTALLING)

    @property
    def can_install_release(self):
        """Whether the release found can be installed from here: this copy
        was installed by the setup file, and the release has one MapHide
        can use. If not, the window sends you to the download page."""
        return self.can_install and self.release is not None and self.release.setup_url is not None

    def _set(self, state, message=""):
        self.state = state
        self.message = message
        self._on_change()

    def _run(self, work, on_done):
        """Run `work()` off the window's thread, then `on_done(result,
        error)` back on it."""
        outcome = []

        def run():
            try:
                outcome.append((work(), None))
            except UpdateError as exc:
                outcome.append((None, str(exc)))
            except Exception:
                # A bug here must still end the wait in the window.
                outcome.append((None, CHECK_FAILED))

        def wait():
            if not outcome:
                self._on_change()
                self._schedule(POLL_INTERVAL_MS, wait)
                return
            self.thread = None
            on_done(*outcome[0])

        self.thread = threading.Thread(target=run, name="Updater", daemon=True)
        self.thread.start()
        self._schedule(POLL_INTERVAL_MS, wait)

    def check(self, on_found=None, quiet=False):
        """Ask GitHub for the latest version. `on_found(release)` runs if it
        is newer than this one. A quiet check, as at startup, goes back to
        idle instead of showing that it failed. Returns False while busy."""
        if self.busy:
            return False

        def done(release, error):
            if error is not None:
                self._set(IDLE if quiet else FAILED, "" if quiet else error)
            elif is_newer(release.version, self._current):
                self.release = release
                self._set(AVAILABLE)
                if on_found is not None:
                    on_found(release)
            else:
                # Only a check someone asked for says MapHide is up to date.
                self._set(IDLE if quiet else LATEST)

        self._set(CHECKING)
        self._run(self._fetch, done)
        return True

    def clear_latest(self):
        """Stop saying MapHide is up to date, a few seconds after a check."""
        if self.state == LATEST:
            self._set(IDLE)

    def install(self, on_started):
        """Download the new version and start its installer, then call
        `on_started()`, which should close MapHide. Returns False if there
        is nothing to install or this copy can't install it."""
        release = self.release
        if self.busy or self.state not in (AVAILABLE, FAILED) or not self.can_install_release:
            return False

        def report(fraction):
            self.progress = fraction

        def work():
            path = self._download(release, self._folder, report)
            self._launch(path)

        def done(_result, error):
            if error is not None:
                self._set(FAILED, error)
                return
            self._set(INSTALLING)
            on_started()

        self.progress = 0.0
        self._set(DOWNLOADING)
        self._run(work, done)
        return True
