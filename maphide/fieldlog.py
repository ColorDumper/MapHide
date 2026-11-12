"""How the main screen's field log words each history entry.

The field log is a terse, lowercase feed ("> map covered"), unlike the full
sentences the debug log and headless mode use. It never shows the OBS host
or port, so the streaming PC's address can't end up on stream in a capture
of the window.
"""

from dataclasses import dataclass

from .controller import (
    HISTORY_DEFAULTS_RESTORED,
    HISTORY_NOTICE,
    HISTORY_SETTINGS_SAVED,
    HISTORY_UPDATE_AVAILABLE,
)
from .obs import OBS_BAD_PASSWORD, OBS_LINK_LOST, OBS_OVERLAY_MAY_REMAIN, OBS_UNREACHABLE
from .overlay import (
    EVENT_CONNECT_FAILED,
    EVENT_CONNECTED,
    EVENT_CONNECTING,
    EVENT_LINK_LOST,
    EVENT_LOG_FAILED,
    EVENT_OVERLAY_HIDDEN,
    EVENT_OVERLAY_MAY_REMAIN,
    EVENT_OVERLAY_SHOWN,
    EVENT_SCENE,
    EVENT_SCENE_DROPPED,
    EVENT_SCENE_WITHOUT_SOURCE,
    EVENT_SOURCE_FOUND,
    EVENT_STOPPED,
    STOPPED_MESSAGE,
)

# The color a line is drawn in.
PLAIN = "plain"
LINKED = "linked"
COVERED = "covered"
WARNING = "warning"

# Why a connection failed, by the message the worker reports it with.
_FAILURE_REASONS = {
    OBS_BAD_PASSWORD: "wrong password",
    OBS_UNREACHABLE: "obs not answering",
    OBS_LINK_LOST: "link lost",
}


@dataclass(frozen=True)
class FieldLine:
    time: str
    text: str
    tone: str


def _reason(message):
    if message.startswith("MapHide stopped after an unexpected error"):
        return "unexpected error"
    return _FAILURE_REASONS.get(message, "check host and port")


def _wording(entry):
    """(text, tone) for one history entry."""
    code, scene = entry.code, entry.subject
    if code == EVENT_CONNECTING:
        return "> acquiring link…", PLAIN
    if code == EVENT_CONNECTED:
        return "> link up · obs", LINKED
    if code == EVENT_CONNECT_FAILED:
        return f"> no link · {_reason(entry.message)}", WARNING
    if code == EVENT_LINK_LOST:
        return "> link lost", WARNING
    if code == EVENT_OVERLAY_MAY_REMAIN:
        return "> cover may still be up · check obs", COVERED
    if code == EVENT_SCENE and scene:
        return f"> scene · {scene}", PLAIN
    if code == EVENT_SCENE_WITHOUT_SOURCE and scene:
        return f"> scene · {scene} · no cover source", WARNING
    if code == EVENT_SOURCE_FOUND and scene:
        return f"> cover source found · {scene}", LINKED
    if code == EVENT_SCENE_DROPPED and scene:
        return f"> scene gone · {scene}", WARNING
    if code == EVENT_OVERLAY_SHOWN:
        return "> map covered", COVERED
    if code == EVENT_OVERLAY_HIDDEN:
        return "> cover dropped", PLAIN
    if code == EVENT_STOPPED:
        if entry.message == STOPPED_MESSAGE:
            return "> stopped", PLAIN
        if entry.message == OBS_OVERLAY_MAY_REMAIN:
            return "> stopped · cover may still be up", COVERED
        return f"> stopped · {_reason(entry.message)}", WARNING
    if code == EVENT_LOG_FAILED:
        return "> debug log couldn't start", WARNING
    if code == HISTORY_SETTINGS_SAVED:
        return "> settings saved", PLAIN
    if code == HISTORY_DEFAULTS_RESTORED:
        return "> defaults restored", PLAIN
    if code == HISTORY_UPDATE_AVAILABLE and entry.subject:
        return f"> update available · v{entry.subject} · see settings", LINKED
    if code == HISTORY_NOTICE:
        return f"> {entry.message}", WARNING
    return f"> {entry.message}", PLAIN


def field_line(entry):
    """The field log line for a controller HistoryEntry."""
    text, tone = _wording(entry)
    # To the second: the milliseconds the history keeps are noise here.
    return FieldLine(entry.timestamp.split(".")[0], text, tone)
