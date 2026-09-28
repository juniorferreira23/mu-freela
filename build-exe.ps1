# Gera o executavel standalone em dist/mu-captcha-resolver.exe
# Pre-requisito: uv sync (instala deps incluindo pyinstaller do grupo dev)
$ErrorActionPreference = 'Stop'
uv sync
uv run pyinstaller main.spec --noconfirm --clean
Write-Host "`n[OK] Executavel gerado em: dist/mu-captcha-resolver.exe"
Write-Host "Distribua o .exe junto com um arquivo .env (veja .env.example)."
