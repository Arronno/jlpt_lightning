param([int]$Port = 8765, [switch]$Lan)
. "$PSScriptRoot\uv-common.ps1"
if ($Lan) {
    Invoke-ProjectPython manage.py local serve --port $Port --lan
} else {
    Invoke-ProjectPython manage.py local serve --port $Port
}
