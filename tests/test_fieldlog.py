import pytest

from maphide.controller import (
    HISTORY_DEFAULTS_RESTORED,
    HISTORY_NOTICE,
    HISTORY_SETTINGS_SAVED,
    HistoryEntry,
)
from maphide.fieldlog import COVERED, LINKED, PLAIN, WARNING, FieldLine, field_line
from maphide.obs import (
    OBS_BAD_PASSWORD,
    OBS_LINK_LOST,
    OBS_OVERLAY_MAY_REMAIN,
    OBS_SETTINGS_WRONG,
    OBS_UNREACHABLE,
)
from maphide.overlay import (
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


def line(code, message="", subject=None):
    return field_line(HistoryEntry("19:41:52.123", message, code, subject))


@pytest.mark.parametrize(
    ("code", "message", "subject", "text", "tone"),
    [
        (EVENT_CONNECTING, "Connecting to OBS...", None, "> acquiring link…", PLAIN),
        (EVENT_CONNECTED, "Connected to OBS.", None, "> link up · obs", LINKED),
        (EVENT_LINK_LOST, OBS_LINK_LOST, None, "> link lost", WARNING),
        (EVENT_SCENE, "Switched to scene: Gameplay.", "Gameplay", "> scene · Gameplay", PLAIN),
        (
            EVENT_SCENE_WITHOUT_SOURCE,
            "Switched to scene: Chatting. Source 'Overlay' not found.",
            "Chatting",
            "> scene · Chatting · no cover source",
            WARNING,
        ),
        (
            EVENT_SOURCE_FOUND,
            "Source 'Overlay' found in scene: Gameplay.",
            "Gameplay",
            "> cover source found · Gameplay",
            LINKED,
        ),
        (
            EVENT_SCENE_DROPPED,
            "Scene 'Old' is no longer available in OBS.",
            "Old",
            "> scene gone · Old",
            WARNING,
        ),
        (EVENT_OVERLAY_SHOWN, "Overlay shown.", None, "> map covered", COVERED),
        (EVENT_OVERLAY_HIDDEN, "Overlay hidden.", None, "> cover dropped", PLAIN),
        (
            EVENT_OVERLAY_MAY_REMAIN,
            "The overlay may still be showing in OBS.",
            None,
            "> cover may still be up · check obs",
            COVERED,
        ),
        (EVENT_STOPPED, STOPPED_MESSAGE, None, "> stopped", PLAIN),
        (
            EVENT_STOPPED,
            OBS_OVERLAY_MAY_REMAIN,
            None,
            "> stopped · cover may still be up",
            COVERED,
        ),
        (
            EVENT_LOG_FAILED,
            "Could not start the debug log: Access is denied.",
            None,
            "> debug log couldn't start",
            WARNING,
        ),
        (HISTORY_SETTINGS_SAVED, "Config saved.", None, "> settings saved", PLAIN),
        (HISTORY_DEFAULTS_RESTORED, "Defaults restored.", None, "> defaults restored", PLAIN),
        (HISTORY_NOTICE, "OBS Host is required.", None, "> OBS Host is required.", WARNING),
    ],
)
def test_each_entry_gets_its_field_log_wording(code, message, subject, text, tone):
    assert line(code, message, subject) == FieldLine("19:41:52", text, tone)


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        (OBS_BAD_PASSWORD, "wrong password"),
        (OBS_UNREACHABLE, "obs not answering"),
        (OBS_SETTINGS_WRONG, "check host and port"),
    ],
)
def test_a_failed_connection_says_why(message, reason):
    assert line(EVENT_CONNECT_FAILED, message).text == f"> no link · {reason}"
    assert line(EVENT_STOPPED, message).text == f"> stopped · {reason}"


def test_a_stop_after_an_unexpected_error_says_so():
    message = "MapHide stopped after an unexpected error (KeyError)."

    assert line(EVENT_STOPPED, message) == FieldLine(
        "19:41:52", "> stopped · unexpected error", WARNING
    )


def test_no_connection_line_ever_names_the_obs_address():
    # The window may be captured on stream, so the streaming PC's address
    # must not appear in it even if a message happens to mention it.
    message = "Failed to connect to 192.168.1.42:4455"
    for code in (EVENT_CONNECTED, EVENT_CONNECT_FAILED, EVENT_LINK_LOST, EVENT_STOPPED):
        assert "192.168" not in line(code, message).text


def test_an_entry_without_a_code_shows_its_message():
    assert line(None, "Something happened.") == FieldLine(
        "19:41:52", "> Something happened.", PLAIN
    )
