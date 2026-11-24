# Switch slip provider then deploy.   Usage:  .\switch-provider.ps1 easyslip
#                                             .\switch-provider.ps1 slip2go
param([Parameter(Mandatory=$true)][ValidateSet("easyslip","slip2go")][string]$Provider)
$ErrorActionPreference = "Stop"
$main = $PSScriptRoot
$f = "$main\payment.py"

$txt = [System.IO.File]::ReadAllText($f, [System.Text.Encoding]::UTF8)
$new = [regex]::Replace($txt, '(?m)^SLIP_PROVIDER(\s*)= ".*?"', "SLIP_PROVIDER`$1= `"$Provider`"")
if ($new -eq $txt) { Write-Host "Nothing changed - already '$Provider'?" -ForegroundColor Yellow }
[System.IO.File]::WriteAllText($f, $new, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "Switched to: $Provider" -ForegroundColor Green
& "$main\deploy-payment.ps1"
