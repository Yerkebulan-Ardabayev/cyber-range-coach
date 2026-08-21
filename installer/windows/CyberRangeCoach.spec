# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parents[1]
datas = [
    (str(root / "frontend" / "dist"), "frontend/dist"),
    (str(root / "curriculum"), "curriculum"),
    (str(root / "installer" / "linux"), "installer/linux"),
    (str(root / "backend" / "migrations"), "backend/migrations"),
    (str(root / "alembic.ini"), "."),
]
tesseract = root / "vendor" / "tesseract"
if tesseract.is_dir():
    datas.append((str(tesseract), "vendor/tesseract"))

a = Analysis(
    [str(root / "backend" / "src" / "cyber_range_coach" / "__main__.py")],
    pathex=[str(root / "backend" / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("uvicorn") + collect_submodules("asyncssh"),
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "playwright"],
    noarchive=False,
)
pyz = PYZ(a.pure)
academy_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CyberRangeCoach",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
doctor_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CyberRangeCoachDoctor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    academy_exe,
    doctor_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CyberRangeCoach",
)
