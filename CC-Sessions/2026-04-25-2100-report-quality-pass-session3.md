---
tags: [session, compressed]
type: session
updated: 2026-04-25
---

# Quick Reference

XLSX полный hybrid pass через **reference-driven workflow**: Антон в Excel вручную правит widths/alignment/styles до идеала → Python script извлекает через openpyxl + XML → применяю в rust_xlsxwriter код. Параллельно: Validate page получил **sticky header с 4 key metrics** (Ratio/VIF/Период/MQS прогноз) через `validationHeaderMetrics` derived store + StepWrapper rendering, HTML cover **компактный layout** (3 cols cover-meta вместо 4, убрана «Версия», cover h1 без max-width).

**Topic:** XLSX hybrid + Validate sticky + HTML cover compact (session 3)
**Key files:** `src-tauri/src/commands/report.rs`, `src/lib/components/pipeline/StepWrapper.svelte`, `src/lib/components/pipeline/ValidateStep.svelte`, `src/lib/project-state.js`, `sidecar/econometrica/aurora_html/sections.py`, `sidecar/econometrica/aurora_html/templates/layout.css`
**Status:** SHIPPED commit `3da0b1d` (7 files, +855/-195). Pending: Phase 0.5 GH Release v1.0.13, math roadmap (Phase 1.1/1.9/2.9 + 5 findings).

## Learnings

### 1. Reference-driven XLSX styling workflow (системный паттерн)

Когда сложно достичь идеала программно, **переложить дизайн на пользователя**:

1. Сгенерировать XLSX базовым layout
2. Антон в Excel вручную правит widths/alignment/styles до желаемого результата
3. Сохраняет как `XLSX_reference.xlsx`
4. **Python script** извлекает форматирование:

```python
# openpyxl для high-level data
import openpyxl
wb = openpyxl.load_workbook(r"C:\Users\ackol\Desktop\XLSX_reference.xlsx")
for sname in wb.sheetnames:
    ws = wb[sname]
    print(f"freeze: {ws.freeze_panes}")
    for col_letter, cd in ws.column_dimensions.items():
        if cd.width:
            print(f"{col_letter}: {cd.width:.4f}")
    # cell.alignment.horizontal/vertical
    # cell.number_format
    # cell.fill.fgColor.rgb
    # cell.font.{name,size,bold,italic,color}
    # ws._charts (BarChart, AreaChart) с anchor info

# raw XML для точных col widths (openpyxl показывает только некоторые)
import zipfile, xml.etree.ElementTree as ET
with zipfile.ZipFile(reference_path) as z:
    xml = z.read('xl/worksheets/sheet1.xml').decode('utf-8')
root = ET.fromstring(xml)
ns = {'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
for c in root.find('main:cols', ns).findall('main:col', ns):
    print(f"min={c.get('min')} max={c.get('max')} width={c.get('width')}")
```

5. Применить в rust_xlsxwriter код через `set_column_width(N, X)`, `Format::new().set_align(...)`, etc

### 2. Conversion: см → Excel char units

**Формула:** `char_units = cm × 5.4` (приблизительно)

Точнее: `char_units = (cm × 96 / 2.54 - 5) / 7` где 96 = px/inch, 2.54 = cm/inch, 7 = px/char (default font), 5 = padding.

Excel internally хранит widths в char units. UI показывает «Ширина: X.XX см». Антон диктует в см, я конвертирую.

| См | Char units |
|---|---|
| 1.0 | 5.4 |
| 2.5 | 13.5 |
| 5.0 | 27.0 |
| 10.0 | 54.0 |
| 19.2 | 103.68 |

### 3. rust_xlsxwriter: horizontal + vertical alignment — два разных slots

**Pattern:** `set_align(value)` принимает один FormatAlign value. Excel хранит horizontal и vertical в разных slots — можно вызвать дважды:

```rust
let fmt = Format::new()
    .set_align(FormatAlign::Center)        // horizontal
    .set_align(FormatAlign::VerticalCenter); // vertical
```

`FormatAlign` enum содержит и horizontal (Left/Center/Right/CenterAcross/Justify) и vertical (VerticalTop/VerticalCenter/VerticalBottom). API определяет slot по value type.

**Антон формулирует «выровнять посередине» → vertical center** (по высоте ячейки), не горизонтально (где обычно уже Center).

### 4. Excel chart styling: built-in style 12

`chart.set_style(12)` — Excel built-in chart style ближайший к hybrid дизайну (gradient navy/gold). Альтернативы (1-48 styles) — пробовать по визуальному подбору.

`chart.set_width(N).set_height(M)` где N, M в **pixels**. Reference XLSX uniform 567×283 px (15×7.5 cm) на всех 5 charts.

### 5. Derived store для sticky pipeline metrics

Pipeline шаги (Импорт/Валидация/Модель/Декомпозиция/Оптимизация/Отчёт) обернуты в общий `StepWrapper.svelte`. Чтобы добавить **только на одном шаге** интерактивный header — derived store + conditional render:

```javascript
// project-state.js
export const validationHeaderMetrics = derived(validateData, ($vd) => {
  const result = $vd?.result;
  if (!result) return null;
  // ... compute ratio, maxVif, mqs prognosis с tier statuses
  return { ratio, ratioStatus, maxVif, vifStatus, ... };
});
```

```svelte
<!-- StepWrapper.svelte -->
const validationMetrics = $derived(step === 1 ? $validationHeaderMetrics : null);
{#if validationMetrics}
  <div class="key-metrics">
    <span class="metric-chip light-{validationMetrics.ratioStatus}">...</span>
  </div>
{/if}
```

**Reactive:** при изменении ролей columns → `validateData` updates → `validationHeaderMetrics` derived recomputes → chip светофоры меняются автоматически.

**Sticky:** StepWrapper уже имеет `step-header { flex-shrink: 0 }` + `step-content { overflow }` — header не прокручивается естественно.

## Solutions & fixes

### XLSX hybrid pass

**Проблема:** изначально XLSX выглядел plain — без brand header на data sheets, разные tab colors на каждом sheet, узкие columns обрезающие headers, charts default Excel синие/красные.

**Решения:**

1. **Brand header helper** для всех 9 sheets:
```rust
let write_brand_header = |ws, sheet_title: &str, stripe_cols: u16| -> Result<(), String> {
    ws.write_with_format(0, 0, "AURORA AI", &brand_aurora_fmt)?;
    ws.write_with_format(0, 1, sheet_title, &brand_title_fmt)?;
    ws.write_with_format(0, 2, "Конфиденциально", &brand_conf_fmt)?;
    for col in 0..stripe_cols {
        ws.write_with_format(1, col, "", &brand_stripe_fmt)?;
    }
    ws.set_row_height(0, 21.75)?;
    ws.set_row_height(1, 3.0)?;
    Ok(())
};
```

2. **Все hardcoded row indices сдвинуты +2** для accommodate brand (header at row 2, data at row 3+).

3. **Все `set_freeze_panes` УБРАНЫ** (per reference Антон не использует).

4. **Tab colors consistent:** navy DEEP_80 (default) / GOLD signature (Cover, ROI каналов, Оптимизация).

5. **Header format:**
```rust
let header_fmt = base_fmt.clone()
    .set_bold().set_font_size(11)
    .set_background_color(Color::RGB(DEEP_80))
    .set_font_color(Color::RGB(WHITE))
    .set_align(FormatAlign::Center)
    .set_align(FormatAlign::VerticalCenter)
    .set_border_bottom(FormatBorder::Medium)
    .set_border_bottom_color(Color::RGB(GOLD));
```

6. **Number formats centered:**
```rust
let num_fmt = base_fmt.clone()
    .set_num_format("#,##0")
    .set_align(FormatAlign::Center)
    .set_align(FormatAlign::VerticalCenter);
// pct_fmt: "0.0%"
// roi_fmt: "0.00\"x\""
```

7. **Chart styling:** `chart.set_style(12).set_width(567).set_height(283)`.

8. **Точные column widths из reference (см → char×5.4):**
   - Cover: A=22.14, B=41.29, C=21.86
   - Executive Summary: A:C=26.43
   - Спецификация: A=24.57, B=26.0 (4.81см), C=36.72 (6.80см), D=67.86
   - ROI каналов: A=23.76 (4.4см), B=36.43, C=21.14 (3.91см), D=11.88 (2.2см), E:G=25.29
   - Spend vs Effect: A:C=18.90 (3.5см), D=14.71, E=20.71, F=15.71
   - Динамика: A=13.5 (2.5см), B=14.47 (2.68см), C=13.18 (2.44см), D:I=39.29
   - Оптимизация: A=28.78 (5.33см), B=39.29, C=19.28 (3.57см), D:F=18.43
   - Данные: A=5.4 (1см), B=13.61 (2.52см), C=32.71, D=11.88 (2.2см), E:I=32.71, J=26.71, K=32.57
   - Глоссарий: A=16.2 (3см), B=103.68 (19.2см), C **hidden**

9. **Глоссарий A1 override** на «Aurora AI» (proper case вместо «AURORA AI» uppercase) — Антон специфически попросил.

### Validate sticky header

**Проблема:** на странице Валидации хочется иметь always-visible 4 ключевых метрики (Ratio/VIF/Период/MQS) которые reactive обновляются при смене ролей.

**Решение:**

```javascript
// project-state.js — derived store
export const validationHeaderMetrics = derived(validateData, ($vd) => {
  const result = $vd?.result;
  if (!result) return null;
  const ratio = Number(result.detected?.ratio ?? 0);
  const cols = result.columns ?? [];
  const mediaCols = cols.filter(c => c.role === 'media');
  const vifs = mediaCols.map(c => Number(c.stats?.vif)).filter(Number.isFinite);
  const maxVif = vifs.length ? Math.max(...vifs) : null;
  const nObs = Number(result.file?.rows ?? 0);

  // MQS prognosis heuristic
  let score = 100;
  if (ratio < 2) score -= 40; else if (ratio < 4) score -= 25; else if (ratio < 10) score -= 10;
  if (maxVif != null) {
    if (maxVif > 10) score -= 25; else if (maxVif > 5) score -= 10;
  }
  if (nObs < 12) score -= 25; else if (nObs < 24) score -= 8;
  const mqs = Math.max(0, Math.min(100, score));

  const tierUp = (v, ok, warn) => v >= ok ? 'ok' : (v >= warn ? 'warn' : 'bad');
  const tierDown = (v, ok, warn) => v <= ok ? 'ok' : (v <= warn ? 'warn' : 'bad');
  return {
    ratio, ratioStatus: tierUp(ratio, 10, 4),
    maxVif, vifStatus: maxVif == null ? 'na' : tierDown(maxVif, 5, 10),
    nObs, periodStatus: tierUp(nObs, 24, 12),
    mqs, mqsStatus: tierUp(mqs, 80, 60),
  };
});
```

```svelte
<!-- StepWrapper.svelte: step-header (sticky) -->
<div class="step-header">
  <span class="step-icon">{stepDef.icon}</span>
  <h2 class="step-title">{stepDef.labelRu}</h2>
  {#if validationMetrics}
    <div class="key-metrics">
      <span class="metric-chip light-{validationMetrics.ratioStatus}" title="...">
        <span class="metric-label">Ratio</span>
        <span class="metric-value">{validationMetrics.ratio.toFixed(1)}:1</span>
      </span>
      <!-- VIF max, Период, MQS прогноз — same pattern -->
    </div>
  {/if}
  {#if meta.status === 'complete'}<span class="step-badge complete">✓ Готово</span>{/if}
</div>
```

CSS muted hybrid (consistent с TrafficLight det-chip):
```css
.metric-chip {
  display: inline-flex; gap: 6px; padding: 3px 10px;
  border-radius: 20px; font-size: 11px;
  background: rgba(127,127,127,0.08);
  border: 1px solid rgba(127,127,127,0.2);
}
.metric-chip.light-ok   { background: color-mix(in srgb, var(--success) 12%, transparent); border-color: color-mix(in srgb, var(--success) 30%, transparent); }
.metric-chip.light-warn { background: color-mix(in srgb, var(--warning) 12%, transparent); ... }
.metric-chip.light-bad  { background: color-mix(in srgb, var(--danger)  12%, transparent); ... }
```

### HTML cover compact

**Проблема:** между cover-meta и Executive Summary большое пустое пространство; «Версия v1.0.11» — техдеталь не нужна клиенту.

**Решение** (`aurora_html/templates/layout.css`):
- `cover h1 max-width` убран → длинные titles в одну строку
- Cover gap: 24px → 8px (h1+subtitle ближе)
- Cover padding: 60/40 → 40/24
- Cover-meta: 4 → 3 колонки (убрана «Версия»)
- Cover-meta margin-top: 32px → 16px, padding-top: 24px → 16px
- `closing-statement` white-space: nowrap

`aurora_html/sections.py` — удалила cover-meta-cell для «Версия» из render_cover.

## Decisions

### Reference-driven workflow вместо algorithmic styling
**Why:** XLSX styling сложно достичь алгоритмически (autofit на Cyrillic даёт узкие widths, число tweaks огромное). Антон в Excel вручную тратит 5-10 минут, я Python-скриптом за 1 минуту извлекаю exact values. Net time saving: ×10.
**How to apply:** для любого Office-файла где визуальный stайлинг важен (XLSX/PPTX/DOCX), делегировать дизайн пользователю как single shot, потом превратить в код.

### 4 chip Validate (Ratio + VIF + Период + MQS прогноз)
**Why:** Антон спрашивал какой параметр primary в эконометрике. Я ответила что **VIF + Ratio + Period + MQS** — комплексная метрика качества данных. Простые counts (медиа каналов, контролей) — это **не качество**, это структура. MQS прогноз — heuristic комбинация для sanity check «стоит ли тренировать».
**How to apply:** при показе тех. показателей разделять «структура данных» (counts) от «качество данных» (statistical metrics).

### «Aurora AI» proper case на Глоссарии (vs «AURORA AI» везде)
**Why:** Антон специфически попросил для Глоссария. Возможно потому что Глоссарий — это reference document (не для action) и «AURORA AI» uppercase воспринимается как badge/marker, а на Глоссарии текст более spokojный. Не углублялась — просто override.

### Удалена «Версия v1.0.11» из HTML cover-meta
**Why:** «Версия программы» — техническая деталь, клиенту не нужна. Cover мета должна быть только бизнес-information (для кого, дата, классификация).
**How to apply:** не показывать клиентский version номер в client-facing документации (для них «модель версия» = период данных и отчёт sequence).

### Удалены «Q3-Q4 2026» / «к следующему периоду» (PPTX + HTML)
**Why:** конкретные периоды — задача media-планнера, не эконометрики. Эконометрика выдаёт **аналитическую** рекомендацию (как улучшить allocation), **когда** применять — отдельное решение.

### Убрали freeze panes на всех sheets
**Why:** Антон в reference их не использует. Большинство sheets короткие (10-30 rows), freeze не нужен. На длинных (Динамика 43 точки, Данные) — Антон scroll-ит и без freeze.

### Cover stripe per-sheet (3/4/6/8 cols)
**Why:** stripe должна **визуально балансировать таблицу**. Узкие sheets (Cover 3 cols, Глоссарий 2 cols, Спецификация 4 cols) — узкая stripe. Wide tables (Executive Summary 8 cols) — wide stripe. Антон вручную сделал per-sheet значения которые я применила.

## Pending

### Финальная приёмка XLSX
Антон сейчас перезапустит tauri dev → проверит обновлённый XLSX (после моих правок ширины и vertical center). Возможно ещё мелкие правки.

### Phase 0.5 — GH Release v1.0.13 (BLOCKED, ~30-60 min)
1. `npm run tauri build` (sidecar exe rebuild автоматически)
2. git tag `v1.0.13`
3. `gh release create v1.0.13` + upload installer
4. Supabase update (app_versions table) + latest.json в aurora-releases
5. PASHE_IT.MD update для клиента

### Post-ship math roadmap
- **Phase 1.1** Joint adstock+Hill MCMC estimation (~12-15h)
- **Phase 1.9** Full posterior CI propagation (~8-10h)
- **Phase 2.9** Pareto multi-objective optimizer (~12-15h, решает trivial allocation на TV-heavy)
- **5 documented findings post-fix v1.2** (~6-10h):
  - A2 ROI thresholds recalibration на real data
  - B2 adstock schema documentation
  - B4 scenario UI controls
  - C1 OLS fallback для n<30
  - C2 scenario padding UX

## Files Modified (commit `3da0b1d`)

```
CC-Sessions/2026-04-25-1600-report-quality-pass-v1013-session2.md  (new — previous compress)
sidecar/econometrica/aurora_html/sections.py                       M  (cover-meta 4→3, removed Версия)
sidecar/econometrica/aurora_html/templates/layout.css              M  (cover compact + h1 no max-width)
src-tauri/src/commands/report.rs                                   M  (XLSX полный hybrid pass)
src/lib/components/pipeline/StepWrapper.svelte                     M  (sticky key-metrics при step=1)
src/lib/components/pipeline/ValidateStep.svelte                    M  (removed local metrics, moved to derived store)
src/lib/project-state.js                                           M  (validationHeaderMetrics derived store)
```

7 files, +855/-195. Pre-commit hook V40 lint OK.

## Setup & Config Changes

Не было config изменений в этой сессии. Только код.

### Reference XLSX (extracted values)

**Workbook от Антона** `C:\Users\ackol\Desktop\XLSX_reference.xlsx` — 9 sheets, hand-crafted Excel.

**Извлечённые tab colors:**
- Обзор, ROI каналов, Оптимизация: `FFC5A46D` (GOLD)
- Executive Summary, Спецификация, Декомпозиция, Spend vs Effect, Динамика, Сценарии, Данные, Глоссарий: `FF1E3A5F` (DEEP_80)

**Извлечённые row heights (per sheet brand+stripe):**
- Cover: row 1 = 25.5pt (kicker), row 2 = 36pt (Lora 28pt title), row 3 = 3.95pt (stripe)
- All data sheets: row 1 = 21.75pt (brand), row 2 = 3.0pt (stripe)

**Stripe widths per sheet (cols):**
- Cover: 3 (A:C)
- Executive Summary: 8 (A:H)
- Спецификация: 4 (A:D)
- Глоссарий: 2 (A:B) (после Антоновой post-reference правки)
- ROI каналов / Spend vs Effect / Динамика / Оптимизация / Данные / Сценарии: 6 (A:F)

**Final widths after Антоновых post-reference правок (см → char):**
| Лист | Col widths |
|---|---|
| Cover | A=22.14, B=41.29, C=21.86 |
| Executive Summary | A:C = 26.43 |
| Спецификация | A=24.57, B=26.0 (4.81см), C=36.72 (6.80см), D=67.86 |
| ROI каналов | A=23.76 (4.4см), B=36.43, C=21.14 (3.91см), D=11.88 (2.2см), E:G=25.29 |
| Spend vs Effect | A:C=18.90 (3.5см), D=14.71, E=20.71, F=15.71 |
| Динамика | A=13.5 (2.5см), B=14.47 (2.68см), C=13.18 (2.44см), D:I=39.29 |
| Оптимизация | A=28.78 (5.33см), B=39.29, C=19.28 (3.57см), D:F=18.43 |
| Данные | A=5.4 (1см), B=13.61 (2.52см), C=32.71, D=11.88 (2.2см), E:I=32.71, J=26.71, K=32.57 |
| Глоссарий | A=16.2 (3см), B=103.68 (19.2см), C hidden |

## Errors & Workarounds

### 1. openpyxl не показывает все column widths
**Symptom:** `ws.column_dimensions['B'].width = None` хотя в Excel column B 36.43 wide.
**Root cause:** Excel хранит widths в **range form** `<col min=1 max=2 width=36.43>` (один width для нескольких cols). openpyxl показывает `column_dimensions` только если есть **explicit per-column entry**. Range entries skipped.
**Fix:** парсить raw XML напрямую через ElementTree:
```python
import zipfile, xml.etree.ElementTree as ET
ns = {'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
with zipfile.ZipFile(reference) as z:
    root = ET.fromstring(z.read(f'xl/worksheets/sheet{N}.xml').decode())
for c in root.find('main:cols', ns).findall('main:col', ns):
    print(c.get('min'), c.get('max'), c.get('width'))
```

### 2. Cyrillic в openpyxl при stdout (Windows cp1251)
**Symptom:** `UnicodeEncodeError: 'charmap' codec can't encode character '\xb2' in position 36: character maps to <undefined>`.
**Root cause:** Windows Python default stdout encoding cp1251, не handle ² superscript / Cyrillic mix.
**Fix:** wrap stdout в UTF-8:
```python
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
```

### 3. Bash file path с прямой `C:\` не работает
**Symptom:** `FileNotFoundError: '/c/Users/ackol/Desktop/XLSX_reference.xlsx'`.
**Root cause:** MSYS2 Bash translates `/c/...` to `C:/...` для shell commands но Python opens files напрямую.
**Fix:** использовать raw Windows path в Python: `r"C:\Users\ackol\Desktop\XLSX_reference.xlsx"`.

### 4. Sidecar Python module cache (повторяется через сессии)
**Symptom:** изменения `.py` не применяются после rebuild — старый narrative показывается.
**Fix:** kill `python.exe` через PowerShell `Stop-Process -Id N -Force`, watchdog респавнит за 15s. Или закрыть/открыть Aurora окно.

### 5. Tauri dev зависает на zombie port 5173
**Symptom:** `Error: Port 5173 is already in use`.
**Fix:** `netstat -ano | grep :5173` → kill PID via `Stop-Process -Id N -Force` (PowerShell, не Bash — Bash `taskkill /F` mangle).

### 6. `2.2` vs `2.2 cm` interpretation
**Symptom:** Антон сказал «ширина D 2.2» — без cm. Я interpreted как char units → 2.2 char (~16px), data «14.67x» обрезается до «#».
**Fix:** Антон уточнил «все цифры — это сантиметры». Перепонимаю все predыдущие comments × 5.4. Decision: всегда требовать unit explicit или установить convention upfront.

## Full Session Notes

### Хронология

1. **Стартовая cover XLSX** — у меня уже был commit `33269fe` с базовым brand на Cover/Executive Summary/Спецификация. Антон попросил **полный hybrid pass** на всех листах + brand AI.

2. **Decision Variant 1 vs 2:** Я предложила:
   - V1 (быстро): остановиться на 3 sheets + tab colors
   - V2 (полностью): brand на всех 9 sheets + offset all rows
   Антон выбрал V2.

3. **Последовательное применение brand+offset на 7 sheets** — добавила brand_header вызов + сдвинула все hardcoded row indices на +2 (header row 0→2, data row i+1→i+3, formulas, chart anchors, conditional_format ranges).

4. **Антон сделал XLSX_reference.xlsx** на Desktop с правильным форматированием.

5. **Извлекла reference через Python** — openpyxl + raw XML. Применила в Rust:
   - Tab colors per sheet
   - Row heights brand 21.75 + stripe 3.0
   - Column widths точные
   - Header alignment center+vertical center
   - Chart sizes 567×283
   - Removed freeze panes

6. **Антон диктовал post-reference корректировки** см. → char×5.4:
   - Спецификация B=4.81см, C=9.45→6.80см
   - ROI A=4.4см, C=3.91см, D=2.2см
   - Spend vs Effect A:C=3.5см
   - Динамика A=2.5см, B=2.68см, C=2.44см
   - Оптимизация A=5.33см, C=3.57→5.06см
   - Данные A=1см, B=2.52см, D=2.2см
   - Глоссарий A=3см, B=19.2см, C hidden, A1 «Aurora AI» override

7. **Validate sticky header** — Антон попросил вынести key metrics в шапку шага которая sticky. Создала derived store + StepWrapper conditional rendering.

8. **HTML cover compact** — Антон попросил уменьшить gaps + удалить «Версия». Сделала.

9. **Commit + memory update.**

### Critical insights

- **Reference-driven workflow** — экономит часы на стайлинг через algorithmic tweaking. Будущий шаблон: clear `*_reference.xlsx`/`*_reference.pptx` workflow для всех Office templates.
- **Conversion см → char × 5.4** — формула надёжна для Excel default font (Calibri 11pt). При custom fonts (Inter 10pt) может быть чуть другой коэффициент, но ~5.4 рабочий.
- **rust_xlsxwriter set_align twice** — паттерн для horizontal+vertical alignment работает через два вызова, тестировано.
- **Derived store + conditional render** — clean pattern для step-specific UI без changing wrapper signature.

### Active scheduled work after ship

- `Aurora_Econometrica_Math_Plan.md` (на Desktop) — master plan
- `docs/MATH_AUDIT_v1_3.md` — cross-engine propagation findings
- `project_econometrica_v1013_report_quality.md` — sessions 2+3 memory (updated)
- `project_econometrica_math_audit.md` — Phases 1-7 history
- `project_econometrica_phase0_roi_recalibration.md` — verdict logic
