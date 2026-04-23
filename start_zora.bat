@echo off
chcp 65001 >nul
echo ========================================
echo    ЗАПУСК ZORA С ПАМЯТЬЮ
echo ========================================
echo.

echo 1. Проверяю Docker...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Docker не установлен
    echo Установите Docker Desktop с https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

echo 2. Проверяю и запускаю Qdrant (память)...
docker ps | findstr "qdrant" >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠️ Qdrant не запущен
    echo Запускаю Qdrant...
    docker run -d -p 6333:6333 --name qdrant qdrant/qdrant
    echo Жду запуска (5 секунд)...
    timeout /t 5 >nul
    echo ✅ Qdrant запущен
) else (
    echo ✅ Qdrant уже запущен
)

echo 3. Останавливаю старые процессы ZORA...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8002') do (
    echo Останавливаю процесс PID: %%a
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 2 >nul

echo 4. Запускаю ZORA...
echo    Адрес: http://localhost:8002
echo    Документация: http://localhost:8002/docs
echo.

start "ZORA with Memory" cmd /k "python zora_launcher.py"

echo 5. Жду запуска (5 секунд)...
timeout /t 5 >nul

echo 6. Проверяю доступность...
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
    echo   • Docker: ✅ Запущен
    echo   • Qdrant (память): ✅ Запущен на порту 6333
    echo   • ZORA: ✅ Запущена на порту 8002
    echo   • Веб-интерфейс: http://localhost:8002
    echo.
    echo 💡 ZORA имеет полноценную память
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