# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Сорокин Иван (sorokin dev)
# Modified 2026-11-20 by Obsidian Stream Hub (Obsidian Mirror name; "1.4.0-obs.1" style versions).
"""Генерирует файл версии Windows для PyInstaller (--version-file):
автор, копирайт и версия видны в «Свойства файла → Подробно»."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041904B0', [
      StringStruct('CompanyName', {company!r}),
      StringStruct('FileDescription', 'Obsidian Mirror — phone screen and camera on Windows'),
      StringStruct('FileVersion', {ver!r}),
      StringStruct('InternalName', 'Obsidian Mirror'),
      StringStruct('LegalCopyright', {copyright!r}),
      StringStruct('OriginalFilename', 'Obsidian Mirror.exe'),
      StringStruct('ProductName', 'Obsidian Mirror'),
      StringStruct('ProductVersion', {ver!r}),
      StringStruct('Comments', {url!r})])]),
    VarFileInfo([VarStruct('Translation', [0x0419, 1200])])
  ]
)
"""


def main(out: str) -> None:
    # "1.4.0-obs.1" -> 1.4.0.1 (Windows wants four numbers)
    parts = [int(x) for x in re.findall(r"\d+", app.__version__)][:4]
    tup = tuple(parts + [0] * (4 - len(parts)))
    text = TEMPLATE.format(tup=tup, ver=app.__version__, url=app.__url__,
                           company=app.__fork_by__,
                           copyright=f"{app.__copyright__}. GPL-3.0")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(text, encoding="utf-8")
    print("version file ->", out)


if __name__ == "__main__":
    main(sys.argv[1])
