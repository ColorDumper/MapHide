"""The file properties Windows shows for MapHide.exe (Details tab), built
from maphide/version.py by MapHide.spec, so the version is written once."""

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

from maphide.version import version_parts

COMPANY = "Color Dumper"
DESCRIPTION = "MapHide - OBS map hider for dual-PC streaming"
COPYRIGHT = "Copyright (c) 2026 Color Dumper"
# US English, Unicode: the language block Windows reads the strings from.
LANGUAGE = "040904B0"


def version_resource(version):
    """The version resource for MapHide.exe at `version` ("1.2.3")."""
    parts = version_parts(version)
    dotted = ".".join(str(part) for part in parts)
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=parts,
            prodvers=parts,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,  # Windows NT, 32-bit Windows API
            fileType=0x1,  # an application
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        LANGUAGE,
                        [
                            StringStruct("CompanyName", COMPANY),
                            StringStruct("FileDescription", DESCRIPTION),
                            StringStruct("FileVersion", dotted),
                            StringStruct("InternalName", "MapHide"),
                            StringStruct("LegalCopyright", COPYRIGHT),
                            StringStruct("OriginalFilename", "MapHide.exe"),
                            StringStruct("ProductName", "MapHide"),
                            StringStruct("ProductVersion", dotted),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [0x0409, 0x04B0])]),
        ],
    )
