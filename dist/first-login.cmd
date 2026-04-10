@echo off
chcp 65001 >nul 2>&1
title Aurora AI Agency — Первый вход

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║     Aurora AI Agency — Настройка доступа        ║
echo  ╚══════════════════════════════════════════════════╝
echo.

:: Проверить, установлен ли Claude Code CLI
where claude >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Claude Code CLI не найден.
    echo.
    echo  Обратитесь к IT-администратору для установки.
    echo  Или установите самостоятельно:
    echo    npm install -g @anthropic-ai/claude-code
    echo.
    pause
    exit /b 1
)

:: Проверить, авторизован ли пользователь
claude auth status >nul 2>&1
if %errorlevel% equ 0 (
    echo  [OK] Вы уже авторизованы в Claude.
    echo.
    echo  Можете запустить Aurora AI Agency.
    echo.
    timeout /t 5
    exit /b 0
)

:: Не авторизован — запустить процесс
echo  Для работы с Aurora AI Agency необходимо войти
echo  в аккаунт Claude (подписка Pro или Team).
echo.
echo  Сейчас откроется браузер для входа.
echo  После успешного входа это окно закроется автоматически.
echo.
echo  Нажмите любую клавишу для продолжения...
pause >nul

echo.
echo  Запуск авторизации...
echo.
claude auth login

if %errorlevel% equ 0 (
    echo.
    echo  ╔══════════════════════════════════════════════════╗
    echo  ║     Готово! Авторизация прошла успешно.         ║
    echo  ║     Можете запустить Aurora AI Agency.          ║
    echo  ╚══════════════════════════════════════════════════╝
    echo.
) else (
    echo.
    echo  [!] Авторизация не завершена.
    echo  Попробуйте ещё раз или обратитесь к IT-администратору.
    echo.
)

timeout /t 10
