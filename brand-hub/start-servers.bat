@echo off
:: Aurora AI Creative Hub — запуск Python-серверов
:: RAG Server (порт 7420) + Parser (порт 7421)

set SCRIPT_DIR=%~dp0

echo Запуск RAG Server (порт 7420)...
start "Aurora RAG Server" cmd /k "cd /d %SCRIPT_DIR%rag-server && python server.py"

timeout /t 2 /nobreak > nul

echo Запуск Parser Server (порт 7421)...
start "Aurora Parser Server" cmd /k "cd /d %SCRIPT_DIR%parser && python server.py"

echo.
echo Серверы запускаются. Подождите 5-10 секунд перед использованием RAG/Parser функций.
