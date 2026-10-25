# Gera o executável standalone dist/mu-captcha-resolver-2captcha.exe
# Requer uv e sincroniza as dependências usando uv.lock sem modificá-lo.
$ErrorActionPreference = 'Stop'

Push-Location $PSScriptRoot
try {
    uv sync --locked
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync --locked falhou (código $LASTEXITCODE)."
    }

    uv run --locked pyinstaller main_2captcha.spec --noconfirm --clean
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller falhou (código $LASTEXITCODE)."
    }

    $executavel = Join-Path $PSScriptRoot 'dist\mu-captcha-resolver-2captcha.exe'
    if (-not (Test-Path -LiteralPath $executavel)) {
        throw "Executável não encontrado após o build: $executavel"
    }

    Write-Host "`n[OK] Executável gerado em: $executavel"
    Write-Host 'Distribua o .exe junto de um .env contendo CAPTCHA_2CAPTCHA_API_KEY.'
}
finally {
    Pop-Location
}
