$projectDir = "C:\Users\hp\binance-sol-arb-bot"
$venvPython = "$projectDir\venv\Scripts\python.exe"
$script = "$projectDir\scripts\run_arb_sol.py"

# Exit codes from run_arb_sol.py that mean "stopped on purpose, do NOT restart":
#   2 = trailing stop / risk halt, 3 = unfinished cycle needs manual check
$noRestartCodes = @(2, 3)

Set-Location $projectDir

while ($true) {
    Write-Output "$(Get-Date) - Starting SOL arb bot"
    & $venvPython $script
    $code = $LASTEXITCODE

    if ($noRestartCodes -contains $code) {
        Write-Output "$(Get-Date) - Bot stopped deliberately (code $code). NOT restarting. Check logs\trading_bot_sol.log, fix the cause, then start it manually."
        break
    }

    Write-Output "$(Get-Date) - Bot exited (code $code), restarting in 10s"
    Start-Sleep -Seconds 10
}