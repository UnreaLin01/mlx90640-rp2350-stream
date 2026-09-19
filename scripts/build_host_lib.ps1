# Build the PC-side Melexis calculation DLL (host/native/build/mlx90640.dll)
# from the unmodified Melexis library plus host/native/mlx_wrap.c.
# Uses the MSYS2 MinGW-w64 gcc (64-bit, to match the 64-bit Python).
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')

$gcc    = 'C:\msys64\mingw64\bin\gcc.exe'
$mlx    = Join-Path $ProjectRoot 'third_party\mlx90640-library'
$native = Join-Path $ProjectRoot 'host\native'
$out    = Join-Path $native 'build'
New-Item -ItemType Directory -Force $out | Out-Null

# -static-libgcc: no extra MinGW runtime DLL needed next to ours.
& $gcc -O2 -shared -static-libgcc `
	-I (Join-Path $mlx 'headers') `
	-o (Join-Path $out 'mlx90640.dll') `
	(Join-Path $native 'mlx_wrap.c') `
	(Join-Path $mlx 'functions\MLX90640_API.c')
if ($LASTEXITCODE -ne 0) { throw "gcc failed ($LASTEXITCODE)" }
Write-Host "Built: $(Join-Path $out 'mlx90640.dll')"
