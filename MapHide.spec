# -*- mode: python ; coding: utf-8 -*-

# One-dir build. A one-file build (single self-extracting .exe) is a common
# antivirus false-positive trigger, so MapHide ships as a folder instead:
# dist/MapHide/MapHide.exe plus dist/MapHide/_internal/.

a = Analysis(
    ['map_hider.py'],
    pathex=[],
    binaries=[],
    datas=[('MapHide.ico', '.'), ('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
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
