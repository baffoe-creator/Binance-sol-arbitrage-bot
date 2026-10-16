$projectDir = "C:\Users\hp\binance-sol-arb-bot"
$venvPython = "$projectDir\venv\Scripts\python.exe"
$script = "$projectDir\scripts\run_arb_sol.py"

Set-Location $projectDir

while ($true) {
    Write-Output "$(Get-Date) - Starting SOL arb bot"
    & $venvPython $script
    Write-Output "$(Get-Date) - Bot exited (code $LASTEXITCODE), restarting in 10s"
    Start-Sleep -Seconds 10
}