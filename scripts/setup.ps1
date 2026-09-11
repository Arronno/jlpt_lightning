. "$PSScriptRoot\uv-common.ps1"
& $UvExecutable python install 3.13
if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
Invoke-ProjectPython manage.py local setup
& "$PSScriptRoot\editor.ps1"
