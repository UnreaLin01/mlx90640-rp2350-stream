# Flash over USB with picotool - no J-Link needed.
#
# The USB firmware has the Raspberry Pi reset interface, so picotool can
# restart the board into BOOTSEL mode by itself (-f) and start the new
# firmware afterwards (-x). The BOOTSEL button is only needed if the board
# currently runs firmware without USB (for example mlx_thermal_udp) or no
# firmware at all: hold BOOTSEL while plugging in the USB cable, then run
# this again.
param([string]$Firmware = 'mlx_thermal')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')

$picotool = Join-Path $PicotoolDir 'picotool.exe'
$uf2 = Join-Path $FirmwareOutDir "$Firmware.uf2"
if (-not (Test-Path $uf2)) { throw "not built: $uf2 (run scripts/build.ps1)" }

# The RTT logger holds the J-Link, not USB, but stop it anyway: the board
# is about to restart.
Get-Process JLinkRTTLogger -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "picotool load $uf2"
& $picotool load -f -x $uf2
if ($LASTEXITCODE -ne 0) {
	throw @"
picotool failed ($LASTEXITCODE).
If the board is not in BOOTSEL mode and its firmware has no USB (for
example mlx_thermal_udp), hold BOOTSEL while connecting USB and retry,
or flash over SWD: scripts/flash.ps1 -Elf $FirmwareOutDir\$Firmware.elf
"@
}
