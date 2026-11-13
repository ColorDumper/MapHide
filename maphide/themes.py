"""The window's color themes.

Every theme names the same set of colors, so the window's layout never
depends on which one is in use. Adding a theme means adding an entry to
THEMES - nothing else needs to know about it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    """Colors as "#rrggbb". Where the window draws a color see-through, its
    opacity (0-1) is given alongside it."""

    label: str
    bg: str
    panel: str
    panel2: str
    border: str
    border2: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_text: str
    accent_deep: str
    on_accent: str
    ok: str
    warn: str
    scan_line: str
    scan_line_opacity: float
    title_bar: str
    # Panels and status boxes are the `panel` color at this opacity...
    glass_opacity: float
    # ...and clickable buttons at this one.
    glass_button_opacity: float
    topo_line_opacity: float


FIELD = Theme(
    label="Field",
    bg="#13140f",
    panel="#1c1d16",
    panel2="#24261d",
    border="#34372b",
    border2="#4a4d3e",
    text="#ebe5d3",
    muted="#aaa38c",
    faint="#7d7865",
    accent="#d9483b",
    accent_text="#ff7a6b",
    accent_deep="#8f2a20",
    on_accent="#13140f",
    ok="#a9cc6a",
    warn="#e2b84c",
    scan_line="#9cc05a",
    scan_line_opacity=0.8,
    title_bar="#0d0e0a",
    glass_opacity=0.42,
    glass_button_opacity=0.6,
    topo_line_opacity=0.07,
)

LEGACY = Theme(
    label="Legacy",
    bg="#12161d",
    panel="#1b2330",
    panel2="#222c3b",
    border="#2d3748",
    border2="#3a4658",
    text="#e6edf7",
    muted="#9fb0c7",
    faint="#7f90a8",
    accent="#4da3ff",
    accent_text="#78b8ff",
    accent_deep="#2a6fc0",
    on_accent="#0b1220",
    ok="#5fd39a",
    warn="#e6b450",
    scan_line="#4da3ff",
    scan_line_opacity=0.75,
    title_bar="#0e1218",
    glass_opacity=0.42,
    glass_button_opacity=0.6,
    topo_line_opacity=0.05,
)

# Keyed by the name saved in the config file, in the order a picker lists them.
THEMES = {
    "field": FIELD,
    "legacy": LEGACY,
}
DEFAULT_THEME = "field"


def theme_name(value):
    """A saved theme name as a known one: case-insensitive, and the default
    for anything unknown - such as a theme from a newer version."""
    name = str(value).strip().lower()
    return name if name in THEMES else DEFAULT_THEME
