# ybx.ps1 - Windows bootstrap for the ybx.py installer.
#
# Thin, like ybx.sh: it finds Python 3 and hands the arguments to ybx.py (a
# sibling copy when run from a checkout, else one downloaded with the same
# urllib/Python it will use). All install/update logic lives in ybx.py.
#
# One-liner (no clone needed):
#   powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.ps1))) install"
#
# Or save it and run:
#   .\ybx.ps1 install

$ErrorActionPreference = "Stop"

function Get-PythonCommand {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @($py.Source, "-3") }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @($python.Source) }
    return $null
}

$python = Get-PythonCommand
if (-not $python) {
    Write-Error "ybx: Python 3 is required (install it from https://www.python.org/downloads/ and retry)."
    exit 1
}

$scriptPath = Join-Path $PSScriptRoot "ybx.py"
if (-not (Test-Path $scriptPath)) {
    $url = "https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.py"
    $scriptPath = Join-Path ([System.IO.Path]::GetTempPath()) ("ybx-" + [System.Guid]::NewGuid().ToString("N") + ".py")
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $scriptPath
}

# $args holds the arguments after the script name.
$pythonArgs = @()
if ($python.Length -gt 1) { $pythonArgs += $python[1..($python.Length - 1)] }
$pythonArgs += $scriptPath
$pythonArgs += $args

& $python[0] @pythonArgs
exit $LASTEXITCODE
