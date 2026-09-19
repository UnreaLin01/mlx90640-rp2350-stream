# Tool locations shared by the other scripts. Pinned to the VS Code Pico
# extension install; PATH is not used because MSYS2 tools shadow these.
$PicoRoot        = Join-Path $env:USERPROFILE '.pico-sdk'
$PicoSdkPath     = Join-Path $PicoRoot 'sdk\2.3.1'
$PicoToolchain   = Join-Path $PicoRoot 'toolchain\15_2_Rel1'
$PicoCmake       = Join-Path $PicoRoot 'cmake\v4.3.4\bin\cmake.exe'
$PicoNinja       = Join-Path $PicoRoot 'ninja\v1.13.2\ninja.exe'
$PicotoolDir     = Join-Path $PicoRoot 'picotool\2.3.1\picotool'
$PioasmDir       = Join-Path $PicoRoot 'tools\2.3.1\pioasm'

$JLinkDir        = 'C:\Program Files\SEGGER\JLink'
$JLinkExe        = Join-Path $JLinkDir 'JLink.exe'
$JLinkRttLogger  = Join-Path $JLinkDir 'JLinkRTTLogger.exe'
$JLinkDevice     = 'RP2350_M33_0'
$JLinkSpeed      = 4000

$ProjectRoot     = Split-Path $PSScriptRoot -Parent
$FirmwareDir     = Join-Path $ProjectRoot 'firmware'
$BuildDir        = Join-Path $FirmwareDir 'build'
$FirmwareElf     = Join-Path $BuildDir 'mlx_thermal.elf'
$LogDir          = Join-Path $ProjectRoot 'logs'
