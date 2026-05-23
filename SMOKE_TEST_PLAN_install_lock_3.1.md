# Phase 3.1 Install-Lock Fix — Smoke Test Plan

> **STATUS: ✅ VERIFIED 2026-05-23 на EVO-X1.** GUI v1.2.0 → 2.1.0-rc1 + sidecar PID 62096→75192 + version 1.2.0→2.1.0-rc1 updated cleanly через manual NSIS installer launch с running v1.2.0. NSIS PREINSTALL hook visible в progress text. Tauri 2's default «App is running, click OK» dialog also appeared (defense-in-depth redundancy). License Ed25519 + Vault HKDF+AES-256-GCM работают post-update. **НИ ОДНОГО** «Error opening file for writing» dialog за весь install — main goal achieved. INV-49 promoted к `accepted`. Bug v1.2.0 silent install-skip — closed.



**Дата создания плана:** 2026-05-23
**Branch:** `fix/install-lock-3.1`
**HEAD:** `2dadd3a` (включает install-lock fix + audit hardening + cabinet sync)
**Tag для теста:** `v2.1.0-rc1-install-lock-3.1-audit`

## Цель smoke test

Проверить что install-lock fix реально работает на customer-side, и закрыть один из основных Антоновских pending gates перед коммерческим release v2.1.0.

**Что починили:**

| Что было | Что стало |
|---|---|
| `apply_update()` вызывала `process::exit(0)` без `stop_sidecar()` | После audit hardening: PowerShell `.status()` blocking → проверка UAC → если ОК → kill sidecar → exit |
| Sidecar orphaned держал `.pyd` locks | NSIS PREINSTALL hook убивает `econometrica-sidecar.exe` + `aurora-econometrica-gui.exe` + python.exe (с USERNAME filter) |
| User clicks UAC «Нет» → app dead (sidecar killed, installer not launched) | После audit hardening: UAC denial → return Err → sidecar остаётся жив → app продолжает работать |
| `[?]` placeholder в финальных комментариях клиента | (cabinet sync orthogonal — не тестируется здесь) |

## Шаг 1 — Pre-build verify

В терминале (PowerShell):

```powershell
cd D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica
git status
git branch --show-current
git rev-parse HEAD
```

**Ожидаемый результат:**
- Branch: `fix/install-lock-3.1`
- HEAD: `2dadd3ac71091c08e28334bd52d64a895c5c3a8c`
- Working tree clean

## Шаг 2 — Сборка инсталлятора

```powershell
$env:CARGO_TARGET_DIR = "D:/cargo-targets/ai-agency"
npm run tauri build
```

**Время сборки:** ~5-15 минут (зависит от кеша Cargo). Если cargo cache холодный — до 30 минут.

**Где будет установщик:**
```
D:\cargo-targets\ai-agency\release\bundle\nsis\Aurora AI Econometrica_2.1.0-rc1_x64-setup.exe
```

**Если build падает** — стоп здесь, скрин ошибки в чат, я разберусь.

## Шаг 3 — Подготовка тестовой среды

Для чистого теста обновления нужна предыдущая версия Эконометрики установлена. Варианты:

**Вариант A (самый чистый):** виртуальная машина с чистой Windows + установка предыдущей версии.

**Вариант B (быстрее):** на текущей машине:
1. Закрыть запущенную Эконометрику если работает
2. Скачать предыдущую версию инсталлятора с `Ackold26/aurora-releases` (например v1.2.0 или последнюю стабильную v2.0.x)
3. Установить — она перезапишет текущую установку
4. Запустить — убедиться что версия в Settings показывает предыдущую

**Если у тебя текущая версия 2.1.0-rc1 уже установлена** — пропусти, переходи к шагу 4 (тест будет «обновление текущей версии на ту же» — install-lock проявится одинаково).

## Шаг 4 — Тест #1: Happy path (обновление с принятием UAC)

**Что делаем:**
1. Запустить Эконометрику
2. Подождать пока sidecar полностью стартует (~5-10 сек, проверить в `%LOCALAPPDATA%\com.aurora.econometrica\sidecar.json` что есть pid + port)
3. В UI или через автоматическую проверку — запустить обновление (download_update + apply_update)
4. Когда появится UAC dialog — нажать **«Да»**
5. Смотреть что происходит

**Ожидаемый результат:**
- UI показывает «Installing...» или эквивалент
- В installer'е появляется текст `Preparing for update: stopping background processes...` (английский, ASCII — это намеренно после audit)
- Installer extracts files без «Error opening file for writing»
- После завершения — Эконометрика запускается с новой версией (2.1.0-rc1)
- В Settings версия = новая
- **КЛЮЧЕВОЕ:** Все компоненты обновились — особенно `.pyd` файлы в `_internal/`. Проверить:
  ```powershell
  # mtime файлов в installed location
  Get-ChildItem "C:\Program Files\Aurora AI Econometrica\sidecar\econometrica\_internal\*.pyd" | Select-Object Name, LastWriteTime
  ```
  Все `.pyd` должны иметь свежий timestamp (момент install), не старый.

**Что считается провалом:**
- В installer'е появляется dialog «Error opening file for writing... _internal\...\*.pyd» → fix не работает
- После install версия в Settings обновилась, но `.pyd` файлы старые (mtime до install) → silent skip — fix не работает
- Inflation UI отсутствует в Validate / brand auto-detect не срабатывает → silent functional gap (original v1.2.0 bug повторяется)

## Шаг 5 — Тест #2: UAC denial path (нажал «Нет» в UAC)

**Что делаем:**
1. Запустить установленную Эконометрику (после теста #1 — там новая 2.1.0-rc1)
2. Не закрывая — повторно trigger update flow (заставить app снова попытаться обновиться, например через manual trigger в settings или через скачивание того же installer'а)
3. Когда появится UAC dialog — нажать **«Нет»** (отказ)
4. Смотреть что происходит

**Ожидаемый результат:**
- В UpdateBlockingOverlay появляется error message (что-то типа «Installer launch failed (UAC denied or PowerShell error). App remains functional — please retry update.»)
- **Эконометрика ОСТАЁТСЯ ЖИВОЙ** — окно не закрывается, sidecar работает
- Можно продолжать работу в Эконометрике без перезапуска
- В `%LOCALAPPDATA%\com.aurora.econometrica\sidecar.json` — sidecar по-прежнему running, pid тот же

**Что считается провалом:**
- App закрылся после UAC denial (значит sidecar успели kill ДО PowerShell check — regression не починили)
- App продолжает крутиться, но sidecar мёртв (значит ordering неправильный)
- Error message не появляется в UI (silent fail — frontend не получает Err)

## Шаг 6 — Тест #3 (опционально): RDP multi-user

**Только если у тебя есть RDP server с двумя пользователями.** Иначе пропусти.

**Что делаем:**
1. User A logged into RDP, запускает Эконометрику
2. User B одновременно logged into RDP, запускает свой python.exe с window title «econometrica_test»
3. User A trigger update
4. После update — verify что User B's python.exe **НЕ был убит** (USERNAME filter работает)

**Ожидаемый результат:**
- User A's update проходит OK
- User B's python.exe всё ещё running после User A's update

## Что присылать после smoke test

В чат:
1. **Шаг прошёл / не прошёл** — по каждому тесту (Test #1, Test #2, Test #3 если делал)
2. **Если провал** — скриншоты ошибок + diagnostic logs:
   - `%APPDATA%\com.aurora.econometrica\logs\*.log` (последние строки)
   - Скрин error dialog из installer'a (если был)
   - mtime `.pyd` файлов (Get-ChildItem команда выше)
3. **Если success** — короткое подтверждение «оба теста ✅» и можно мержить PR install-lock в основную ветку

## Что я сделаю после твоих результатов

**Если success:**
- Создать PR `fix/install-lock-3.1` → `feat/v2.0.0-explicit-mode-wizard` (или master, по предпочтению)
- Promote INV-49 status: `proposed-pending-verification` → `accepted` в `aurora-meta/ENGINEERING_INVARIANTS.md`
- Tag v2.1.0-rc1 (drop install-lock-3.1 suffix) когда merged
- Обновить status.md tech-debt

**Если provals:**
- Phase 4 fix cycle — diagnose root cause + new commit на этой же branch
- Re-test cycle

## Время на твоей стороне

- Build: 5-30 min (один раз)
- Test #1: 5 min
- Test #2: 3 min
- Test #3 (опц.): 5 min
- **Всего:** 15-45 минут

## Контакт

Если что-то непонятно в шагах или странный ответ от installer'а — присылай в чат, я разберусь.
