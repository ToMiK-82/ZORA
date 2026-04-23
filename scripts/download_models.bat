@echo off
chcp 65001
echo ==========================================
echo    ZORA Model Downloader
echo ==========================================
echo.
echo [1/4] Qwen 2.5-Coder 14B...
ollama pull qwen2.5-coder:14b
echo [OK] Qwen загружен
echo.
echo [2/4] Nomic Embed...
ollama pull nomic-embed-text
echo [OK] Nomic загружен
echo.
echo [3/4] DeepSeek-R1 32B...
ollama pull deepseek-r1:32b
echo [OK] R1 загружен
echo.
echo [4/4] Llama 3.1 70B (долго!)...
ollama pull llama3.1:70b
echo [OK] Llama 70B загружен
echo.
echo ==========================================
echo    ВСЕ МОДЕЛИ ЗАГРУЖЕНЫ!
echo ==========================================
pause
