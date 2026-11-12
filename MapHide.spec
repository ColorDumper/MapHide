# -*- mode: python ; coding: utf-8 -*-

# One-dir build. A one-file build (single self-extracting .exe) is a common
# antivirus false-positive trigger, so MapHide ships as a folder instead:
# dist/MapHide/MapHide.exe plus dist/MapHide/_internal/.

import os
import re

a = Analysis(
    ['map_hider.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('MapHide.ico', '.'),
        ('assets', 'assets'),
        ('maphide/qt/*.qml', 'maphide/qt'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Used only by tools/make_assets.py and the tests, never by the app.
    excludes=['tkinter', 'PIL', 'PySide6.QtOpenGL'],
    noarchive=False,
    # -OO on the bundled bytecode: drops asserts and docstrings for a small size
    # win. MapHide uses no asserts and reads none of its own docstrings at runtime.
    optimize=2,
)

# PySide6's packaging hooks bring in all of Qt Quick: about 160 MB. These are
# the parts this window never loads - other control styles, dialogs, 3D,
# PDF, a software OpenGL fallback, Qt's own OpenSSL, and translations for an
# English-only window. Leaving out something it does load only shows when the
# window opens, which is what `MapHide.exe --selftest` checks in the build.
UNUSED = re.compile(
    r"opengl32sw|QuickControls2|QuickDialogs2|QuickTemplates2"
    r"|QuickNativeStyle|Qt6Labs|Qt6Test|Qt6QuickTest|Qt6Sql|QuickVectorImage|ShapesDesignHelpers"
    r"|QmlXmlListModel|QmlLocalStorage|QuickTimeline|QuickLayouts|QmlDesignSupport|QmlNetwork"
    r"|Qt6QmlCore|Qt6Pdf|VirtualKeyboard|Quick3D|QuickParticles|QuickWidgets|Qt6Svg"
    r"|libcrypto-3-x64|libssl-3-x64|PySide6/translations/"
    r"|qml/(Qt/|QtTest|QtNetwork|QtCore|QtQuick/(Controls|Dialogs|Layouts|LocalStorage"
    r"|NativeStyle|Particles|Pdf|Scene2D|Scene3D|Templates|Timeline|VectorImage|VirtualKeyboard|tooling))"
    r"|plugins/(qmltooling|tls|networkinformation|generic|iconengines)"
    # WebP for the map box and ICO for the window icon; PNG is built in.
    r"|imageformats/(?!qwebp|qico)|platforms/(?!qwindows)",
    re.IGNORECASE,
)


def used(entry):
    return not UNUSED.search(entry[0].replace(os.sep, '/'))


a.binaries = [entry for entry in a.binaries if used(entry)]
a.datas = [entry for entry in a.datas if used(entry)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MapHide',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['MapHide.ico'],
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MapHide',
)
