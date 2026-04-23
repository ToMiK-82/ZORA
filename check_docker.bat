@echo off
echo ========================================
echo Docker Desktop Checker
echo ========================================

echo.
echo Checking Docker status...

REM Проверка версии Docker
docker version >nul 2>&1
if %errorlevel% equ 0 (
    echo ✅ Docker is running
    echo.
    echo Docker info:
    docker version --format "{{.Client.Version}}" 2>nul
    echo.
    echo You can now run: .\start_zora_improved.bat
    pause
    exit /b 0
)

echo ❌ Docker is not running or not installed
echo.
echo Please do one of the following:
echo.
echo 1. Start Docker Desktop manually:
echo    - Search for "Docker Desktop" in Start Menu
echo    - Click "Start" button
echo    - Wait for Docker icon to show in system tray
echo.
echo 2. Or run Docker Desktop from command line:
echo    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
echo.
echo 3. After Docker Desktop starts, wait 30 seconds and try again
echo.
echo 4. If Docker is not installed, download from:
echo    https://www.docker.com/products/docker-desktop/
echo.
pause

REM Попытка запустить Docker Desktop автоматически
echo.
echo Attempting to start Docker Desktop...
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe" 2>nul
if %errorlevel% equ 0 (
    echo Docker Desktop started. Please wait 30 seconds...
    timeout /t 30 /nobreak >nul
    goto check_again
) else (
    echo Could not start Docker Desktop automatically
    echo Please start it manually
)

:check_again
echo.
echo Checking Docker status again...
docker version >nul 2>&1
if %errorlevel% equ 0 (
    echo ✅ Docker is now running!
    echo.
    echo You can now run: .\start_zora_improved.bat
) else (
    echo ❌ Docker is still not running
    echo Please start Docker Desktop manually
)

pause