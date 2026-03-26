# PC Activity Tracker — watchdog
# Checks if tracker API is responding, restarts if not.

$trackerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 27420
$logFile = Join-Path $trackerDir "data\watchdog.log"

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Out-File -Append -Encoding utf8 $logFile
}

try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:$port/status" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    if ($response.StatusCode -eq 200) {
        # Tracker is alive — nothing to do
        exit 0
    }
} catch {
    # Tracker is not responding — restart
    Write-Log "Tracker not responding. Restarting..."
    try {
        Start-Process "wscript.exe" -ArgumentList "`"$trackerDir\start_tray.vbs`""
        Write-Log "Restart command sent."
    } catch {
        Write-Log "Failed to restart: $_"
    }
}
