# Кросс-продуктовая проверка антивирусного дефекта — 2026-08-13

Разведка: живёт ли в других продуктах Авроры та же пара паттернов, из-за которых Kaspersky снял
Econometrica с диска 11.08.2026 (`PDM:Trojan.Win32.Generic`, поведенческий). Только чтение
(`grep` + `git log`), ничего не менялось. Эталон исправления — запись `ea560be` в
`Aurora_Econometrica_thinwt`.

**Дефект A** — `icacls ... /inheritance:r /grant:r <user>:(OI)(CI)F` при инициализации сессии:
`/grant:r` ЗАМЕНЯЕТ список прав, снимая SYSTEM/Администраторы, прямо перед шифрованием файлов в
том же каталоге — читается как подготовка шифровальщика.

**Дефект Б** — `netstat -ano | findstr :порт` (или прямой `netstat -ano -p TCP` с разбором) →
`taskkill /PID /F` — разведка процессов по порту с последующим снятием найденного.

Метод проверки: искал не только буквальный `Command::new("icacls"/"netstat")`, но и обёртки
(`crate::proc::hidden("icacls")` у DocMaster/Smart Analytica) — иначе дефект прячется за
рефакторингом вызова. Различал реальный вызов и упоминание в комментарии/doc-строке по контексту
каждого совпадения вручную.

## Таблица

Рабочие копии одного продукта (`_wt_*`, `*_archive_*`, ветки одного `.git`) сведены в одну строку
продукта; список веток и их индивидуальные версии — в примечании под таблицей.

| Продукт | Путь дерева (репрезентативный) | Версия (осн. ветка) | Дефект A | Дефект Б | При старте | Последняя запись (реп.) |
|---|---|---|---|---|---|---|
| **Econometrica** | `Dev/Aurora_Econometrica` (репо; thinwt = worktree) | 2.4.8 (thinwt/master) | ЕСТЬ на всех ветках КРОМЕ thinwt/master `session/manager.rs:46` `Command::new("icacls")` /grant:r /inheritance:r | ЕСТЬ на всех ветках КРОМЕ thinwt/master `econ_sidecar.rs:222-223` `cmd /C "netstat -ano -p tcp \| findstr :{port}"` | да (SessionManager::new при старте; kill_on_port при остановке зависшего движка) | 2026-08-13 (thinwt) |
| **Oracle** | `Dev/Aurora_Oracle` (репо; 8 worktree) | 0.4.6 (_wt_oracle_gwsign) | ЕСТЬ, все ветки `session/manager.rs:46` идентично Econometrica-паттерну | нет | да | 2026-08-13 (_wt_oracle_gwsign) |
| **Legal Center** | `Dev/ROSST_AI_Legal` (репо; commercial+3 worktree) | 0.13.2 (master/commercial) | ЕСТЬ, все ветки `session/manager.rs` тот же паттерн | ЕСТЬ на ветках commercial/gwsign/master (НЕТ на базовой ветке `fix/updater-path-traversal`) `commands/bridge.rs:146,187` `netstat -ano -p TCP` + `taskkill /F /PID` (без findstr, парсит вывод сам) | да (manager при старте; bridge.rs — `ensure_gateway_running`, вызывается при старте) | 2026-08-13 |
| **Creative Center (Hub)** | `Dev/Aurora_Creative_Hub` (репо; 2 worktree) | 0.10.0 (master) | ЕСТЬ, все ветки `session/manager.rs` тот же паттерн | нет | да | 2026-08-13 |
| **PR Master (PR Studio)** | `Dev/Aurora_PR_Master` (+1 worktree) | 0.8.5 | ЕСТЬ `session/manager.rs` тот же паттерн | нет | да | 2026-08-08 |
| **Media Radar (Parser)** | `Dev/Aurora_Parser` (+1 worktree) | 1.0.0 | ЕСТЬ `session/manager.rs` тот же паттерн | нет | да | 2026-07-30 |
| **Smart Analytica** | `Dev/ROSST_AI_Media` (репо; 3 worktree, наименование папки "Media" — вводит в заблуждение, productName="Aurora AI Smart Analytica") | 1.3.13 (master) | ЕСТЬ через обёртку `crate::proc::hidden("icacls")` — `session/manager.rs:103-109`, аргументы `/grant:r ... /inheritance:r` идентичны | ЕСТЬ, два независимых места: `parser_sidecar.rs:191-209` и `rag_sidecar.rs:203-221`, `cmd /C netstat...findstr:port` → `kill_on_port` | да (`kill_on_port` вызывается из `start()` при запуске sidecar и из `ensure_alive()`/watchdog) | 2026-08-13 |
| **Docs Lab (DocMaster)** | `Dev/ROSST_AI_DocMaster` (репо; 2 worktree) | 0.12.1 (feat/rag-core-adopt) | ЕСТЬ через ту же обёртку `crate::proc::hidden("icacls")` — `session/manager.rs:103-109` | ЕСТЬ, ТРИ места: `parser_sidecar.rs:191-209`, `rag_sidecar.rs:203-221`, `commands/bridge.rs:146,187` | да (те же точки вызова, что у Smart Analytica; bridge.rs — `ensure_gateway_running` при старте) | 2026-08-13 |
| **AI Agency** (общий шаблон, не входит в 12 продуктов PORTFOLIO) | `Dev/AI_APP_AGENCY` | 0.8.6 | ЕСТЬ `session/manager.rs:50` `match std::process::Command::new("icacls")` тот же паттерн | нет | да | 2026-07-24 |
| **Aurora Data Studio** | `Aurora Data Studio/studio_ui` | 1.0.1 | нет (нет `session/manager.rs`, нет `icacls` вообще) | нет | — | 2026-05-30 (заброшена?) |
| **Launch** | `Aurora Launch` | 0.2.5 | нет — `commands/methodology_cert.rs:365` упоминает icacls только в TODO-комментарии («Future hardening»), реального вызова нет | нет | — | 2026-07-30 |
| **thin-client (Platform Core шаблон)** | `thin-client/app`, `aurora-platform-core*`, `_canon-ssot-v2` | 0.1.0 | нет (cookiecutter-заготовка, без `session/manager.rs`) | нет | — | не проверялась (заготовка) |

### Ветки/worktree по продуктам (не раздувая таблицу выше)
- **Econometrica** (`Dev/Aurora_Econometrica/.git`): `Aurora_Econometrica`(feat/econ-kpi-units, 2.2.0, 17.07) — дефект A+Б; `thinwt`(master, 2.4.8, 13.08) — **исправлено**; `avrora`(2.2.0, 12.07) — A+Б; `canon`(feat/econ-canon-p0, 2.4.5, 10.08) — A+Б; `v230`(2.4.0, 30.07) — A+Б; `_wt_econ_gwsign`(2.4.4, 09.08) — A+Б; `_wt_transport_econ`(2.4.0, 26.07) — A+Б. Отдельно `Aurora_Econometrica_archive_2026-05-09` — самостоятельный старый клон (1.2.0, 04.05) — A+Б, заброшен.
- **Oracle** (`Dev/Aurora_Oracle/.git`): 8 веток/worktree (bridge-msg, bridgefix, cloud, fix042, pptx-manhattan, unified, _wt_oracle_gwsign, _wt_oracle_master) — везде дефект A, версии 0.3.2–0.4.6, последние записи 06.06–13.08. `Oracle-r2` — путь есть, но `git branch`/`git log` не отвечают (возможно повреждён/не worktree в строгом смысле — не проверено).
- **Legal** (`Dev/ROSST_AI_Legal/.git`): база (fix/updater-path-traversal, 0.8.8, 03.08), `ROSST_AI_Legal_commercial`(0.13.2,13.08), `_wt_legal_gwsign`(0.13.0,09.08), `_wt_legal_master`(0.13.2,13.08), `_wt_transport_legal`(0.8.8,26.07). Отдельно заброшенный `_wt_legal_mbpoc` (root, ветка model_backend_poc, 27.06) — дефект A через прямой `Command::new`.
- **Docs Lab**: база (feat/rag-core-adopt, 0.12.1, 13.08), `_wt_docslab_cpd44`(0.10.5,03.08), `_wt_transport_docslab`(0.10.5,26.07). Отдельно заброшенный `_wt_docmaster_mbpoc` (root, 27.06) — дефект A через прямой `Command::new` (другая реализация, не через `proc::hidden`).
- **Smart Analytica** (тот же `.git`, что и Media Radar — `Dev/ROSST_AI_Media`): `_wt_analytica_cloud`(1.3.11,09.08), `_wt_sa_gwsign`(1.3.11,09.08), `_wt_transport_analytica`(1.3.11,26.07).
- **Creative Hub**: `_wt_ch_cloud`(0.9.9,09.08), `_wt_ch_gwsign`(0.9.9,09.08).
- **PR Studio**: `_wt_prstudio_cpd44`(0.8.5,03.08).
- **Media Radar**: `_wt_transport_radar`(1.0.0,26.07).

## Итоговые числа

- Просмотрено деревьев с `src-tauri/src`: **54** (37 в `Dev`, 17 вне `Dev`, включая 4 cookiecutter-шаблона `{{cookiecutter.app_id}}` без реального продукта).
- Продуктов (репозиториев) затронуто Дефектом A: **9 из 11** проверенных Tauri-продуктов — Econometrica (частично, кроме thinwt/master), Oracle, Legal Center, Creative Center, PR Studio, Media Radar, Smart Analytica, Docs Lab, AI Agency. Не затронуты: Aurora Data Studio, Launch.
- Продуктов затронуто Дефектом Б: **4** — Econometrica (частично, кроме thinwt/master), Smart Analytica, Docs Lab, Legal Center (только на ветках commercial/gwsign/master). У Smart Analytica и Docs Lab — по 2-3 независимых места одновременно (не одно на продукт, как у Econometrica).
- Продукт, где фикс уже применён: **только Econometrica/thinwt** (ветка `master`, коммит `ea560be`, 12.08.2026). Ни в одной другой ветке того же репозитория Econometrica, ни в одном другом продукте фикс не распространён.

## Прочие порождения консольных утилит при старте (item 3)

- `tasklist` в `sidecar_runtime.rs` (Econometrica) и `port_discovery.rs` (Smart Analytica/DocMaster) — **безобидно**: позитивная проверка имени процесса, вызывается ТОЛЬКО когда владелец уже совпал с текущим пользователем, ничего не убивает. Комментарий в коде прямо отмечает «не для trusted decisions».
- `powershell` в `commands/updater.rs` (все продукты) — **безобидно для этого разбора**: запуск инсталлятора обновления с elevation, срабатывает по действию пользователя (клик «обновить»), не при обычном старте.
- `powershell` в `commands/critic_processor.rs` (Smart Analytica) — **безобидно**: рендер слайдов через PowerPoint COM (`render_slides.ps1`), функциональность обработки презентации, не связано с правами/процессами.
- `icacls` в doc-комментариях `lib.rs` (Creative Hub, `_wt_ch_*`) и `proc.rs` (DocMaster) — просто перечисление примеров консольных утилит в объяснении обёртки `CREATE_NO_WINDOW`, реального вызова нет.
- `icacls` в `Aurora Launch/commands/methodology_cert.rs:365` — TODO-комментарий («Future hardening: invoke icacls subprocess»), реального вызова нет.
- `wmic`, `reg`, `netsh`, `sc`, `schtasks` — не встретились ни в одном проверенном дереве.

## 🔴 Чего проверить не смог

- **Не смотрел живые бинарники/установленные копии у клиентов** — только исходники в рабочем дереве, как и требовало задание (только чтение, без сборки). Не знаю, какая версия кода реально стоит на машинах клиентов для каждого продукта (кроме Econometrica, где это отслежено в памяти — клиенты на 2.4.4).
- **`Oracle-r2`** — путь существует, но `git branch --show-current` и `git log` не вернули данных (пустой вывод без ошибки) — не разобрался, это неинициализированный worktree, повреждённый `.git`-линк или что-то ещё; не включён в подсчёт затронутых веток.
- **Не проверял ветки `.claude/worktrees/agent-*`** внутри `Aurora_Econometrica` и `ROSST_AI_Media` (временные ветки Claude Code, 5 штук) — увидел их в первом grep-проходе, дальше не разбирал: похоже на эфемерные агентские сессии, не рабочие копии продукта.
- **Не проверял `_sync_family_backup_2026-06-03/ROSST_AI_Creative`** (бэкап-копия, не рабочее дерево) и Python/не-Tauri части продуктов (`aurora-llm`, `brand-hub`, `AI_APP_AGENCY`-бэкенд без Tauri, `Aurora_Analytics_Suite/landing`, `Aurora_Econometrica_Trade_and_Pricing`, `aurora-econometrica-brand-tracker`) — у них нет `src-tauri`, задание касалось Rust/Tauri-кода, но если у них есть свои консольные вызовы вне Tauri — не проверено.
- **Не смотрел, действительно ли `session/manager.rs` = буквально идентичный скопированный файл** во всех 9 продуктах (не сравнивал побайтово/diff) — сравнивал по контексту грепа и одному полному чтению (Oracle). Для Smart Analytica/DocMaster подтвердил, что это ДРУГАЯ реализация (обёртка + таймаут), для остальных 7 — предполагаю идентичность по совпадающим строкам кода и комментарию `V62`, не проверял построчно каждый файл.
- **Не проверял `Aurora Data Studio`/`Launch`/`thin-client` на Дефект Б** отдельным полным чтением каждого файла — полагался на comprehensive grep по `netstat|findstr` в `src-tauri/src`, который не дал совпадений; ложноотрицательный сценарий (обёртка под другим именем, как у DocMaster с icacls) не исключён полностью.
