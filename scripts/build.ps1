# Configure (first time) and build the firmware.
param([switch]$Clean)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')
Assert-BuildTools

if ($Clean -and (Test-Path $BuildDir)) {
	Remove-Item -Recurse -Force $BuildDir
}

if (-not (Test-Path (Join-Path $BuildDir 'build.ninja'))) {
	& $PicoCmake -S $ProjectRoot -B $BuildDir -G Ninja `
		"-DCMAKE_MAKE_PROGRAM=$PicoNinja" `
		"-DPICO_SDK_PATH=$PicoSdkPath" `
		"-DPICO_TOOLCHAIN_PATH=$PicoToolchain" `
		"-Dpicotool_DIR=$PicotoolDir" `
		"-Dpioasm_DIR=$PioasmDir" `
		'-DPICO_BOARD=pico2' `
		'-DCMAKE_BUILD_TYPE=RelWithDebInfo'
	if ($LASTEXITCODE -ne 0) { throw "cmake configure failed ($LASTEXITCODE)" }
}

& $PicoCmake --build $BuildDir
if ($LASTEXITCODE -ne 0) { throw "build failed ($LASTEXITCODE)" }
Write-Host "Built: $FirmwareElf"
