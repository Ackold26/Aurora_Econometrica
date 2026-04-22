# Manual test checklist: Comparison feature

Use after any commit touching:
- `src/lib/components/comparison/*`
- `src-tauri/src/commands/project.rs` (load_snapshot, project_load_comparison)

## Setup

1. `AIAGENCY_DEV=1 CARGO_TARGET_DIR="D:/cargo-targets/econometrica" npm run tauri dev`
2. Ждать пока sidecar healthy (см. log «Econometrica sidecar healthy»).
3. **Prereq:** минимум 2 проекта с пройденным pipeline до Optimize.
   Если нет — создать 2 новых: Import → Validate → Model → Decompose → Optimize.

## Flow A: Open Comparison

1. В ProjectSelector (клик на имя проекта наверху) — dropdown.
2. На любом проекте кроме активного — нажать ⚖ (между ⌨ и 🗑).
3. **Ожидаемо:** открывается ProjectPickerModal.
4. Вводим в search имя проекта → фильтруется список.
5. Click на проект → Picker closes, ModelComparisonView opens (full-screen overlay).

### Verify
- [ ] activeProject НЕ переключился (chip сверху не изменился).
- [ ] ComparisonView показывает 6 секций: KPI grid, Channels table, Waterfall side-by-side, ROI bars, Optimize compare (если есть), Derived insights.
- [ ] KPI grid подсвечивает лучший зелёной рамкой.
- [ ] Channels table — `+/-` delta с цветовой подсветкой (зелёный positive, красный negative).

## Flow B: Keyboard & a11y (<dialog> native)

1. ComparisonView открыт.
2. Tab → focus идёт по элементам внутри (close button, потом focusable в body).
3. Tab достигает последнего — следующий Tab возвращает на первый (cycling внутри dialog).
4. Shift+Tab — обратно.
5. Escape → modal закрывается.
6. Focus возвращается на ⚖ кнопку с которой открыли.

### Verify
- [ ] Tab не уходит на элементы за dialog (header стейпера, sidebar, header проекта).
- [ ] Escape закрывает → activeProject unchanged.
- [ ] Backdrop click → modal закрывается.
- [ ] В 3 темах (dark/light/fun) focus ring видимый на всех интерактивных.

## Flow C: ProjectPickerModal <dialog>

1. Открыть picker.
2. Input auto-focuses (native showModal focus first focusable).
3. Tab → «Отмена» button.
4. Escape → picker closes, возвращает focus на ⚖ (не открывает ComparisonView).

### Verify
- [ ] Search focuses автоматически при open.
- [ ] Tab/Shift+Tab crossfades.
- [ ] Backdrop click → cancel.
- [ ] Escape fires onCancel.

## Flow D: ConfirmDialog <dialog>

ConfirmDialog используется в **/workflow** route (при удалении workflow).
Pipeline ProjectSelector использует native `confirm()` — не testируется здесь.

1. Открыть Creative Hub продукт (или любой где есть /workflow страница).
2. Navigate to Workflows page.
3. Click 🗑 на workflow → ConfirmDialog открывается.
4. Tab между «Отмена» и «Удалить» (2 focusable).
5. Escape → dialog закрывается + workflow остаётся (cancel fires).
6. Backdrop click → cancel.

### Verify
- [ ] Dialog открывается центрированный (margin:auto).
- [ ] 2 кнопки focusable, Tab cycling.
- [ ] Escape fires onCancel (deleteTarget → null).
- [ ] Backdrop click fires onCancel.
- [ ] «Удалить» danger style (red).

## Flow E: Scenarios overflow

1. Проект с >50 сценариев (создать скриптом или вручную).
2. Открыть Comparison.

### Verify
- [ ] Banner «ℹ Показаны последние 50 сценариев (A: 50 из N, B: M из L)» сверху.
- [ ] Если ни у A ни у B не >50 — banner не показывается.

## Flow F: Optimize compare — partial data

1. Проект A прошёл до Optimize.
2. Проект B — только Model (без Optimize).
3. Открыть Comparison.

### Verify
- [ ] Секция 5 «Оптимизация бюджета» показывается (if `hasOptimize` true).
- [ ] В таблице каналы где есть `curA/curB` но нет `optA/optB` — показаны с «—» в optimal columns (благодаря A1 filter fix).
- [ ] Лифт/бюджет A показаны, B — «—» или 0.

## Flow G: ECharts dispose на unmount

1. Открыть Comparison.
2. Закрыть → открыть снова (тот же набор проектов).
3. Повторить 5 раз.

### Verify (через DevTools):
- [ ] `document.querySelectorAll('canvas').length` не растёт неограниченно.
- [ ] Нет warning'ов в console о «zrender disposed instance» или аналог.

## Flow H: 3 проекта dropdown

1. ProjectSelector открыт.
2. Наблюдение: ⚖ есть на каждом проекте кроме активного или на всех?

### Verify
- [ ] Если ⚖ на активном — кликается, в PickerModal активный исключается.
- [ ] Если ⚖ только на не-активных — логично.

## Flow I: DecomposeStep quiet on Validate (regression — rc1.4)

Защита от регрессии `29fd0c6` (onMount спамит /compute/decompose пока нет модели).

1. Dev-server: `AIAGENCY_DEV=1 CARGO_TARGET_DIR="D:/cargo-targets/econometrica" npm run tauri dev`
2. Открыть новый проект (чистый state, модель НЕ обучена).
3. Загрузить данные (Import) → перейти на Validate step.
4. Дождаться 3-5 сек (любые fetch'и должны случиться).

### Verify

Открыть sidecar.log (`%APPDATA%/com.aurora.econometrica-gui/sidecar.log` или dev-path).

- [ ] `grep -c "/compute/decompose" sidecar.log` = **0** пока пользователь не дошёл до Model step.
- [ ] После Train модель → пользователь переключается на Decompose → `/compute/decompose` появляется ровно 1 раз.

**Regression signal:** если /compute/decompose спамит при Validate — guard сломан, rollback на commit `29fd0c6` + hotfix.

## Flow J: merge_rules end-to-end (regression — rc1.2/1.3)

Защита от регрессии Pydantic silent-drop + 4-layer materialization (rc1.2 → rc1.3).

1. Импортировать датасет где есть weak channels (Retail Media, Радио, Пресса, ООН).
2. Validate step → в рекомендациях появляется «Объединить слабые каналы в Малые медиа».
3. Применить merge recommendation.
4. Train модель.

### Verify

`sidecar.log` должен содержать (последовательно):

- [ ] `/compute/train/start: merge_rules={'Малые медиа': [...]}`  — Pydantic принял поле (fail = silent-drop bug).
- [ ] `df.columns BEFORE: N → AFTER: N+1` — merge применён в modeler.py.
- [ ] `Training MMM: X obs, Y media, Z control` — модель обучается (fail = MISSING_MEDIA_COLUMNS).

**Regression signal:** если merge_rules={} в логе — Pydantic снова silent-drop, проверить `TrainRequest` / `TrainStartRequest` модели в `sidecar/econometrica/models/train.py`.

## Regression checks

1. Old features работают:
   - [ ] Import → Validate → Model → Decompose → Optimize — полный pipeline.
   - [ ] Report export PPTX/XLSX/HTML.
   - [ ] Save as .aurora archive → импорт на «другой машине».
   - [ ] Settings → Projects folder.
   - [ ] Onboarding tours на всех 6 шагах.

## Known issues (не блокеры)

- `<dialog>` animations не играют при первом open сразу после mount (microtask timing). Flash может быть.
- В некоторых Svelte warnings про unused CSS после DataTable reuse — информационные.

## Failed test?

1. Запиши в Obsidian `Mistakes/2026-04-XX-comparison-bug.md` — incident.
2. Hotfix branch → fix → new tag `v1.0.10-rc1.2`.
3. Обновить этот checklist с new verify step чтобы не повторилось.
