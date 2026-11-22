# Installs everything the assistant needs on Windows. Safe to re-run.
#   1. Python (downloaded from python.org if missing) + virtualenv + requirements
#   2. AbletonOSC remote script into the Ableton User Library (patched to expose count_in_duration)
#   3. Pre-downloads the speech model
param([string]$UserLibrary = "$env:USERPROFILE\Documents\Ableton\User Library")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$log = Join-Path $root "install.log"
Start-Transcript -Path $log -Force | Out-Null

function Test-Py($exe, $extra) {
    try {
        $out = & $exe @extra -c "import sys; print(sys.executable); print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and $out[1] -match "^3\.(1[0-3])$") { return $out[0] }
    } catch {}
    return $null
}
function Find-Python {
    $local = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $local) { $r = Test-Py $local @(); if ($r) { return $r } }
    foreach ($v in @("-3.12", "-3.13", "-3.11", "-3.10")) {
        if (Get-Command py -ErrorAction SilentlyContinue) { $r = Test-Py "py" @($v); if ($r) { return $r } }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) { $r = Test-Py "python" @(); if ($r) { return $r } }
    return $null
}

Write-Host "== Python =="
$py = Find-Python
if (-not $py) {
    Write-Host "No suitable Python found, downloading Python 3.12 from python.org..."
    $installer = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -OutFile $installer
    Start-Process -FilePath $installer -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0 Include_test=0 Include_doc=0" -Wait
    $py = Find-Python
    if (-not $py) { throw "Python install finished but python wasn't found." }
}
Write-Host "Using: $py"

Write-Host "== Virtualenv + packages =="
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "== AbletonOSC =="
$rs = Join-Path $UserLibrary "Remote Scripts"
New-Item -ItemType Directory -Force -Path $rs | Out-Null
$zip = Join-Path $env:TEMP "AbletonOSC.zip"
$tmp = Join-Path $env:TEMP "AbletonOSC-extract"
Invoke-WebRequest -Uri "https://github.com/ideoforms/AbletonOSC/archive/refs/heads/master.zip" -OutFile $zip
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$dest = Join-Path $rs "AbletonOSC"
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
Copy-Item (Join-Path $tmp "AbletonOSC-master") $dest -Recurse
# expose Song.count_in_duration (AbletonOSC doesn't by default)
$song = Join-Path $dest "abletonosc\song.py"
$txt = Get-Content $song -Raw
if ($txt -notmatch "count_in_duration") {
    $txt = $txt -replace '("clip_trigger_quantization",)', "`$1`r`n            `"count_in_duration`","
    Set-Content -Path $song -Value $txt -NoNewline
}
Write-Host "Installed to $dest"

Write-Host "== Speech model =="
& .\.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8'); print('model ready')"

Write-Host ""
Write-Host "DONE. Remaining: enable AbletonOSC in Live (Preferences > Link, Tempo & MIDI > Control Surface), then run run.bat"
Stop-Transcript | Out-Null
