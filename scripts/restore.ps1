param([Parameter(Mandatory = $true)][string]$Backup)
$BackupPath = (Resolve-Path -LiteralPath $Backup).Path
. "$PSScriptRoot\uv-common.ps1"
Invoke-ProjectPython manage.py local restore --source $BackupPath
