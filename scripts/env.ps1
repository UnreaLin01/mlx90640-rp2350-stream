# Tool locations shared by the other scripts, all inside the VS Code Pico
# extension's install folder. PATH is not used because MSYS2 tools shadow
# these.
$PicoRoot        = Join-Path $env:USERPROFILE '.pico-sdk'

# Two kinds of tool version.
#
# Pinned: the SDK, the compiler and picotool. A different version could
# build a different firmware, so exactly these are used. They are also
# written in the root CMakeLists.txt, which is how the extension knows to
# install exactly these when the project is opened.
$SdkVersion       = '2.3.1'
$ToolchainVersion = '15_2_Rel1'
$PicotoolVersion  = '2.3.1'

# Preferred: CMake and Ninja only drive the build; the firmware comes out
# the same with any recent version. These two are used if installed, and
# otherwise the newest version that is. Without this, anyone whose
# extension installed a different CMake got "cmake.exe not found".
$CmakeVersion     = 'v4.3.4'
$NinjaVersion     = 'v1.13.2'

# Resolve a tool whose version does not matter. Returns the path, and sets
# $script:ToolFallbacks when it had to use a version other than the
# preferred one, so build.ps1 can say so. When nothing is installed the
# preferred path is returned anyway, so the error names what is missing.
$script:ToolFallbacks = @()
function Resolve-AnyVersion([string]$Kind, [string]$Preferred, [string]$RelPath) {
	$want = Join-Path $PicoRoot "$Kind\$Preferred\$RelPath"
	if (Test-Path $want) { return $want }

	$newest = Get-ChildItem (Join-Path $PicoRoot $Kind) -Directory -ErrorAction SilentlyContinue |
		Where-Object { Test-Path (Join-Path $_.FullName $RelPath) } |
		Sort-Object { try { [version]($_.Name -replace '^v', '') } catch { [version]'0.0' } } -Descending |
		Select-Object -First 1
	if ($newest) {
		$script:ToolFallbacks += "$Kind $Preferred is not installed, using $($newest.Name)"
		return Join-Path $newest.FullName $RelPath
	}
	return $want
}

$PicoSdkPath     = Join-Path $PicoRoot "sdk\$SdkVersion"
$PicoToolchain   = Join-Path $PicoRoot "toolchain\$ToolchainVersion"
$PicotoolDir     = Join-Path $PicoRoot "picotool\$PicotoolVersion\picotool"
$PioasmDir       = Join-Path $PicoRoot "tools\$SdkVersion\pioasm"
$PicoCmake       = Resolve-AnyVersion 'cmake' $CmakeVersion 'bin\cmake.exe'
$PicoNinja       = Resolve-AnyVersion 'ninja' $NinjaVersion 'ninja.exe'

# Check that everything a build needs is installed, and stop with a clear
# message if not. Only build.ps1 calls this: the flash scripts need none of
# CMake or Ninja, and must keep working on a PC that cannot build.
function Assert-BuildTools {
	$need = [ordered]@{
		"Pico SDK $SdkVersion"             = $PicoSdkPath
		"arm-none-eabi-gcc $ToolchainVersion" = $PicoToolchain
		"picotool $PicotoolVersion"        = $PicotoolDir
		"pioasm $SdkVersion"               = $PioasmDir
		'CMake'                            = $PicoCmake
		'Ninja'                            = $PicoNinja
	}
	$missing = @($need.GetEnumerator() | Where-Object { -not (Test-Path $_.Value) })
	if ($missing.Count -eq 0) {
		$script:ToolFallbacks | ForEach-Object { Write-Host "note: $_" -ForegroundColor Yellow }
		return
	}

	Write-Host ''
	Write-Host '=== build tools not found ====================================' -ForegroundColor Red
	Write-Host ''
	Write-Host '  Missing:'
	$missing | ForEach-Object { Write-Host "    $($_.Key)" }
	Write-Host ''
	Write-Host '  What to do:' -ForegroundColor Yellow
	Write-Host '    1. install the "Raspberry Pi Pico" extension in VS Code'
	Write-Host '    2. open this project folder in VS Code'
	Write-Host '    3. accept when the extension offers to install the missing'
	Write-Host '       tools, then build again'
	Write-Host ''
	Write-Host "  They all go into $PicoRoot"
	Write-Host ''
	Write-Host '=============================================================' -ForegroundColor Red
	exit 1
}

$JLinkDir        = 'C:\Program Files\SEGGER\JLink'
$JLinkExe        = Join-Path $JLinkDir 'JLink.exe'
$JLinkRttLogger  = Join-Path $JLinkDir 'JLinkRTTLogger.exe'
$JLinkDevice     = 'RP2350_M33_0'
$JLinkSpeed      = 4000
# Without a probe plugged in, the two J-Link tools behave differently:
#   - J-Link Commander (flash.ps1) runs with -NoGui 1, so it just prints
#     "Cannot connect to the probe/programmer" and exits.
#   - The RTT logger (rtt.ps1) has no such option. It opens a "Probe
#     selection" dialog asking whether to connect over TCP/IP, and waits
#     for a click. That is left as it is on purpose: the dialog already
#     says "No probes connected via USB", and someone is at the PC anyway
#     whenever a J-Link task runs.

$ProjectRoot     = Split-Path $PSScriptRoot -Parent
$FirmwareDir     = Join-Path $ProjectRoot 'firmware'
# CMake is configured from the project root (see CMakeLists.txt there), so
# everything is built under build/. The flashable files are kept apart from
# CMake's working files (firmware/CMakeLists.txt, add_image):
#   build/images/        the main firmwares
#   build/images/tests/  the development-only test images
$BuildDir        = Join-Path $ProjectRoot 'build'
$FirmwareOutDir  = Join-Path $BuildDir 'images'
$TestImageDir    = Join-Path $FirmwareOutDir 'tests'
$FirmwareElf     = Join-Path $FirmwareOutDir 'mlx_thermal.elf'

# Path of a built image by name, whichever of the two folders it is in.
# Returns $null if it has not been built.
function Find-Image([string]$Name, [string]$Ext) {
	foreach ($dir in $FirmwareOutDir, $TestImageDir) {
		$path = Join-Path $dir "$Name$Ext"
		if (Test-Path $path) { return $path }
	}
	return $null
}
$LogDir          = Join-Path $ProjectRoot 'logs'
