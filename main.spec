# -*- mode: python ; coding: utf-8 -*-
# Build: uv run pyinstaller main.spec --noconfirm
# Gera dist/mu-captcha-resolver.exe — basta copiar o .exe junto com o .env
# (com CAPTCHA_API_KEY e, opcionalmente, CAPTCHA_2CAPTCHA_API_KEY).
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all('playwright')
datas2, binaries2, hiddenimports2 = collect_all('anticaptchaofficial')
datas += datas2
binaries += binaries2
hiddenimports += hiddenimports2
datas3, binaries3, hiddenimports3 = collect_all('twocaptcha')
datas += datas3
binaries += binaries3
hiddenimports += hiddenimports3

a = Analysis(
    ['main.py'],
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
    name='mu-captcha-resolver',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
