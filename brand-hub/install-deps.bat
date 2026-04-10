@echo off
:: Aurora AI Creative Hub — установка зависимостей Python

set SCRIPT_DIR=%~dp0

echo Установка зависимостей RAG Server...
pip install -r "%SCRIPT_DIR%rag-server\requirements.txt"

echo.
echo Установка зависимостей Parser...
pip install -r "%SCRIPT_DIR%parser\requirements.txt"

echo.
echo Готово. Запустите start-servers.bat для старта серверов.
pause
