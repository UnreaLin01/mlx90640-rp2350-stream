# Flash over USB with picotool - no J-Link needed.
#
# The USB firmware has the Raspberry Pi reset interface, so picotool can
# restart the board into BOOTSEL mode by itself (-f) and start the new
# firmware afterwards (-x). When it cannot, the message at the bottom of
# this file says what to do, so nobody has to know this in advance.
param([string]$Firmware = 'mlx_thermal')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')

$picotool = Join-Path $PicotoolDir 'picotool.exe'
# Test images live in their own folder; look in both, so a name is enough.
$uf2 = Find-Image $Firmware '.uf2'
if (-not $uf2) { throw "not built: $Firmware.uf2 (run scripts/build.ps1)" }
$elf = [IO.Path]::ChangeExtension($uf2, '.elf')

# The RTT logger holds the J-Link, not USB, but stop it anyway: the board
# is about to restart.
Get-Process JLinkRTTLogger -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "picotool load $uf2"
& $picotool load -f -x $uf2
if ($LASTEXITCODE -ne 0) {
	# Say what to do here, at the moment it is needed. The rule is easy to
	# forget, and there is no reason to carry it around in your head.
	Write-Host ''
	Write-Host '=== flashing failed =========================================' -ForegroundColor Red
	Write-Host ''
	Write-Host '  picotool could not reach the board.'
	Write-Host ''
	Write-Host '  It can restart the board by itself only when the firmware'
	Write-Host '  ALREADY on the board has USB. mlx_thermal and its 16/64 Hz'
	Write-Host '  versions have it; mlx_thermal_udp and the test images do not,'
	Write-Host '  and neither does a board that was never flashed.'
	Write-Host ''
	Write-Host '  What to do:' -ForegroundColor Yellow
	Write-Host '    1. unplug the USB cable'
	Write-Host '    2. hold the BOOTSEL button down and plug it back in'
	Write-Host '    3. run this again (the button can be released now)'
	Write-Host ''
	Write-Host '  With a J-Link attached you can skip all of that:'
	Write-Host "    powershell -File scripts/flash.ps1 -Elf $elf"
	Write-Host ''
	Write-Host '=============================================================' -ForegroundColor Red
	exit 1
}
