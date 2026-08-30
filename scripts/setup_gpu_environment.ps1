param(
    [string]$Python = "py",
    [string]$VenvDirectory = ".venv"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvPath = Join-Path $repositoryRoot $VenvDirectory
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$requirements = Join-Path $repositoryRoot "requirements-gpu.txt"
$pipCache = Join-Path $repositoryRoot "artifacts\pip_cache"
$temporaryRoot = Join-Path $repositoryRoot "artifacts\tmp"

New-Item -ItemType Directory -Force -Path $pipCache, $temporaryRoot | Out-Null
$env:PIP_CACHE_DIR = $pipCache
$env:TEMP = $temporaryRoot
$env:TMP = $temporaryRoot

if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -3.13 -m venv $venvPath
}

& $venvPython -m ensurepip --upgrade --default-pip
& $venvPython -m pip install -r $requirements

# FastEmbed depends on the CPU distribution by package name. Both ONNX wheels
# install the same ``onnxruntime`` module, so reinstall GPU last and without
# dependency resolution to guarantee that the CUDA binaries win.
& $venvPython -m pip uninstall -y onnxruntime onnxruntime-gpu
& $venvPython -m pip install --no-deps --force-reinstall onnxruntime-gpu==1.29.0

& $venvPython -c "import onnxruntime as ort; ort.preload_dlls(); providers=ort.get_available_providers(); print({'device': ort.get_device(), 'providers': providers}); assert 'CUDAExecutionProvider' in providers"
