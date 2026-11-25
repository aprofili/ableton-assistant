# Open the RODECaster App at startup (if it isn't already running).
$exe = 'C:\Program Files\RØDE Microphones\RODECaster App\RODECaster App.exe'
if ((Test-Path -LiteralPath $exe) -and -not (Get-Process -Name 'RODECaster App' -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $exe
}
