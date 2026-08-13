# Разведка выпускных веток — 2026-08-13

Только чтение (`git tag`, `git branch --contains`, `git for-each-ref`, `git status --porcelain`,
`git rev-list --left-right --count`, чтение `tauri.conf.json` и `manager.rs`). Ни одна ветка не
переключена, ни одного `checkout`/`pull`/`push`/`stash`/`merge` не выполнялось.

## Таблица по продуктам

| Продукт | Выпускная ветка | Основание | Версия в tauri.conf.json (на текущем checkout) | Последняя метка | Ветка checkout дерева | Незаписанных файлов | icacls: файл:строка |
|---|---|---|---|---|---|---|---|
| Oracle | 🔴 не master — `feat/oracle-install-per-user` (кандидат) | метка `v0.4.5-oracle` (10.08) лежит в `feat/oracle-install-per-user` и `fix/oracle-gw-sign-prefix`, НЕ в master; эта ветка и самая активная (13.08) | 0.4.2 (на checkout `feat/oracle-report-hygiene`, НЕ на ветке с меткой) | v0.4.5-oracle, 2026-08-10 | `feat/oracle-report-hygiene` | 10 | `manager.rs:46,47,56,58,60,62` (прямой `Command::new("icacls")`) |
| Legal Center | **master** | метка `v0.13.2-legal` лежит и в master, и в `feat/legal-commercial-readiness`; master активнее всех (коммит 13.08, тот же день) | 0.8.8 (на checkout `fix/updater-path-traversal`, ветка на 433 коммита позади master — не показательно) | v0.13.2-legal, 2026-08-10 | `fix/updater-path-traversal` | 6 | `manager.rs:46,56,58` |
| Creative Center | **master** | метка `v0.10.0-creative-center` лежит только в master; master и есть текущий checkout; master...HEAD = 0/0 | 0.10.0 (совпадает с меткой) | v0.10.0-creative-center, 2026-08-10 | `master` | 89 | `manager.rs:114,115,121,122,125,127` |
| PR Studio | 🔴 неопределимо однозначно — см. раздел ниже | версийных меток продукта нет вообще (только общие «canon»-метки на несколько продуктов); master не двигался с 06.06, реальная работа идёт в feature-ветках | 0.8.5 | `crisis-refactor-2026-06-27` (общая, не про версию PR Studio), 2026-06-27 | `fix/updater-is-newer-prerelease` | 16 | `manager.rs:103,113,115` |
| Media Radar | ⚠️ вероятно master, но с оговоркой | метка `v1.0.0-mcp-bridge-dev` лежит и в master, и в 3 feature-ветках; но версия в конфиге (1.0.0) резко расходится с известной клиентской 1.3.5 — версийные метки продукта, похоже, перестали создаваться после 1.0.x | 1.0.0 (⚠️ не совпадает с памятью о клиентской 1.3.5) | v1.0.0-mcp-bridge-dev, 2026-06-03 | `fix/updater-is-newer-prerelease` | 5 | `manager.rs:46,56,58` |
| AI Agency | 🔴 неопределимо однозначно — см. раздел ниже | версийных меток продукта нет (только общие «canon»-метки); master не двигался с 26.06, метка лежит только в текущей feature-ветке | 0.8.6 | `crisis-refactor-2026-06-27` (общая), 2026-06-27 | `feat/contract-vs-standard` | 9 | `manager.rs:50,60,62` |
| Smart Analytica | **master** (высокая уверенность) | метка `v1.3.13-analytics-hub` лежит только в master; master = текущий checkout, самый активный (коммит сегодня, 13.08); версия конфига совпадает с меткой | 1.3.13 (совпадает с меткой) | v1.3.13-analytics-hub, 2026-08-10 | `master` | 37 (⚠️ живая сессия правит прямо сейчас — по маячку задачи) | `manager.rs:103,104,113,115,118,120` |
| Docs Lab | 🔴 не master — `feat/rag-core-adopt` (высокая уверенность) | метка `v0.12.1-docs-lab` (13.08, СЕГОДНЯ) лежит ТОЛЬКО в `feat/rag-core-adopt`; версия конфига (0.12.1) совпадает с меткой и с памятью «0.12.1 у клиентов (13.08)»; master отстаёт на 31 коммит и последний раз двигался 09.08 | 0.12.1 (совпадает с меткой и с памятью о клиентской версии) | v0.12.1-docs-lab, 2026-08-13 | `feat/rag-core-adopt` | 30 | `manager.rs:103` — обёрнут `crate::proc::hidden("icacls")`, голого слова "icacls" в вызове нет (только в строке-литерале аргумента) |

## Развёрнутые факты по продукту

### Oracle (`Aurora_Oracle`)
- Метки (топ-5 по дате создания): `v0.4.5-oracle` (10.08 10:08), далее серия `backup/2026-08-04/*` (backup-метки, не релизные).
- `git branch -a --contains v0.4.5-oracle`: `feat/oracle-install-per-user` (+), `fix/oracle-gw-sign-prefix`, и их remotes. **master в списке отсутствует.**
- Активность веток (топ-4): `feat/oracle-install-per-user` 13.08, `fix/oracle-gw-sign-prefix` 10.08, `integration/oracle-unified` 08.08, `master` 08.08.
- Текущий checkout дерева — `feat/oracle-report-hygiene` (третья ветка, не входит даже в топ-4 активности и не содержит метку). `master...HEAD`: 141 коммитов только в master, 0 только в HEAD — то есть checkout сильно позади master, а master сам ещё позади ветки с меткой.
- Вывод: реальный выпуск (последняя метка + сборка 0.4.2 по памяти) собирался НЕ с master, а с `feat/oracle-install-per-user` или соседней `fix/oracle-gw-sign-prefix`. Это ветка-кандидат для CPD-77, а не master.

### Legal Center (`ROSST_AI_Legal`)
- Метки: `v0.13.2-legal` (10.08), `v0.12.2-legal` (30.07), `v0.12.1-legal` (26.07) — чистая версийная последовательность.
- `--contains v0.13.2-legal`: `archive/legal-master-before-merge-2026-08-10`, `archive/legal-readiness-2026-08-10`, `feat/legal-commercial-readiness` (+), **`master` (+)**.
- Активность: `feat/legal-commercial-readiness` и `master` — оба 13.08 (сегодня, судя по всему параллельная работа).
- Checkout дерева стоит на `fix/updater-path-traversal` — старая ветка, 433 коммита позади master, версия конфига там 0.8.8 (не показательна для релиза).
- Вывод: master — выпускная ветка, уверенно (метка + активность + согласуется с записью в MEMORY «Legal (13.08): четвёртый круг аудита закрыт»).

### Creative Center (`Aurora_Creative_Hub`)
- Метка `v0.10.0-creative-center` (10.08) лежит только в master; checkout дерева и есть master.
- Активность: master 13.08 (самая свежая), дальше `fix/ch-gw-sign-prefix` и `feat/ch-cloud-module` (09.08).
- 89 незаписанных файлов на master — существенный объём правок в рабочем дереве прямо сейчас; сами файлы не перечисляла, только количество.
- Вывод: master — выпускная ветка, уверенно.

### PR Studio (`Aurora_PR_Master`)
- Метки — НЕ версийные для продукта: `crisis-refactor-2026-06-27`, `crisis-canon-2026-06-27`, `copywriter-canon-2026-06-26`, `v-commstrat-canon`, `v-model-alias-effort-fix` (06.06). Это общие «canon»-метки, встречающиеся и в других деревьях (та же `crisis-refactor-2026-06-27` — топ-метка и в AI Agency). Собственных релизных меток вида `v0.8.x-prstudio` в топ-5 нет.
- `--contains crisis-refactor-2026-06-27`: только `fix/updater-is-newer-prerelease` (текущий checkout).
- Активность: `fix/updater-is-newer-prerelease` 08.08, `fix/prstudio-cpd44-resume-fallback` 03.08, `feat/sec1-auth-sig` 19.07, **`master` 06.06** — master не двигался больше двух месяцев.
- `master...HEAD`: 0 коммитов только в master, 31 только в HEAD — текущая ветка полностью включает master и на 31 коммит впереди.
- Вывод: однозначно определить нельзя. Master протух (06.06) и явно не используется для сборки. Кандидаты — `fix/updater-is-newer-prerelease` (самая активная и текущая) либо `fix/prstudio-cpd44-resume-fallback`. Без продуктовых версийных меток невозможно подтвердить, какая из feature-веток реально уходила в сборку клиенту.

### Media Radar (`Aurora_Parser`)
- Метки: `v1.0.0-mcp-bridge-dev` (03.06), `v1.0.0` (29.05), `v1.0.0-sidecar-bootability-fix`, `v1.0.0-help-update` (14.04) — все старые, с мая-июня.
- `--contains v1.0.0-mcp-bridge-dev`: `feat/sec1-auth-sig`, `fix/radar-resilient-download` (+), `fix/updater-is-newer-prerelease` (*, текущий), **`master`**.
- Активность: `fix/updater-is-newer-prerelease` 30.07, `master` 28.07, `fix/radar-resilient-download` 26.07, `feat/sec1-auth-sig` 19.07.
- ⚠️ Версия в `tauri.conf.json` на текущем checkout — `1.0.0`, тогда как по памяти (ядро MEMORY) у клиентов установлена **Media Radar 1.3.5**. Это большое расхождение — либо версийные метки для Media Radar перестали создаваться после 1.0.x и версия росла без тегирования, либо номер в конфиге на этой конкретной feature-ветке не актуален.
- Вывод: master технически содержит последнюю найденную метку и является второй по активности, поэтому осторожно предполагаю его выпускной, но с оговоркой: **раз номер версии в конфиге не бьётся с известной клиентской версией, нужна дополнительная проверка (например, поиск метки вида `v1.3.5*`, которую я не увидела в топ-5 — возможно, она есть глубже в списке тегов и не попала в выборку «последние 5»).**

### AI Agency (`AI_APP_AGENCY`)
- Метки — те же общие «canon»-метки, что у PR Studio: `crisis-refactor-2026-06-27`, `crisis-canon-2026-06-27`, `copywriter-canon-2026-06-26`, `v0.8.6-commstrat-canon`, `v0.8.6-creative-handoff-recognition` (31.05). Версийных меток продукта нет.
- `--contains crisis-refactor-2026-06-27`: только `feat/contract-vs-standard` (текущий checkout).
- Активность: `feat/contract-vs-standard` 24.07, `feat/sec1-auth-sig` 18.07, **`master` 26.06**, `backup-pre-wip-cleanup-2026-05-19` 18.04 — master стоит почти два месяца.
- `master...HEAD`: 0/4 — текущая ветка на 4 коммита впереди master.
- Вывод: однозначно определить нельзя, тем же образом что и PR Studio. Master протух, метки не продуктовые. Кандидат — `feat/contract-vs-standard` (самая активная и текущая), но подтверждения через версийную метку нет.

### Smart Analytica (`ROSST_AI_Media`)
- Метки — чистая версийная последовательность: `v1.3.13-analytics-hub` (10.08), `v1.3.12-analytics-hub` (10.08), `pre-merge-sa-2026-08-09`, `v1.3.11-analytics-hub` (24.07).
- `--contains v1.3.13-analytics-hub`: только master (текущий checkout).
- Активность: master 13.08 (сегодня, самая свежая), дальше три feature-ветки от 09.08.
- Версия конфига 1.3.13 совпадает с меткой.
- ⚠️ 37 незаписанных файлов на master — задача предупреждала, что «в Smart Analytica запись сделана десять минут назад» другой сессией; я это дерево не трогала, только прочитала количество.
- Вывод: master — выпускная ветка, высокая уверенность.

### Docs Lab (`ROSST_AI_DocMaster`)
- Метки: `v0.12.1-docs-lab` (13.08, СЕГОДНЯ), `v0.12.0-docs-lab` (10.08), `backup/2026-08-09/feat-rag-core-adopt`, `v0.11.2` (08.08), `v0.11.1` (08.08).
- `--contains v0.12.1-docs-lab`: только `feat/rag-core-adopt` (текущий checkout) и его remote. **master отсутствует в списке.**
- Активность: `feat/rag-core-adopt` 13.08 (сегодня), `master` 09.08, `fix/docslab-probe-local` 09.08, `fix/docslab-cpd44-resume-fallback` 03.08.
- `master...HEAD`: 0/31 — master полностью позади, feat/rag-core-adopt на 31 коммит впереди.
- Версия конфига 0.12.1 совпадает и с меткой, и с записью в MEMORY «Docs Lab: 0.12.1 у клиентов (13.08), доставка проверена клиентским ключом».
- Вывод: выпускная ветка — `feat/rag-core-adopt`, НЕ master. Уверенность высокая: три независимых сигнала (метка, версия конфига, память о клиентской поставке) сходятся на этой ветке и её же коммите от сегодняшнего дня.

## 🔴 Где определить однозначно не смогла
1. **PR Studio** — нет продуктовых версийных меток (только общие «canon»-метки на несколько продуктов), master протух с 06.06. Кандидаты: `fix/updater-is-newer-prerelease` (активнее, текущий checkout) vs `fix/prstudio-cpd44-resume-fallback`. Различие — только свежесть коммитов, подтверждающей версийной метки нет ни у одной.
2. **AI Agency** — та же картина: нет продуктовых меток, master стоит с 26.06. Кандидат — `feat/contract-vs-standard` (единственная содержит найденную общую метку и самая активная), но без версийного подтверждения.
3. **Media Radar** — формально master содержит последнюю найденную метку, но версия в конфиге (1.0.0) не бьётся с известной клиентской версией 1.3.5 из памяти. Возможно, версийная метка Media Radar новее v1.3.x существует, но не попала в выборку «последние 5 по дате создания» — стоит перепроверить полный список тегов отдельно.
4. **Oracle** — метка новее (v0.4.5, 10.08) лежит в feature-ветках, а не в master; при этом клиентская версия по памяти 0.4.2 — старше метки. Не исключено, что 0.4.2 собиралась ещё до создания метки v0.4.5, и текущая выпускная ветка для СЛЕДУЮЩЕГО релиза — `feat/oracle-install-per-user`, но подтверждения от самого Антона/лога сборки нет.

## Подтверждение рамок
Ничего не переключала, ни одной ветки не меняла. Использовались только: `git tag`, `git log` (чтение метаданных меток), `git branch -a --contains`, `git for-each-ref`, `git branch --show-current`, `git status --porcelain` (только счётчик, содержимое не перечисляла), `git rev-list --left-right --count`, чтение `tauri.conf.json` и `manager.rs` через `grep`. Ни `checkout`/`switch`/`pull`/`stash`/`merge`/`push` не выполнялись ни разу.
