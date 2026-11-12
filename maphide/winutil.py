"""Small Windows-only touches for the app's window and taskbar entry."""

import ctypes

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
# The same attribute's id on older Windows 10 builds.
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
DWMWA_CAPTION_COLOR = 35


def set_app_id(app_id):
    """Group the app's windows under its own taskbar entry and icon."""
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


def top_level_window(child_hwnd):
    """The window handle Windows draws the title bar for, given the handle of
    the window's client area."""
    return ctypes.windll.user32.GetParent(child_hwnd)


def apply_dark_title_bar(hwnd, caption_color):
    """Draw the title bar dark, in `caption_color` ("#rrggbb") where Windows
    supports a custom caption color. Silently does nothing where it doesn't:
    the title bar's look is cosmetic."""
    try:
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        for attribute in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD):
            rc = dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(on), ctypes.sizeof(on))
            if rc == 0:
                break
        r, g, b = (int(caption_color[i : i + 2], 16) for i in (1, 3, 5))
        caption = ctypes.c_uint(r | (g << 8) | (b << 16))
        dwm.DwmSetWindowAttribute(
            hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(caption), ctypes.sizeof(caption)
        )
    except (OSError, AttributeError):
        pass
