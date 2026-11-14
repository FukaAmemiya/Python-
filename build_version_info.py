"""Create Windows version metadata for the standalone executable.

SignPath Foundation requires product identity and version metadata to be
present in signed PE binaries. This file is only used at build time.
"""

import argparse
import re
from pathlib import Path

PRODUCT = "双站小说下载器 (FukaAmemiya)"
EXE_NAME = "NovelDownloader-Windows-x64.exe"


def metadata(tag):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag)
    if not match:
        raise ValueError("Expected a version like v1.1.1")
    version = tuple(int(number) for number in match.groups()) + (0,)
    value = ".".join(str(number) for number in version)
    strings = {
        "CompanyName": "FukaAmemiya",
        "FileDescription": "双站小说下载器 · Windows 桌面版",
        "FileVersion": value,
        "InternalName": "NovelDownloader",
        "LegalCopyright": "Copyright (C) FukaAmemiya",
        "OriginalFilename": EXE_NAME,
        "ProductName": PRODUCT,
        "ProductVersion": value,
    }
    fields = ",\n              ".join(
        f"StringStruct({key!r}, {text!r})" for key, text in strings.items()
    )
    body = (
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers={version}, prodvers={version},\n"
        "    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,\n"
        "    subtype=0x0, date=(0, 0)),\n"
        "  kids=[StringFileInfo([StringTable('040904B0', [\n"
        f"              {fields}\n"
        "  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]\n"
        ")\n"
    )
    return body, value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v0.0.0")
    parser.add_argument("--output", default="win-version-info.txt")
    args = parser.parse_args()
    body, value = metadata(args.tag)
    Path(args.output).write_text(body, encoding="utf-8")
    print(f"Version resource: {value}")


if __name__ == "__main__":
    main()
