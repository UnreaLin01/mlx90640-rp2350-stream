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
Write-Host "RTT logger PID $($p.Id), control block $addr -> $log"
