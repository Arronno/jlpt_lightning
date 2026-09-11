. "$PSScriptRoot\uv-common.ps1"
$env:JLPT_DATA_DIR = Join-Path $ProjectRoot '.runtime\checks'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $ProjectRoot '.tools\browsers'
& $UvExecutable run --isolated --locked --managed-python ruff check .
if ($LASTEXITCODE -ne 0) { throw 'Lint failed.' }
& $UvExecutable run --isolated --locked --managed-python ruff format --check .
if ($LASTEXITCODE -ne 0) { throw 'Format check failed.' }
& $UvExecutable run --isolated --locked --managed-python pytest @args
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
