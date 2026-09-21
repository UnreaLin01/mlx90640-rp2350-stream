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
if ($LASTEXITCODE -ne 0) {
	# An exit code on its own says nothing. List what actually goes wrong,
	# in the order it usually does.
	Write-Host ''
	Write-Host '=== J-Link flashing failed ==================================' -ForegroundColor Red
	Write-Host ''
	Write-Host '  Check, in this order:' -ForegroundColor Yellow
	Write-Host '    1. the J-Link is plugged into the PC'
	Write-Host '       ("Cannot connect to the probe" above means it was not found)'
	Write-Host '    2. SWDIO and SWCLK go to the board, and VTref goes to 3V3'
	Write-Host '       (without VTref the J-Link thinks the board has no power)'
	Write-Host '    3. the board is powered, through its USB cable'
	Write-Host '    4. nothing else is holding the J-Link - close J-Link'
	Write-Host '       Commander or the RTT Viewer'
	Write-Host ''
	Write-Host '  The message J-Link printed above says which one it is.'
	Write-Host ''
	Write-Host '  No J-Link at hand? Flash over USB instead:'
	Write-Host '    powershell -File scripts/flash_usb.ps1'
	Write-Host ''
	Write-Host '=============================================================' -ForegroundColor Red
	exit 1
}
