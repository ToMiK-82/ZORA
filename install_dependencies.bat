@echo off
chcp 65001 >nul
echo ========================================
echo    УСТАНОВКА ЗАВИСИМОСТЕЙ ZORA
echo ========================================
echo.

echo 1. Проверяю Python...
python --version
if %errorlevel% neq 0 (
    echo ❌ Python не найден
    echo Установите Python 3.8+ с https://www.python.org/
    pause
    exit /b 1
)

echo 2. Проверяю pip...
pip --version
if %errorlevel% neq 0 (
    echo ❌ pip не найден
    echo Установите pip: python -m ensurepip --upgrade
    pause
    exit /b 1
)

echo 3. Устанавливаю основные зависимости...
echo.
pip install fastapi uvicorn python-dotenv requests pydantic

echo 4. Устанавливаю дополнительные зависимости...
echo.
pip install jinja2 aiofiles python-multipart

echo 5. Проверяю установку...
echo.
python -c "import fastapi; print('✅ FastAPI установлен')"
python -c "import uvicorn; print('✅ Uvicorn установлен')"
python -c "import jinja2; print('✅ Jinja2 установлен')"

echo.
echo ✅ Все зависимости установлены!
echo.
echo Теперь можно запустить ZORA:
echo   .\start_zora_with_docker.bat
echo   или
echo   python zora_complete.py
echo.
pause