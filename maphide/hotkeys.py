"""Reading the keyboard, and the vocabulary of key names MapHide accepts."""

import ctypes

HOTKEY_OPTIONS = [
    *[(chr(code), code) for code in range(ord("A"), ord("Z") + 1)],
    ("ESC", 0x1B),
    ("SHIFT", 0x10),
]
HOTKEY_TO_VK = dict(HOTKEY_OPTIONS)
SHOW_KEY_LABELS = tuple(chr(code) for code in range(ord("A"), ord("Z") + 1))
STANDALONE_HIDE_KEY_LABELS = ("ESC", "SHIFT")
# Windows reports the key's current state in the high bit. The low bit is a
# was-pressed-since-last-call flag: it still reads true even if the key is
# back up by the time we check, which is what lets poll_hotkey below notice
# a press that happened while the worker was blocked on an OBS call. It is
# not reliable while the key is still down, though - Windows' keyboard
# auto-repeat re-asserts it roughly every 30ms for as long as a key is held,
# even though the key never actually releases in between (confirmed against
# real hardware). Only trust it while the key currently reads up; see
# state.py's decide().
KEY_DOWN_MASK = 0x8000
KEY_PRESSED_SINCE_MASK = 0x0001
MODIFIER_KEYSYMS = {
    "SHIFT_L": "SHIFT",
    "SHIFT_R": "SHIFT",
}
SPECIAL_KEYSYMS = {
    "ESCAPE": "ESC",
}
# Tk reports which modifiers were held as bits on a key event's state field.
MODIFIER_STATE_MASKS = {"SHIFT": 0x0001}

SHOW_KEY_HELP = "Show key supports A-Z."
HIDE_KEY_HELP = "Hide key supports A-Z, Esc, Shift, or Shift+A-Z."


def hotkey_to_vk_codes(hotkey, fallback=None):
    labels = [part.strip().upper() for part in str(hotkey).split("+") if part.strip()]
    codes = []
    for label in labels:
        code = HOTKEY_TO_VK.get(label)
        if code is None:
            return fallback or []
        if code not in codes:
            codes.append(code)
    return codes or (fallback or [])


def hotkey_labels(hotkey):
    return [part.strip().upper() for part in str(hotkey).split("+") if part.strip()]


def is_valid_hide_hotkey(hotkey):
    labels = hotkey_labels(hotkey)
    if len(labels) == 1:
        return labels[0] in SHOW_KEY_LABELS or labels[0] in STANDALONE_HIDE_KEY_LABELS
    if len(labels) == 2:
        return labels[0] == "SHIFT" and labels[1] in SHOW_KEY_LABELS
    return False


def is_valid_show_hotkey(hotkey):
    labels = hotkey_labels(hotkey)
    return len(labels) == 1 and labels[0] in SHOW_KEY_LABELS


def normalize_event_key(keysym):
    key = str(keysym).strip().upper()
    if key in MODIFIER_KEYSYMS:
        return MODIFIER_KEYSYMS[key]
    if key in SPECIAL_KEYSYMS:
        return SPECIAL_KEYSYMS[key]
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return key if key in SHOW_KEY_LABELS else None
    return None


def read_key_state(vk_code):
    # One call, since GetAsyncKeyState clears its own was-pressed-since-last-call
    # bit each time it is asked - reading the two bits separately would clear the
    # first one before the second call could see it.
    state = ctypes.windll.user32.GetAsyncKeyState(vk_code)
    is_down = (state & KEY_DOWN_MASK) != 0
    pressed_since_last_check = (state & KEY_PRESSED_SINCE_MASK) != 0
    return is_down, pressed_since_last_check


def poll_hotkey(vk_codes):
    """Current down state, plus whether a press happened since the last poll.

    The second value is exact for a single-key hotkey: it is still true even
    if that key is back up by the time we check, which is what a hotkey
    tapped and released while the worker was blocked on an OBS call needs. For
    a multi-key combo it is an approximation - true once every key has been
    down since the last poll and all are currently down - since Windows only
    tracks the since-last-call flag per key, not per combo.
    """
    if not vk_codes:
        return False, False
    if len(vk_codes) == 1:
        # Report the raw bits as-is: for one key, "pressed since last check" is
        # exact even after the key has already gone back up.
        return read_key_state(vk_codes[0])
    is_down = True
    any_pressed_since = False
    for code in vk_codes:
        key_down, key_pressed_since = read_key_state(code)
        is_down = is_down and key_down
        any_pressed_since = any_pressed_since or key_pressed_since
    return is_down, is_down and any_pressed_since
