# Запуск локального сервера Git Support. Enter останавливает запущенный этим окном сервер.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$port = 8025
$url = "http://127.0.0.1:$port/"
$server = $null
$stdout = $null
$stderr = $null
$originalPort = $env:PORT
$portOverrideActive = $false
$logs = Join-Path $projectRoot 'logs'

function Test-PortOpen {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $pending = $client.BeginConnect('127.0.0.1', $port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($pending)
        return $true
    } catch { return $false } finally { $client.Dispose() }
}

function Get-ListenerPid {
    $pattern = "^\s*TCP\s+127\.0\.0\.1:$port\s+\S+\s+LISTENING\s+\d+\s*$"
    $line = netstat -ano -p tcp 2>$null | Select-String $pattern | Select-Object -First 1
    if ($line) { return [int](($line.ToString().Trim() -split '\s+')[-1]) }
    return $null
}

try {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw 'Не найдена проектная .venv. Установите зависимости по README.md.'
    }
    if (Test-PortOpen) {
        throw "Порт $port уже занят. Git Support не запускался."
    }

    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stdout = Join-Path $logs "server-$stamp.out.log"
    $stderr = Join-Path $logs "server-$stamp.err.log"

    $env:PORT = "$port"
    $portOverrideActive = $true
    $server = Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', $port) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($server.HasExited) { break }
        try {
            $response = Invoke-WebRequest -Uri $url -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "Сервер не запустился. Проверьте $stderr" }

    Start-Process -FilePath $url
    Write-Host "Git Support открыт: $url" -ForegroundColor Green
    Write-Host 'Нажмите Enter, чтобы остановить сервер и закрыть окно.' -ForegroundColor Yellow
    [void](Read-Host)
} catch {
    Write-Host "Ошибка: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Нажмите Enter для выхода.' -ForegroundColor Yellow
    [void](Read-Host)
} finally {
    $listenerPid = Get-ListenerPid
    if ($listenerPid -and $server -and $listenerPid -eq $server.Id) {
        try { Stop-Process -Id $listenerPid -Force -ErrorAction Stop }
        catch { Write-Host "Не удалось остановить сервер на порту $port (PID $listenerPid): $($_.Exception.Message)" -ForegroundColor Red }
    }
    if ($server) {
        try {
            if (-not $server.HasExited) {
                & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $server.Id /T /F 2>$null | Out-Null
                [void]$server.WaitForExit(5000)
            }
        } catch { Write-Host "Не удалось остановить PID $($server.Id): $($_.Exception.Message)" -ForegroundColor Red }
        $server.Dispose()
    }
    if ($portOverrideActive) {
        if ($null -eq $originalPort) { Remove-Item Env:PORT -ErrorAction SilentlyContinue }
        else { $env:PORT = $originalPort }
    }
    foreach ($path in @($stdout, $stderr)) {
        if ($path -and (Test-Path -LiteralPath $path -PathType Leaf)) {
            $text = [System.IO.File]::ReadAllText($path)
            [System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($true))
        }
    }
}
