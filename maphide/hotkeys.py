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
MODIFIER_LABELS = ("SHIFT",)
MODIFIER_KEYSYMS = {
    "SHIFT_L": "SHIFT",
    "SHIFT_R": "SHIFT",
}
SPECIAL_KEYSYMS = {
    "ESCAPE": "ESC",
}
EVENT_STATE_MODIFIERS = (
    ("SHIFT", 0x0001),
)

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


def is_key_down(vk_code):
    state = ctypes.windll.user32.GetAsyncKeyState(vk_code)
    return (state & 0x8000) != 0


def is_hotkey_down(vk_codes):
    return bool(vk_codes) and all(is_key_down(code) for code in vk_codes)
