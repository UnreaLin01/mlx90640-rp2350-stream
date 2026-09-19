# Flash the firmware ELF over SWD with J-Link Commander, then reset and run.
# Stops any running RTT logger first (it holds the J-Link).
param([string]$Elf)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')
if (-not $Elf) { $Elf = $FirmwareElf }
if (-not (Test-Path $Elf)) { throw "ELF not found: $Elf" }

Get-Process JLinkRTTLogger -ErrorAction SilentlyContinue | Stop-Process -Force

$cmdFile = Join-Path $env:TEMP 'mlx_thermal_flash.jlink'
@"
connect
halt
loadfile "$Elf"
r
g
exit
"@ | Set-Content -Encoding ascii $cmdFile

& $JLinkExe -NoGui 1 -ExitOnError 1 -device $JLinkDevice -if SWD -speed $JLinkSpeed -autoconnect 1 -CommandFile $cmdFile
if ($LASTEXITCODE -ne 0) { throw "J-Link flash failed ($LASTEXITCODE)" }
