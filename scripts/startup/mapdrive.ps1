# Re-map the Tailscale file share at login, once Tailscale is up. Log: mapdrive.log next to this script.
$ip = '100.66.214.64'
$letter = 'D:'
$log = Join-Path $PSScriptRoot 'mapdrive.log'
function L($m) { "$(Get-Date -Format s) $m" | Add-Content -Path $log }
L "start"
$up = $false
for ($i = 0; $i -lt 90; $i++) {          # wait up to ~7.5 min for Tailscale + the share host
    try {
        $c = New-Object Net.Sockets.TcpClient
        $iar = $c.BeginConnect($ip, 445, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne(3000) -and $c.Connected) { $up = $true; $c.Close(); break }
        $c.Close()
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $up) { L "host $ip port 445 unreachable"; exit 1 }
L "host reachable"
$view = (net view "\\$ip" 2>&1) -join "`n"
L ("net view:`n" + $view)
$shares = @()
foreach ($line in ($view -split "`n")) { if ($line -match '^(\S.*?)\s{2,}Disk\b') { $shares += $matches[1].Trim() } }
$current = (net use 2>&1) -join "`n"
L ("net use:`n" + $current)
if ($current -match "$letter\s+\\\\$([regex]::Escape($ip))\\" -and $current -match "OK\s+$letter") { L "already mapped"; exit 0 }
if ($shares.Count -eq 0) { L "no disk shares found"; exit 2 }
net use $letter /delete /y 2>&1 | Out-Null
$out = (net use $letter "\\$ip\$($shares[0])" /persistent:yes 2>&1) -join "`n"
L "mapped $letter -> \\$ip\$($shares[0]): $out"
