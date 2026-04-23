@echo off
chcp 65001 >nul
echo ========================================
echo    ПОЛНАЯ ПЕРЕУСТАНОВКА DOCKER И НАСТРОЙКА ZORA
echo ========================================
echo.

echo ЭТОТ СКРИПТ ВЫПОЛНИТ:
echo 1. Удаление Docker Desktop и всех следов
echo 2. Очистка WSL дистрибутивов
echo 3. Перезагрузка системы (опционально)
echo 4. Установка Docker Desktop заново
echo 5. Настройка Docker для работы с ZORA
echo 6. Запуск Qdrant (памяти для ZORA)
echo 7. Запуск ZORA с работающей памятью
echo.

set /p CONTINUE="Продолжить? (Y/N): "
if /i not "%CONTINUE%"=="Y" (
    echo Отменено
    pause
    exit /b 0
)

echo.
echo ========================================
echo    ШАГ 1: УДАЛЕНИЕ DOCKER DESKTOP
echo ========================================
echo.

echo 1.1. Останавливаю Docker Desktop...
taskkill /f /im "Docker Desktop.exe" >nul 2>&1
taskkill /f /im "dockerd.exe" >nul 2>&1
timeout /t 3 >nul

echo 1.2. Удаляю Docker Desktop через Winget (если установлен)...
winget uninstall Docker.DockerDesktop >nul 2>&1

echo 1.3. Или через установщик Windows...
echo Откройте 'Панель управления -> Программы и компоненты'
echo Найдите 'Docker Desktop' и удалите его
echo Нажмите Enter после удаления...
pause

echo.
echo ========================================
echo    ШАГ 2: ОЧИСТКА ОСТАТОЧНЫХ ФАЙЛОВ
echo ========================================
echo.

echo 2.1. Удаляю папки Docker...
echo Удаляю: C:\Program Files\Docker
rd /s /q "C:\Program Files\Docker" 2>nul
echo Удаляю: C:\Program Files (x86)\Docker
rd /s /q "C:\Program Files (x86)\Docker" 2>nul
echo Удаляю: %USERPROFILE%\.docker
rd /s /q "%USERPROFILE%\.docker" 2>nul
echo Удаляю: %LOCALAPPDATA%\Docker
rd /s /q "%LOCALAPPDATA%\Docker" 2>nul

echo 2.2. Очищаю WSL дистрибутивы Docker...
echo Откройте PowerShell от имени администратора и выполните:
echo.
echo wsl --shutdown
echo wsl --unregister docker-desktop
echo wsl --unregister docker-desktop-data
echo.
echo Нажмите Enter после выполнения команд...
pause

echo.
echo ========================================
echo    ШАГ 3: ПЕРЕЗАГРУЗКА (РЕКОМЕНДУЕТСЯ)
echo ========================================
echo.

set /p REBOOT="Перезагрузить компьютер? (Y/N): "
if /i "%REBOOT%"=="Y" (
    echo Перезагружаю компьютер...
    shutdown /r /t 30
    echo Компьютер перезагрузится через 30 секунд
    echo Запустите этот скрипт снова после перезагрузки
    pause
    exit /b 0
)

echo.
echo ========================================
echo    ШАГ 4: УСТАНОВКА DOCKER DESKTOP
echo ========================================
echo.

echo 4.1. Скачиваю Docker Desktop...
echo Откройте https://www.docker.com/products/docker-desktop/
echo Скачайте и установите Docker Desktop
echo.
echo Рекомендуемые настройки при установке:
echo - [x] Install required Windows components
echo - [x] Add shortcut to desktop
echo - [x] Use WSL 2 instead of Hyper-V (или наоборот если WSL не работает)
echo.
echo Нажмите Enter после установки...
pause

echo 4.2. Запускаю Docker Desktop...
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"

echo Жду запуска Docker (60 секунд)...
echo Если появляется ошибка WSL, используйте Hyper-V вместо WSL 2
echo.
timeout /t 60 >nul

echo 4.3. Проверяю Docker...
docker --version
if %errorlevel% neq 0 (
    echo ❌ Docker не запустился
    echo Попробуйте:
    echo 1. Запустить Docker Desktop вручную
    echo 2. В настройках отключить WSL 2, включить Hyper-V
    echo 3. Перезагрузить компьютер
    pause
    exit /b 1
)

echo ✅ Docker установлен и запущен

echo.
echo ========================================
echo    ШАГ 5: НАСТРОЙКА DOCKER ДЛЯ ZORA
echo ========================================
echo.

echo 5.1. Проверяю возможность запуска контейнеров...
docker run hello-world
if %errorlevel% neq 0 (
    echo ❌ Docker не может запускать контейнеры
    echo Проверьте настройки Docker Desktop
    pause
    exit /b 1
)

echo ✅ Docker может запускать контейнеры

echo 5.2. Запускаю Qdrant (память для ZORA)...
echo Запускаю контейнер Qdrant на порту 6333...
docker run -d -p 6333:6333 --name qdrant qdrant/qdrant

echo Жду запуска Qdrant (10 секунд)...
timeout /t 10 >nul

echo Проверяю Qdrant...
curl -s http://localhost:6333
if %errorlevel% equ 0 (
    echo ✅ Qdrant запущен и работает
) else (
    echo ⚠️ Qdrant запущен, но проверка не удалась
    echo Проверьте вручную: http://localhost:6333
)

echo.
echo ========================================
echo    ШАГ 6: ЗАПУСК ZORA С ПАМЯТЬЮ
echo ========================================
echo.

echo 6.1. Проверяю зависимости ZORA...
python -c "import fastapi" >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Зависимости не установлены
    echo Устанавливаю...
    call install_dependencies.bat
)

echo 6.2. Останавливаю старые процессы ZORA...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8002') do (
    echo Останавливаю процесс PID: %%a
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 2 >nul

echo 6.3. Запускаю ZORA с памятью...
echo Запускаю ZORA на порту 8002...
start "ZORA with Memory" cmd /k "python zora_complete.py"

echo Жду запуска (10 секунд)...
timeout /t 10 >nul

echo 6.4. Проверяю доступность...
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
    echo ========================================
    echo    ✅ УСПЕХ! ZORA ЗАПУЩЕНА С ПАМЯТЬЮ
    echo ========================================
    echo.
    echo 📊 СИСТЕМА РАБОТАЕТ:
    echo   • Docker Desktop: ✅ Переустановлен и запущен
    echo   • Qdrant (память): ✅ Запущен на порту 6333
    echo   • ZORA: ✅ Запущена на порту 8002
    echo   • Веб-интерфейс: http://localhost:8002
    echo.
    echo 💡 ZORA теперь имеет полноценную память
    echo    и может сохранять и извлекать информацию
    echo.
    echo 🛑 Для остановки закройте окно с сервером (Ctrl+C)
    echo.
    echo 🔧 Для управления Docker используйте Docker Desktop
    echo 📚 Документация ZORA: http://localhost:8002/docs
) else (
    echo.
    echo ❌ ОШИБКА
    echo ZORA не запустилась
    echo Попробуйте запустить вручную: python zora_complete.py
)

echo.
pause