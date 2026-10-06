param(
    [ValidateSet('start', 'stop', 'status', 'logs', 'backup')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$serviceRoot = Join-Path $repositoryRoot '.artifacts/local-service'
if (-not (Test-Path -LiteralPath (Join-Path $serviceRoot '.env.app'))) {
    throw 'Local restored service configuration is missing. See deploy/relocation_runbook.md.'
}

$composeArguments = @(
    'compose', '-p', 'metacritic-personal',
    '--env-file', (Join-Path $serviceRoot '.env.app'),
    '-f', (Join-Path $serviceRoot 'compose.yaml'),
    '-f', (Join-Path $serviceRoot 'compose.local-private.yaml'),
    '--profile', 'app'
)

switch ($Action) {
    'start' { & docker @composeArguments up -d }
    'stop' { & docker @composeArguments stop }
    'status' { & docker @composeArguments ps -a }
    'logs' { & docker @composeArguments logs --tail 80 web scheduler worker }
    'backup' {
        $backupRoot = Join-Path $repositoryRoot '.artifacts/local-backups'
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        $backupStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $backupFile = Join-Path $backupRoot "database-$backupStamp.dump"
        $containerBackupFile = "/tmp/personal-backup-$backupStamp.dump"
        & docker exec -e "BACKUP_DEST=$containerBackupFile" metacritic-personal-db-1 sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$BACKUP_DEST"'
        if ($LASTEXITCODE -ne 0) { throw 'Database backup failed.' }
        & docker cp "metacritic-personal-db-1:$containerBackupFile" $backupFile
        if ($LASTEXITCODE -ne 0) { throw 'Database backup download failed.' }
        & docker exec metacritic-personal-db-1 rm -f $containerBackupFile
        if ($LASTEXITCODE -ne 0) { throw 'Temporary backup cleanup failed.' }
        Write-Host "Backup: $backupFile"
    }
}
if ($LASTEXITCODE -ne 0) { throw "Local service command failed: $Action" }
