$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$UvExecutable = if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.tools\uv\uv.exe')) {
    Join-Path $ProjectRoot '.tools\uv\uv.exe'
} elseif (Get-Command uv -ErrorAction SilentlyContinue) {
    (Get-Command uv).Source
} else {
    throw 'Install uv first using the official instructions at https://docs.astral.sh/uv/getting-started/installation/.'
}
# No project .venv. uv creates isolated environments in its own cache.
$env:UV_CACHE_DIR = Join-Path $ProjectRoot '.tools\uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $ProjectRoot '.tools\python'
function Invoke-ProjectPython {
    & $UvExecutable run --isolated --locked --managed-python --no-dev python @args
    if ($LASTEXITCODE -ne 0) { throw "Application command failed (exit $LASTEXITCODE)." }
}
