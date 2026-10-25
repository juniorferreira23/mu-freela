# -*- mode: python ; coding: utf-8 -*-
# Build: uv run --locked pyinstaller main_2captcha.spec --noconfirm --clean
# Gera dist/mu-captcha-resolver-2captcha.exe; distribua junto do arquivo .env.
from PyInstaller.utils.hooks import collect_all, copy_metadata


datas, binaries, hiddenimports = collect_all("playwright")
datas += copy_metadata("python-dotenv")

a = Analysis(
    ["main_2captcha.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mu-captcha-resolver-2captcha",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
