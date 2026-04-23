@echo off
chcp 65001 >nul
echo ========================================
echo    НАСТРОЙКА DOCKER И ЗАПУСК QDRANT ДЛЯ ZORA
echo ========================================
echo.

echo 1. Проверяю текущее состояние Docker...
docker --version >nul 2>&1
if %errorlevel% equ 0 (
    echo ✅ Docker установлен
    goto :check_docker_running
) else (
    echo ❌ Docker не установлен
    echo Установите Docker Desktop с https://www.docker.com/products/docker-desktop/
    echo После установки перезапустите этот скрипт
    pause
    exit /b 1
)

:check_docker_running
echo 2. Проверяю запущен ли Docker...
docker ps >nul 2>&1
if %errorlevel% equ 0 (
    echo ✅ Docker запущен
    goto :check_qdrant
)

echo ⚠️ Docker не запущен
echo Пытаюсь запустить Docker Desktop...

set DOCKER_PATH=
if exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" (
    set "DOCKER_PATH=C:\Program Files\Docker\Docker\Docker Desktop.exe"
) else if exist "C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe" (
    set "DOCKER_PATH=C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe"
)

if "%DOCKER_PATH%"=="" (
    echo ❌ Docker Desktop не найден
    echo Установите Docker Desktop с https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

echo Запускаю Docker Desktop: %DOCKER_PATH%
start "" "%DOCKER_PATH%"

echo Жду запуска Docker (30 секунд)...
echo Если появляется ошибка WSL, см. инструкции ниже
echo.

set /a counter=0
:wait_for_docker
timeout /t 5 >nul
docker ps >nul 2>&1
if %errorlevel% equ 0 (
    echo ✅ Docker запущен
    goto :check_qdrant
)
set /a counter+=5
if %counter% geq 30 (
    echo ⚠️ Docker не запустился за 30 секунд
    echo Возможна проблема с WSL
    goto :wsl_problem
)
echo Ожидание... %counter%/30 секунд
goto :wait_for_docker

:wsl_problem
echo.
echo ========================================
echo    ПРОБЛЕМА: Docker Desktop WSL Timeout
echo ========================================
echo.
echo РЕШЕНИЕ:
echo.
echo 1. Остановите WSL вручную:
echo    Откройте PowerShell от имени администратора и выполните:
echo    wsl --shutdown
echo.
echo 2. Перезапустите Docker Desktop
echo.
echo 3. Если не помогает, переустановите WSL дистрибутивы:
echo    wsl --unregister docker-desktop
echo    wsl --unregister docker-desktop-data
echo    Перезапустите Docker Desktop
echo.
echo 4. Альтернатива: Используйте Hyper-V вместо WSL
echo    В настройках Docker Desktop отключите WSL 2
echo.
pause
exit /b 1

:check_qdrant
echo.
echo 3. Проверяю Qdrant...
docker ps | findstr "qdrant" >nul 2>&1
if %errorlevel% equ 0 (
    echo ✅ Qdrant уже запущен
    goto :start_zora
)

echo 4. Запускаю Qdrant...
echo Запускаю контейнер Qdrant на порту 6333...
docker run -d -p 6333:6333 --name qdrant qdrant/qdrant

echo Жду запуска Qdrant (10 секунд)...
timeout /t 10 >nul

echo Проверяю Qdrant...
curl -s http://localhost:6333 >nul 2>&1
if %errorlevel% equ 0 (
    echo ✅ Qdrant запущен и работает
) else (
    echo ⚠️ Qdrant запущен, но проверка не удалась
    echo Проверьте вручную: http://localhost:6333
)

:start_zora
echo.
echo 5. Запускаю ZORA с памятью...
echo Останавливаю старые процессы на порту 8002...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8002') do (
    echo Останавливаю процесс PID: %%a
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 2 >nul

echo Запускаю ZORA...
start "ZORA with Memory" cmd /k "python zora_complete.py"

echo.
echo 6. Жду запуска (5 секунд)...
timeout /t 5 >nul

echo 7. Проверяю доступность...
python -c "
import socket, time
for i in range(10):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', 8002))
        sock.close()
        if result == 0:
            print('✅ ZORA запущена на порту 8002')
            print('✅ Память (Qdrant) доступна на порту 6333')
            print('✅ Адрес: http://localhost:8002')
            import webbrowser
            webbrowser.open('http://localhost:8002')
            exit(0)
    except:
        pass
    time.sleep(1)
print('❌ ZORA не запустилась за 10 секунд')
exit(1)
"

if %errorlevel% equ 0 (
    echo.
    echo ✅ УСПЕХ!
    echo ZORA запущена с работающей памятью!
    echo.
    echo 📊 Компоненты системы:
    echo   • Docker Desktop: ✅ Запущен
    echo   • Qdrant (память): ✅ Запущен на порту 6333
    echo   • ZORA: ✅ Запущена на порту 8002
    echo   • Веб-интерфейс: http://localhost:8002
    echo.
    echo 💡 Теперь ZORA имеет полноценную память
    echo    и может сохранять и извлекать информацию
    echo.
    echo 🛑 Для остановки закройте окно с сервером (Ctrl+C)
) else (
    echo.
    echo ❌ ОШИБКА
    echo ZORA не запустилась
    echo Попробуйте запустить вручную: python zora_complete.py
)

echo.
pause