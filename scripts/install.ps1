# Installs everything the assistant needs on Windows. Safe to re-run.
#   1. Python (via winget if missing) + virtualenv + requirements
#   2. AbletonOSC remote script into the Ableton User Library (patched to expose count_in_duration)
#   3. Pre-downloads the speech model
param([string]$UserLibrary = "$env:USERPROFILE\Documents\Ableton\User Library")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$log = Join-Path $root "install.log"
Start-Transcript -Path $log -Force | Out-Null

function Find-Python {
    foreach ($cmd in @("py -3.12", "py -3.13", "py -3.11", "py -3.10", "python")) {
        try {
            $parts = $cmd.Split(" ")
            $exe = $parts[0]; $rest = $parts[1..($parts.Length)] | Where-Object { $_ }
            $v = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v -match "^3\.(1[0-3])$") { return ,@($exe) + @($rest) }
        } catch {}
    }
    return $null
}

Write-Host "== Python =="
$py = Find-Python
if (-not $py) {
    Write-Host "No suitable Python found, installing Python 3.12 with winget..."
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $py = Find-Python
    if (-not $py) { throw "Python install finished but python wasn't found. Open a new terminal and re-run install.bat." }
}
Write-Host "Using: $($py -join ' ')"

Write-Host "== Virtualenv + packages =="
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py[0] @($py[1..($py.Length)] | Where-Object { $_ }) -m venv .venv }
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
