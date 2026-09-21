# Capture RTT channel 0 to logs/ in the background. Stop with -Stop.
# The control block address is taken from the ELF symbol _SEGGER_RTT.
param([switch]$Stop, [string]$Name = 'rtt', [string]$Elf)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')
if (-not $Elf) { $Elf = $FirmwareElf }

Get-Process JLinkRTTLogger -ErrorAction SilentlyContinue | Stop-Process -Force
if ($Stop) { return }

$nm = Join-Path $PicoToolchain 'bin\arm-none-eabi-nm.exe'
$sym = & $nm $Elf | Select-String ' _SEGGER_RTT$'
if (-not $sym) { throw "_SEGGER_RTT not found in $Elf" }
$addr = '0x' + ($sym.Line -split ' ')[0]

New-Item -ItemType Directory -Force $LogDir | Out-Null
$log = Join-Path $LogDir ("{0}_{1:yyyyMMdd_HHmmss}.log" -f $Name, (Get-Date))
$loggerArgs = @('-Device', $JLinkDevice, '-If', 'SWD', '-Speed', $JLinkSpeed,
                '-RTTAddress', $addr, '-RTTChannel', '0', "`"$log`"")
$p = Start-Process -FilePath $JLinkRttLogger -ArgumentList $loggerArgs -WindowStyle Hidden `
	-RedirectStandardOutput "$log.stdout" -PassThru

# The logger runs hidden, so a failure to connect would otherwise look
# exactly like success: a PID is printed and the log file stays empty
# forever. So watch it for a while, until one of:
#   - it exits, or prints ERROR   -> it failed
#   - the log file gets data      -> it works (the firmware logs once per s)
#   - 10 s pass with neither      -> unknown, and said so
#
# A fixed wait would not do. Without a probe the logger first shows the
# J-Link "Probe selection" dialog and only gives up after it is answered,
# which takes as long as the person at the PC takes to click.
$deadline = (Get-Date).AddSeconds(10)
$state = 'silent'
while ((Get-Date) -lt $deadline) {
	Start-Sleep -Milliseconds 250
	$said = Get-Content "$log.stdout" -ErrorAction SilentlyContinue
	if ($p.HasExited -or ($said -match 'ERROR')) { $state = 'failed'; break }
	if ((Test-Path $log) -and (Get-Item $log).Length -gt 0) { $state = 'ok'; break }
}
if ($state -eq 'silent') {
	# Do not call this "connected": the logger may just be waiting behind
	# the probe dialog.
	Write-Host "RTT logger PID $($p.Id) is running, but no log line arrived in 10 s." -ForegroundColor Yellow
	Write-Host '  - A J-Link "Probe selection" dialog is open: no J-Link was found.'
	Write-Host '    Click No, plug it in, and run this again.'
	Write-Host '  - No dialog: the firmware prints nothing yet, or the board runs a'
	Write-Host "    different firmware than $Elf, so the log is read from the"
	Write-Host '    wrong address.'
	Write-Host "  It keeps running; the log goes to $log"
	return
}
if ($state -eq 'failed') {
	if (-not $p.HasExited) { $p.Kill() }
	Write-Host ''
	Write-Host '=== the RTT logger did not start ============================' -ForegroundColor Red
	Write-Host ''
	if (Test-Path "$log.stdout") {
		Write-Host '  What it printed:'
		Get-Content "$log.stdout" | ForEach-Object { Write-Host "    $_" }
		Write-Host ''
	}
	Write-Host '  Check, in this order:' -ForegroundColor Yellow
	Write-Host '    1. the J-Link is plugged into the PC'
	Write-Host '       ("Cannot connect to the probe" above means it was not found)'
	Write-Host '    2. SWDIO and SWCLK go to the board, and VTref goes to 3V3'
	Write-Host '    3. the board is powered, through its USB cable'
	Write-Host '    4. nothing else is holding the J-Link - close J-Link'
	Write-Host '       Commander or the RTT Viewer and try again'
	Write-Host ''
	Write-Host "  The firmware being logged is $Elf - it must be the one that"
	Write-Host '  is actually on the board, or the control block address is wrong.'
	Write-Host ''
	Write-Host '=============================================================' -ForegroundColor Red
	exit 1
}
Write-Host "RTT logger PID $($p.Id), control block $addr -> $log"
