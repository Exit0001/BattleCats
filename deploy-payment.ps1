# Deploy payment.py to VPS (whatever SLIP_PROVIDER is currently set in the file)
$ErrorActionPreference = "Stop"
$main = $PSScriptRoot

$line = Select-String -Path "$main\payment.py" -Pattern '^SLIP_PROVIDER' | Select-Object -First 1
Write-Host ""
Write-Host "Provider in file : $($line.Line.Trim())" -ForegroundColor Cyan

Write-Host "[1/3] Running security tests..." -ForegroundColor Cyan
$out = & "$main\.venv\Scripts\python.exe" -X utf8 "$main\test_slip_security.py" 2>&1
if ($out -match "FAIL") { $out; Write-Host "ABORTED - tests failed" -ForegroundColor Red; exit 1 }
$out | Select-String -Pattern "14/14|8/8"

Write-Host ""
Write-Host "[2/3] Uploading payment.py..." -ForegroundColor Cyan
$pass = ConvertTo-SecureString "SZ/(-6p-x/(yXXQW" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential("root", $pass)
Set-SCPItem -ComputerName "187.77.156.253" -Credential $cred -Path "$main\payment.py" -Destination "/battlecats/" -Force -AcceptKey

Write-Host ""
Write-Host "[3/3] Restart + verify..." -ForegroundColor Cyan
$s = New-SSHSession -ComputerName "187.77.156.253" -Credential $cred -AcceptKey -Force
$r = Invoke-SSHCommand -SSHSession $s -Command "mkdir -p /battlecats/logs; systemctl restart battlecats; sleep 4; grep -m1 '^SLIP_PROVIDER' /battlecats/payment.py; systemctl is-active battlecats"
$r.Output
Remove-SSHSession $s | Out-Null
Write-Host ""
Write-Host "DONE" -ForegroundColor Green
