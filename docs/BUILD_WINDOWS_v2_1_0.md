# Сборка Windows-установщика — Aurora MMM Optimizer v2.1.0

> **Цикл:** v2.1.0, Партия 5
> **Цель:** Получить установочный пакет для прямых продаж 50-100 клиентам на Windows 10/11.
> **Формат:** NSIS installer (.exe), цифровая подпись EV Code Signing (когда ООО оформлено).

---

## Контрольный список перед сборкой

- [x] Версия в `package.json` — `2.1.0-rc1`
- [x] Версия в `src-tauri/Cargo.toml` — `2.1.0-rc1`
- [x] Версия в `src-tauri/tauri.conf.json` — `2.1.0-rc1`
- [ ] PyInstaller sidecar spec проверен — все runtime зависимости включены
- [ ] Sidecar бинарь собран и протестирован отдельно (`python build_sidecar.py`)
- [ ] Иконки в `src-tauri/icons/` присутствуют: `32x32.png`, `128x128.png`, `128x128@2x.png`, `icon.icns`, `icon.ico`
- [ ] Все sidecar файлы перечислены в `tauri.conf.json::bundle.resources`
- [ ] Content packs (`content-packs/`) перечислены в resources
- [ ] `npm run check` — нет блокирующих ошибок (кроме pre-existing test-only)
- [ ] `npm test` — все тесты проходят
- [ ] `cd sidecar/econometrica && python -m pytest tests/` — все тесты проходят

---

## Команда сборки

```powershell
# Из корня репозитория
$env:CARGO_TARGET_DIR = "D:\cargo-targets\aurora-econometrica"
npm run tauri build
```

Результат:
- `$env:CARGO_TARGET_DIR\release\bundle\nsis\Aurora.AI.Econometrica_2.1.0-rc1_x64-setup.exe`
- Размер ожидается 80-200 MB (зависит от Python sidecar и embedded моделей)

---

## Цифровая подпись

### Сейчас (2026-05-16)

ООО не оформлено → EV Code Signing сертификата нет.

Установщик собирается **без** цифровой подписи. Антивирусы (особенно Windows Defender SmartScreen) будут показывать предупреждение «неизвестный издатель». Это известное ограничение пилотной фазы.

Для смягчения:
- В письме клиенту прилагать инструкцию «как разрешить запуск неподписанного установщика»
- Сборка проходит smoke-test self-signed через скрипт (см. ниже)

### Когда ООО будет оформлено

1. Получить EV Code Signing сертификат через аккредитованный CA (Certum, GlobalSign, SSL.com)
2. Установить сертификат в Windows certificate store (LocalMachine\My)
3. Извлечь SHA-1 thumbprint:
   ```powershell
   Get-ChildItem -Path Cert:\LocalMachine\My | Where-Object { $_.Subject -like "*Aurora*" }
   ```
4. Задать переменную окружения:
   ```powershell
   $env:SIGNING_CERT_THUMBPRINT = "<SHA-1 thumbprint>"
   ```
5. Подписать установщик:
   ```powershell
   .\scripts\build\sign_installer.ps1 -InstallerPath <path-to-installer.exe>
   ```

### Проверка инфраструктуры без сертификата

```powershell
# Dry run — показывает signtool команду без выполнения
.\scripts\build\sign_installer.ps1 -InstallerPath <path> -DryRun

# Self-signed smoke test — проверяет что signtool найден и работает
.\scripts\build\sign_installer.ps1 -InstallerPath <path> -UseSelfSigned
```

---

## Тестовая установка на чистый Windows 10/11

Цель — установить на компьютер где **никогда** не было Aurora и Python, проверить полный путь до результата.

### Перед установкой

- Создать виртуальную машину Windows 10 21H2 или Windows 11 23H2
- Снять snapshot **до** установки (для возможности повтора)
- Отключить интернет в VM (проверка что приложение работает offline)
- В Windows Defender отключить cloud-based protection (иначе предупреждение замедлит проверку)

### Установка

1. Скопировать установщик в VM (через shared folder или drag-drop)
2. Запустить .exe
3. Smartscreen: «Запустить всё равно» (для неподписанного)
4. Принять путь установки по умолчанию (`C:\Program Files\Aurora AI Econometrica`)
5. Подождать завершения установки (ожидается 30-60 сек)
6. Запустить приложение из стартового меню

### Проверки на чистом Windows

- [ ] Приложение запускается без ошибок «vcredist not found», «Python missing»
- [ ] Главный экран показывается, локализация русская
- [ ] Кнопка «Новый проект» работает
- [ ] Загрузка тестового файла (Кагоцел РФ+ Excel) проходит
- [ ] Автоопределение каналов отрабатывает
- [ ] Помощник проходит все 6 шагов
- [ ] Запуск модели проходит, не падает
- [ ] Результаты отображаются (декомпозиция, рекомендации)
- [ ] Сохранение проекта работает, файл создаётся в `%APPDATA%\aurora-econometrica-gui\projects\`
- [ ] Закрытие + повторное открытие приложения восстанавливает проект
- [ ] Видна версия 2.1.0-rc1 в Settings → About

### После проверки

- Сохранить лог установки и runtime (если что-то не так)
- Сделать скриншоты ключевых экранов для лендинга
- Восстановить snapshot VM для повторных тестов

---

## Известные ограничения v2.1.0-rc1

- **Без цифровой подписи** — Windows SmartScreen покажет предупреждение
- **Только русский язык** — английский в backlog v2.2.0
- **Только Windows** — macOS / Linux в backlog v2.2.0
- **Однопользовательский режим** — многопользовательский в backlog v2.2.0

---

## Roadmap к v2.1.0 stable (после rc1)

1. Пилотный тест Антона (Кагоцел РФ+ от начала до конца) — Партия 1
2. Тестовая установка на чистый Windows 10 и 11 (см. выше)
3. Получение фидбека от 3-5 пилотных клиентов
4. Исправление найденных ошибок → rc2 или сразу stable
5. Получение EV сертификата от ООО → подпись stable
6. Tag `v2.1.0` + публикация на auroraai.pro
7. Прямые продажи 50-100 клиентам

---

## Связанные документы

- `docs/MASTER_PLAN_v2_1_0.md` — общий план цикла
- `docs/AURORAMODEL_FORMAT.md` — формат сохранения моделей (новый, безопасный)
- `docs/USER_GUIDE_v2_1_0.md` — руководство пользователя
- `docs/VIDEO_DEMO_5MIN_SCRIPT.md` — сценарий видео-демо
- `scripts/build/sign_installer.ps1` — wrapper для цифровой подписи
- `sidecar/econometrica/build_sidecar.py` — сборка Python sidecar
