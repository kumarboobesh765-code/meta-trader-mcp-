$ErrorActionPreference = "SilentlyContinue"

$chatId = "1819206234"
$tokenFile = "C:\VPSMonitor\telegram-token.txt"
$stateFile = "C:\VPSMonitor\state.json"
$logFile = "C:\VPSMonitor\monitor.log"

function Write-Log($message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message" |
        Add-Content $logFile
}

$encryptedToken = (Get-Content $tokenFile -Raw).Trim()
$secureToken = ConvertTo-SecureString $encryptedToken
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)

try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}

function Send-Telegram($message) {
    try {
        Invoke-RestMethod `
            -Uri "https://api.telegram.org/bot$($token)/sendMessage" `
            -Method Post `
            -Body @{
                chat_id = $chatId
                text = $message
            } | Out-Null
        Write-Log "Telegram alert sent: $message"
    }
    catch {
        Write-Log "Telegram send failed: $($_.Exception.Message)"
    }
}

$state = @{ Internet = $null; MT5 = $null }

if (Test-Path $stateFile) {
    try {
        $saved = Get-Content $stateFile -Raw | ConvertFrom-Json
        $state.Internet = $saved.Internet
        $state.MT5 = $saved.MT5
    }
    catch {}
}

Send-Telegram "VPS Monitor started on $env:COMPUTERNAME"

while ($true) {
    $internet = [bool](Test-Connection "1.1.1.1" -Count 1 -Quiet)
    $mt5 = [bool](Get-Process terminal64 -ErrorAction SilentlyContinue)

    if ($null -ne $state.Internet -and $internet -ne $state.Internet) {
        if ($internet) {
            Send-Telegram "VPS internet connection restored."
        } else {
            Send-Telegram "WARNING: VPS internet connection lost."
        }
    }

    if ($null -ne $state.MT5 -and $mt5 -ne $state.MT5) {
        if ($mt5) {
            Send-Telegram "MetaTrader 5 is running again."
        } else {
            Send-Telegram "WARNING: MetaTrader 5 has stopped running!"
        }
    }

    $state.Internet = $internet
    $state.MT5 = $mt5

    $state | ConvertTo-Json | Set-Content $stateFile

    Write-Log "Check completed. Internet=$internet MT5=$mt5"

    Start-Sleep -Seconds 60
}
