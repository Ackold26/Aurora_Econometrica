---
tags: [session, compressed, econometrica, jax, numpyro, pymc, priors, live-test, reports, optimizer]
type: session
updated: 2026-04-19
---
# Quick Reference

Эпическая live-сессия на Econometrica + Кагоцел (31×34). Pipeline пройден end-to-end: Import→Validate→Model→Decompose→Optimize→Report. Ключевые breakthroughs: (1) PyTensor на Windows требует g++, не MSVC — переключились на JAX/NumPyro backend (NUTS за секунды вместо 15-30 мин); (2) Tighter priors на Hill-saturation устранили 1658 divergences; (3) Нормализация X_control исправила R² с -86 млрд % до 95.6 MQS. Плюс: file logging в sidecar, tight icons (0% margin) на все 9 приложений, стратегические документы (SaaS migration, Tamburin competitive, SYSTEM_REQUIREMENTS).

**Topic:** econometrica-live-test-jax-breakthrough

**Коммиты:**
- `74691f8` — MCMC UX polish (Markov Chain Monte Carlo rename, Stop button, time-based progress, data_file store fix, Adstock auto, docs)
- **`81d4d21`** — JAX/NumPyro backend + tight priors + control normalization + file logging + icons tight
- 16 коммитов иконок в 8 других приложениях (Logo_PNG_1 → Logo_PNG_3-2 header → Logo_PNG_4_cuted tight)

**Key files:**
- `sidecar/econometrica/engines/modeler.py` — NUTS sampler selection, priors, pickle cleanup, control normalization, y_pred fallback
- `sidecar/econometrica/server.py` — file logging + startup diagnostic, train/cancel endpoint, pptx endpoint (без try/except — TODO)
- `src-tauri/src/commands/econometrica.rs` + `lib.rs` — econ_train_cancel
- `src/lib/components/ConfigPanel.svelte` — data_file из importData, Adstock 'auto', MSVC hint
- `src/lib/components/pipeline/TrainingProgress.svelte` — Stop button, time-based pct, cancelled status
- `src/lib/components/pipeline/ModelTrainingStep.svelte` — handleStop, estimatedSec
- `src/lib/components/pipeline/ExpertModelPanel.svelte` — Диагностика Markov Chain Monte Carlo
- `src/lib/insights-rules.js` — MCMC→Markov Chain Monte Carlo в 4 карточках
- `src-tauri/icons/*` — Logo_PNG_4_cuted, tight fit 0% margin
- `docs/SYSTEM_REQUIREMENTS.md` (NEW)
- `README.md` — обновлён раздел Системные требования

**Внешние документы:**
- `D:/Docs/Aurora_Ai/5_Документация/SYSTEM_REQUIREMENTS_PLATFORM.md` (NEW)
- `D:/Docs/Aurora_Ai/5_Документация/COMPETITIVE_TAMBURIN.md` (NEW)
- `D:/Docs/Aurora_Ai/5_Документация/ROADMAP_SAAS_MIGRATION.md` (NEW)
- `D:/Docs/Aurora_Ai/KB/` — 4 MD + 3 index.md (Obsidian vault с frontmatter + wikilinks)

**Status:** ✅ **LIVE-ТЕСТ ПРОЙДЕН END-TO-END**
- Шаг 0 Импорт ✅ / Шаг 1 Валидация ✅ (ratio 2.38:1, 6 медиа, 7 контрол)
- Шаг 2 Модель ✅ MQS=95.6, R-hat < 1.01, Divergences=0
- Шаг 3 Декомпозиция ✅ waterfall+insights+таблица
- Шаг 4 Оптимизация ⚠️ работает, UX недоделки (slider не recalc, сценарии нет UI)
- Шаг 5 Отчёт: MD ✅ XLSX ✅ PPTX ❌ (error decoding response body)

---

## Learnings

### L1 — PyTensor на Windows требует g++ (не MSVC!)

Потратили много времени на установку MS Visual C++ Build Tools. Это **бесполезно для PyTensor** — он по умолчанию ищет `g++` через `shutil.which()`, не `cl.exe`. MSVC Build Tools полезны для NumPy/Cython, но PyTensor игнорирует их.

Лог показывает напрямую:
```
[WARNING] pytensor.configdefaults: g++ not available, if using conda: `conda install gxx`
[WARNING] pytensor.configdefaults: g++ not detected!  PyTensor will be unable to compile
[INFO] econometrica: pytensor.config.cxx = ""
```

Когда cxx="" → PyTensor использует Python-fallback → NUTS работает в Python-интерпретированном режиме → 15-30× медленнее.

**Варианты исправления:**
1. **MinGW-w64** (g++) — системный установщик, ~500 МБ. PyTensor auto-detects.
2. **JAX/NumPyro backend** — обход PyTensor компиляции. **Выбрали этот путь.**

### L2 — JAX/NumPyro версионный mismatch

На момент сессии:
- `pip install numpyro` → NumPyro 0.20.1
- `pip install jax` → JAX 0.10.0
- **Несовместимы:** NumPyro 0.20.1 ищет `jax.extend.core.primitives.xla_pmap_p`, которое JAX 0.10 удалил.

**Рабочий stack:** `jax==0.7.2 jaxlib==0.7.2 numpyro==0.20.1`.

Паттерн: при установке JAX+NumPyro всегда **пинить JAX на версию, совместимую с NumPyro** (последний NumPyro обычно отстаёт от JAX на 6-12 месяцев).

### L3 — NumPyro backend активируется одной строкой в pm.sample

После `pip install jax jaxlib numpyro` достаточно:
```python
trace = pm.sample(
    draws=draws, tune=tune, chains=chains,
    nuts_sampler='numpyro',
    chain_method='vectorized',  # parallel chains в одном JAX call
    return_inferencedata=True,
    progressbar=True,
)
```

**Не передавать:** `cores`, `callback` — они не поддерживаются NumPyro.

### L4 — Hill saturation priors создают funnel

Предыдущие priors:
- `alphas: Gamma(3, 1)` — mean=3, слишком сильная нелинейность
- `gammas: Beta(2, 2)` — U-shaped bimodal distribution
- `betas: HalfNormal(0.5)` — слабая регуляризация

Результат: 1658 divergences, R-hat > 3 даже на 2 каналах.

**Рабочие priors:**
- `alphas: Gamma(5, 3)` — mean=1.67, типичный saturation shape
- `gammas: Beta(3, 3)` — bell-shaped около 0.5
- `betas: HalfNormal(0.3)` — сильнее регуляризация
- `control_betas: Normal(0, 0.3)` — тоже
- `sigma: HalfNormal(0.3)` — y_norm std=1, 0.3 разумно

Также: убрал `gamma_scaled = gammas[i] * x.max()` — это создавало scale-зависимость, которая ломала geometry.

### L5 — Нормализация X_control критична

**Баг:** в коде model использовался `X_control.values.astype(float)` — **raw values**. Если контроли — это price (в ₽), температура (в градусах), или budget — control_effect = X_control @ control_betas взрывается в миллиарды, `mu` улетает, y_pred_norm > 1000, y_pred = y_pred_norm × y_std + y_mean = bajjilions.

**Симптом:** R² = -86 миллиардов %.

**Фикс:** `X_control_norm = (X_control - mean) / std` + использовать в pm.Model и в y_pred fallback.

### L6 — Pickle PyMC-модели падает с functools.partial

`pickle.dump(mmm)` где `mmm = pm.Model(...)` с custom Deterministic (Adstock/Hill) → `'functools.partial' object has no attribute '__name__'`. PyTensor closures содержат functools.partial без `__name__`.

**Fix:** не пиклим `mmm` и `trace`. Downstream engines (decomposer/optimizer/scenario) используют только `config`, `channel_params`, `y_actual`, `y_predicted`, `normalization` — этого достаточно.

### L7 — sample_posterior_predictive тоже может упасть

Даже без pickle, `pm.sample_posterior_predictive(trace, model=mmm)` иногда падает с той же functools.partial (особенно на Metropolis CompoundStep).

**Fix:** try/except + manual y_pred reconstruction из posterior means (применяем Hill-формулу к X_media_norm с mean(alpha), mean(gamma), mean(beta) + X_control_norm @ mean(control_betas) + mean(intercept)).

### L8 — Sidecar Stdio::null() = нет логов

В dev-режиме Tauri запускает Python sidecar с `stderr(Stdio::null())`. Никаких логов в dev-консоли. **Обязательно** добавлять file logging:
```python
_log_file = Path(APPDATA) / 'aurora-econometrica-gui' / 'logs' / f'sidecar-{date}.log'
logging.basicConfig(handlers=[StreamHandler(stderr), FileHandler(_log_file)], force=True)
```

Без этого — невозможно диагностировать crashes.

### L9 — Tauri dev watcher убивает sidecar при любом edit в src-tauri/

Запустить `npx tauri icon <path>` пишет в `src-tauri/icons/` → Tauri dev обнаруживает → Rust rebuild → app restart → Python sidecar kill.

**Паттерн:** во время live-теста **не трогать** src-tauri/. Только sidecar/ можно — Python reloadится вместе с Tauri, но это не критично.

### L10 — Metropolis CompoundStep вызывает functools.partial в arviz

Когда check_compiler() возвращал False (MSVC не помогает) → Metropolis sampler → CompoundStep (смесь типов) → functools.partial внутри → arviz.summary / ppc падают.

NUTS через JAX этой проблемы не имеет.

### L11 — MCMC в Python-backend runs на 4% CPU

Наблюдение: Python-backend NUTS работает на 1/4 ядра (~4.2% CPU). Это потому что PyTensor на Python-backend тратит много времени в pure-Python ops (не numpy). Эффективнее на 1-2 ядрах чем на 8.

JAX через XLA compile сразу утилизирует CPU на 100% × N_cores одновременно.

### L12 — R-hat > 1.05 и 0 divergences одновременно

После фикса priors получили странное состояние: `Divergences=0 ✅` но `R-hat > 4 ❌`.

Значит: geometry posterior OK (NUTS не путается), но цепи **разбежались в разные местные моды** (мультимодальность).

Это признак **data insufficiency** (мало строк) + over-parameterization. Решение: упростить модель ИЛИ добавить data ИЛИ сильнее priors. Нам помогло последнее + нормализация controls.

### L13 — Смешанные единицы в MMM-данных

Кагоцел: 6 media каналов, из которых:
- OLV/Banners/Social/Performance/Статьи — **бюджет в рублях** (миллионы-миллиарды ₽)
- TRPs бренд (W 25-54) — **пункты рейтинга** (22,100 ед.)

Наш MMM считает всех как одну шкалу → ROI TRPs получается 49,122× (искусственно огромный). Нужен либо CPP-pricing (умножить TRPs на cost-per-point) либо раздельная группа reach-cols в модели.

### L14 — Git Bash на Windows конвертирует single-slash args

`taskkill /F /IM python.exe` в Git Bash → `/F` интерпретируется как путь → ошибка. Решения:
- `taskkill //F //IM python.exe` (двойной слеш)
- `cmd "/c taskkill /F /IM python.exe"`
- Отдельный PowerShell (от Админа нужен для kill)

### L15 — `taskkill /F /IM python.exe` требует Admin

С non-admin PS: «Отказано в доступе» для процессов Python запущенных sidecar'ом через Tauri. Нужен PS от Администратора.

### L16 — Icon regeneration flow на Windows

1. Preprocess PNG (PIL: trim alpha bbox, convert white-opaque to transparent, pad to square, resize Lanczos 1024×1024)
2. `npx @tauri-apps/cli icon <path>` генерит ~30 файлов (icon.ico/png/icns + Windows Store Square*Logo + iOS AppIcon + Android mipmap)
3. Distribute через `cp` в все 8 других `src-tauri/icons/` директорий

Tight fit (0% margin): `side = max(w, h)` без множителя → логотип касается краёв.

### L17 — Aurora AI позиционирование vs Tamburin

Tamburin — основной РФ-конкурент (cloud SaaS, OLS/RF, простое UX). Наши USP:
- **Приватность данных** (локальная работа) — решающее для фарма/банков/B2B с NDA
- **Bayesian MMM (state-of-the-art)** с доверительными интервалами
- **Платформенность** (8 связанных продуктов)
- **Expert-режим** для data scientist'ов

Слабости против Tamburin:
- Нет публичных кейсов (Tamburin уже работает 5+ лет)
- Windows-only
- Ручной импорт без коннекторов к Mediascope/Adfox

### L18 — Claude API для SaaS: не подписки

Anthropic ToS запрещает перепродажу Claude Pro/Max в commercial SaaS. Для SaaS нужен API с per-token биллингом. Для РФ — **офшорное юрлицо** (EU/UAE/AM/KZ) для прямого биллинга Anthropic. Экономически API дешевле (~$1200/мес на 100 юзеров) чем 10× Max подписок.

---

## Decisions

### D1 — JAX/NumPyro over MinGW

Два пути ускорения PyTensor:
- **MinGW-w64**: системный g++, ~500 МБ, без правки кода, ~3-5× speedup
- **JAX/NumPyro**: pip package, ~800 МБ, одна строка правки, ~7-15× speedup + parallel chains + GPU-ready roadmap

Выбрали **JAX**. Причины: скорость, бандлинг в sidecar (не нужен системный install), будущий GPU-путь.

### D2 — Tighter priors над non-centered parameterization

Два стандартных решения funnel в Hill-моделях:
- Non-centered: `alpha_raw ~ Normal(0, 1); alpha = mu + sigma * alpha_raw` — переделывать модель
- Tight priors: просто сузить Gamma/Beta параметры — минутная правка

Выбрали **tight priors** — быстрее и дало 0 divergences.

### D3 — Pickle только channel_params + normalization (без trace/mmm)

Downstream engines не используют trace/mmm, а pickle падает из-за functools.partial в PyTensor closures. Решение: не пиклить, сохраняем только то что нужно decomposer/optimizer/scenario.

### D4 — File logging в %APPDATA%

- Никаких Stdio::null() проблем
- Файл живёт per-day (rotation через `sidecar-YYYY-MM-DD.log`)
- Можно читать параллельно с работой sidecar
- Дублирование в stderr для dev-run

### D5 — Нормализация controls одинаково с media

Media нормализовались, controls — нет. Очевидный баг. Добавили `X_control_norm = (X_control - mean) / std` + использовать в модели и в y_pred fallback + сохранять `control_means/stds` в pickle для downstream.

### D6 — Tight icons (0% margin)

После итераций (2% → 2% → 0%): Logo_PNG_4_cuted — симметричная пирамида без текста, хорошо читается в любом размере. Tight fit делает её максимально крупной в квадрате таскбара.

### D7 — В отчётах нужна единая формула спецификации модели

Feedback от Антона: клиенту нужно видеть математику. MMM без формулы = black box = недоверие. Задача: добавить секцию «Спецификация» в MD/XLSX/PPTX с формулами Hill/Adstock + priors + описание.

### D8 — Optimizer UX — отдельная задача завтра

Текущее состояние Optimizer:
- Slider «Общий бюджет» не триггерит recalc
- При +0.0% нет explanation overlay
- Scenario Playground UI отсутствует
- Смешанные единицы (TRPs vs ₽) ломают ROI

Все 4 записано в `project_econometrica_optimizer_ux.md`. Разбираем завтра.

### D9 — Session 4 коммичу одним коммитом вместо рефактора

Всё держится вместе: JAX activation + tight priors + control normalization + file logging + pickle cleanup. Это один atomic change — `81d4d21`.

### D10 — Путь B (Hybrid SaaS) для Aurora AI

Roadmap 2027 Q3-Q4: 7 LLM-продуктов в SaaS. Econometrica + Creative Hub остаются desktop-only (сохраняет USP приватности для enterprise). Econometrica в SaaS — отдельный проект 2028+.

---

## Solutions & Fixes

### Fix 1 — data_file из правильного store (ConfigPanel)

**Bug:** ImportStep сохранял в `importData.file`, ConfigPanel читал `pipelineState.data.file` → при restart dev пусто → Python crash `[Errno 2] No such file or directory: ''`.

**Fix:**
```js
const dataFile = $importData?.file || $pipelineState?.data?.file || '';
if (!dataFile) {
  computeStatus.set('Ошибка: файл данных не найден. Вернитесь на шаг Импорт...');
  return;
}
```

**File:** `src/lib/components/ConfigPanel.svelte:199`

### Fix 2 — check_compiler через vswhere.exe (для future MSVC users)

Даже если PyTensor требует g++, наш `check_compiler()` теперь корректно детектит MSVC через `%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe`, инжектит vcvars64.bat env vars. Для Cython/NumPy compile — работает.

**File:** `sidecar/econometrica/engines/modeler.py:17-95`

### Fix 3 — functools.partial ppc fallback

**Bug:** `pm.sample_posterior_predictive` падает с functools.partial error.

**Fix:** try/except + reconstruct y_pred из posterior means (применяем Hill формулу и control_effect через normalized X_control).

**File:** `sidecar/econometrica/engines/modeler.py:296-370`

### Fix 4 — Не пиклить trace и mmm

**Bug:** `pickle.dump(model_data)` где model_data содержит trace+mmm → functools.partial закрытия в PyTensor → крах.

**Fix:** убрать 'trace' и 'model' из model_data dict. Downstream не использует.

**File:** `sidecar/econometrica/engines/modeler.py:434-448`

### Fix 5 — NumPyro sampler + JAX backend

**File:** `sidecar/econometrica/engines/modeler.py:250-275`
```python
try:
    import numpyro; import jax
    _use_numpyro = True
    logger.info('Using NumPyro NUTS sampler (JAX backend)')
except ImportError:
    logger.warning('NumPyro/JAX not available — falling back to PyTensor NUTS')

if _use_numpyro:
    trace = pm.sample(
        draws=draws, tune=tune, chains=chains,
        return_inferencedata=True, progressbar=True,
        nuts_sampler='numpyro',
        chain_method='vectorized',
    )
else:
    # ...fallback
```

### Fix 6 — Tight priors (Hill funnel)

**File:** `sidecar/econometrica/engines/modeler.py:214-246`

```python
intercept = pm.Normal('intercept', mu=0, sigma=0.5)                    # было sigma=1
media_betas = pm.HalfNormal('media_betas', sigma=0.3, shape=...)       # было 0.5
control_betas = pm.Normal('control_betas', mu=0, sigma=0.3, shape=...) # было 0.5
alphas = pm.Gamma('alphas', alpha=5, beta=3, shape=...)                # было Gamma(3,1)
gammas = pm.Beta('gammas', alpha=3, beta=3, shape=...)                 # было Beta(2,2)
sigma = pm.HalfNormal('sigma', sigma=0.3)                              # было 0.5
# Hill без gamma_scaled (было: gammas[i] * x.max() — нестабильно)
saturated = x_safe ** alphas[i] / (x_safe ** alphas[i] + gammas[i] ** alphas[i] + 1e-10)
```

### Fix 7 — Control normalization

**File:** `sidecar/econometrica/engines/modeler.py:186-208`
```python
# Normalize controls — критично: без этого raw price/budget → y_pred взрывается
if len(control_cols) > 0:
    control_means = X_control.mean()
    control_stds = X_control.std().replace(0, 1)
    X_control_norm = (X_control - control_means) / control_stds
else:
    control_means = pd.Series(dtype=float)
    control_stds = pd.Series(dtype=float)
    X_control_norm = pd.DataFrame()

# In model:
control_effect = pm.math.dot(X_control_norm.values.astype(float), control_betas)

# In pickle normalization dict:
'control_means': control_means.to_dict(),
'control_stds': control_stds.to_dict(),
```

### Fix 8 — File logging в sidecar

**File:** `sidecar/econometrica/server.py:26-60`
```python
_log_dir = Path(os.environ.get('APPDATA', '.')) / 'aurora-econometrica-gui' / 'logs'
_log_dir.mkdir(parents=True, exist_ok=True)
_log_file = _log_dir / f'sidecar-{datetime.now().strftime("%Y-%m-%d")}.log'

_stderr_handler = logging.StreamHandler(sys.stderr)
_file_handler = logging.FileHandler(_log_file, encoding='utf-8', mode='a')
_stderr_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
_file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))

logging.basicConfig(level=logging.INFO, handlers=[_stderr_handler, _file_handler], force=True)

# Startup diagnostic dump
from engines.modeler import check_compiler
logger.info(f'check_compiler() = {check_compiler()}')
logger.info(f'Injected PATH: {os.environ.get("PATH", "")[:300]}')
import pytensor
logger.info(f'pytensor.config.cxx = "{pytensor.config.cxx}"')
```

### Fix 9 — Stop training endpoint

**Backend:** `sidecar/econometrica/server.py:261-271`
```python
@app.post('/compute/train/cancel/{task_id}')
def train_cancel(task_id: str):
    with _training_lock:
        task = _training_tasks.get(task_id)
        if task and task['status'] == 'running':
            task['status'] = 'cancelled'
            task['error'] = 'Обучение остановлено пользователем'
        return {'status': task['status'] if task else 'not_found', 'task_id': task_id}
```

**Rust:** `src-tauri/src/commands/econometrica.rs:74-85` — econ_train_cancel через HTTP POST
**Frontend:** `TrainingProgress.svelte` — кнопка «⏹ Остановить обучение» (красная outline)

### Fix 10 — Time-based progress interpolation

**File:** `src/lib/components/pipeline/TrainingProgress.svelte:45-80`
```js
if (newPhase === 'sampling') {
  if (samplingStartElapsed === null) samplingStartElapsed = elapsedSec;
  const samplingElapsed = elapsedSec - samplingStartElapsed;
  const samplingBudget = Math.max(60, estimatedSec * 0.7);
  const sampleProgress = Math.min(samplingElapsed / samplingBudget, 0.97);
  pct = Math.max(serverPct, Math.round(25 + sampleProgress * 60));
}
```

estimatedSec из ModelTrainingStep:
```js
const estimatedSec = $derived.by(() => {
  if (!lastConfig) return 600;
  const mc = lastConfig.mcmc_override || { chains: 2, draws: 1000, tune: 500 };
  const channels = (lastConfig.media_columns || []).length || 4;
  const totalSamples = (mc.draws + mc.tune) * mc.chains;
  const secPerSample = 0.3 * Math.max(channels / 4, 1);
  return Math.max(60, totalSamples * secPerSample);
});
```

### Fix 11 — MCMC → Markov Chain Monte Carlo (UI strings)

В 6 файлах: ConfigPanel (label + tooltip + status), ModelTrainingStep (2 status), TrainingProgress (phaseLabel), ExpertModelPanel (section-title), insights-rules.js (4 cards).

Причина: терминологическая ясность для enterprise-клиентов (не путать с Markov Chain моделями в MTA).

---

## Files Modified

### Commit `74691f8` (первая часть сессии)
- sidecar/econometrica/engines/modeler.py (check_compiler + vswhere)
- sidecar/econometrica/server.py (train/cancel endpoint)
- src-tauri/src/commands/econometrica.rs + lib.rs (econ_train_cancel)
- src/lib/components/ConfigPanel.svelte (data_file fix, Adstock auto, MSVC hint)
- src/lib/components/pipeline/TrainingProgress.svelte (Stop button, time interp)
- src/lib/components/pipeline/ModelTrainingStep.svelte (handleStop, estimatedSec)
- src/lib/components/pipeline/ExpertModelPanel.svelte (MCMC rename)
- src/lib/insights-rules.js (MCMC rename)
- src/routes/+page.svelte (topbar logo 31→26px)
- static/logo-wordmark.png (Logo_PNG_3-2)
- src-tauri/icons/* (Logo_PNG_4_cuted первая итерация)
- docs/SYSTEM_REQUIREMENTS.md (NEW)
- README.md

### Commit `81d4d21` (финальная часть сессии) — критический
- sidecar/econometrica/engines/modeler.py:
  - Tighter priors (alpha Gamma(5,3), gamma Beta(3,3), beta HalfNormal(0.3))
  - Control normalization (X_control_norm)
  - NumPyro backend selection with fallback
  - try/except вокруг sample_posterior_predictive
  - pickle без trace/mmm
- sidecar/econometrica/server.py:
  - File logging в %APPDATA%/aurora-econometrica-gui/logs/
  - Startup diagnostic dump
- src-tauri/icons/* (Logo_PNG_4_cuted tight, 0% margin)

### 16 иконочных коммитов других приложений (8×Logo_PNG_4 + 8×tight)
`6f10da4 / e6a9419 / 8f0da77 / 9faf9e4 / 0649809 / 8b7f497 / a2b6420 / 58c96be` (Logo_PNG_4)
+ 8 коммитов tight fit.

### Внешние документы (5_Документация/)
- `SYSTEM_REQUIREMENTS_PLATFORM.md` — требования для всех 8 продуктов
- `COMPETITIVE_TAMBURIN.md` — анализ vs Tamburin
- `ROADMAP_SAAS_MIGRATION.md` — стратегия SaaS-перехода

### Obsidian KB (`D:/Docs/Aurora_Ai/KB/`)
- `System_Requirements/` (2 + index)
- `Competitive/` (1 + index)
- `Roadmap/` (1 + index)
Все с frontmatter + wikilinks.

### Memory
- `project_econometrica_session4.md` — детальная сессия
- `project_econometrica_methodology.md` — методология + позиционирование
- `project_econometrica_ols_fallback.md` — OLS fallback task
- `project_econometrica_optimizer_ux.md` — optimizer pending
- `project_econometrica_reports_issues.md` — reports pending
- `project_oracle_media_remote_conflict.md` — git remote conflict
- `MEMORY.md` — индекс

---

## Setup & Config Changes

### Python environment (критично для следующей сессии!)
```bash
pip install numpyro==0.20.1
pip install "jax==0.7.2" "jaxlib==0.7.2"  # НЕ upgrade — 0.10 несовместим с numpyro!
```

Проверка:
```bash
python -c "import jax, numpyro; print('JAX', jax.__version__); print('NumPyro', numpyro.__version__)"
# → JAX 0.7.2 / NumPyro 0.20.1
```

### MSVC Build Tools
- Установлены (v14.44.35207), путь через vswhere.exe
- **НЕ помогают PyTensor** (он требует g++)
- Помогают Cython/NumPy (полезно держать)

### Sidecar logs
- Путь: `%APPDATA%\aurora-econometrica-gui\logs\sidecar-YYYY-MM-DD.log`
- Rotation: per-day, mode='a' (append)
- Формат: `YYYY-MM-DD HH:MM:SS,mmm [LEVEL] logger: message`

### Dev commands
- Start: `cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica && npm run tauri dev`
- Kill python (из PS Админ): `taskkill /F /IM python.exe`
- Check JAX: см. выше

---

## Pending Tasks

### Блокеры релиза (разбираем завтра)

**1. PPTX export падает — `error decoding response body`**
- Root cause: `/export/pptx` в server.py:474 без try/except → HTML 500 → reqwest не парсит
- Fix: try/except wrapper + логирование фаз build_pptx
- Приоритет: critical (MD/XLSX работают, PPTX main client deliverable)
- Est: 1 час
- См. `project_econometrica_reports_issues.md` секция 1

**2. Единая формула спецификации модели в отчётах**
- Отсутствует в MD/XLSX/PPTX
- Нужно: секция «Спецификация» с формулами Hill/Adstock + priors + описание
- Приоритет: важно (клиент doверие)
- Est: 4-6 часов
- См. `project_econometrica_reports_issues.md` секция 2

### UX недоделки Optimizer (~16-24 часа суммарно)

**3. Slider «Общий бюджет» не триггерит recalc**
- Нужен debounce + auto-optimize при изменении
- Est: 1-2 часа

**4. Explanation overlay при +0% прирост**
- Когда модель говорит «всё оптимально» — пользователю непонятно
- Est: 1 час

**5. Scenario Playground UI**
- Код `scenario.py` есть, UI части нет
- Нужен блок: выбор канала + % изменения + таблица сравнения
- Est: 6-8 часов

**6. Смешанные единицы (TRPs vs ₽)**
- TRPs 22,100 пунктов vs рубли в других каналах → ROI 49,122× искажение
- Вариант A (быстро): header-parser + warning
- Вариант B (правильно): группы spend_cols/reach_cols в модели
- Вариант C (production): CPP-нормализация
- Est: 8-12 часов

### UI cosmetic

**7. R² не отображается на Модель и Отчёт**
- Backend считает, теряется в serialize → store → card
- Est: 30 минут

### Стратегические / tech debt

**8. OLS-fallback для <20 точек** (6-8ч, `project_econometrica_ols_fallback.md`)
**9. Prior calibration via lift-tests** — roadmap Q3-Q4 2026
**10. MTA-модуль** (Markov Chains на клик-стрим) — отдельный кабинет
**11. Разрулить Oracle/Media remote conflict** — требует force-push (подтверждение Антона)
**12. Коннекторы к Mediascope/Adfox** — для импорта медиапланов без xlsx
**13. Публичные кейсы** — нужны 3-5 для coverage в СМИ

### Синхронизация в 9 других Aurora-вариантов
После закрытия live-теста — распространить UX-фиксы (Markov Chain Monte Carlo rename, data_file store, Stop button и пр.) в другие кабинеты.

---

## Errors & Workarounds

### E1 — Python NUTS застрял на 15+ мин sampling

**Симптом:** модель не завершается даже за 20+ мин. CPU 4.2% (Python single-thread).

**Root cause:** PyTensor на Windows по умолчанию использует Python fallback (нет g++).

**Workaround:** JAX/NumPyro backend (см. Fix 5).

### E2 — `'functools.partial' object has no attribute '__name__'`

**Возникает в:** `pm.sample_posterior_predictive`, `arviz.summary`, `pickle.dump(model)`.

**Root cause:** PyTensor closures с functools.partial без `__name__` attribute. Либо Metropolis CompoundStep, либо pickle PyMC model graph.

**Workarounds:**
1. Не пиклить mmm/trace (Fix 4)
2. try/except ppc + manual y_pred (Fix 3)
3. NUTS через JAX не создаёт CompoundStep → ошибка не возникает

### E3 — R² = -86 миллиардов %

**Root cause:** X_control не нормализован → control_effect в миллиарды → y_pred_norm взрывается → y_pred = huge × y_std + y_mean = astronomical.

**Fix:** control normalization (Fix 7).

### E4 — 1658 divergences после NUTS

**Root cause:** Hill priors `alphas Gamma(3,1) + gammas Beta(2,2)` создают funnel geometry. NUTS не может адаптировать step-size.

**Fix:** tight priors + без `gamma_scaled` (Fix 6).

### E5 — JAX 0.10 несовместима с NumPyro 0.20.1

**Симптом:** `ImportError: cannot import name 'xla_pmap_p' from 'jax.extend.core.primitives'`

**Fix:** пинить `jax==0.7.2 jaxlib==0.7.2`.

### E6 — 11 повисших python.exe процессов

**Симптом:** после live-теста накапливаются зомби-процессы MCMC (Metropolis не убивается корректно).

**Workaround:** `taskkill /F /IM python.exe` из **PowerShell от Админа**. Non-admin → «Отказано в доступе».

### E7 — Git Bash single-slash args

**Симптом:** `taskkill /F /IM python.exe` → `Ошибка: Неправильный параметр или аргумент - 'F:/'`

**Workaround:** `taskkill //F //IM python.exe` (двойной слеш) ИЛИ отдельный PowerShell.

### E8 — Tauri dev watcher убивает sidecar при icon regen

**Симптом:** `npx tauri icon` во время активного dev → rebuild → sidecar kill → live-test прерван.

**Workaround:** не запускать операции в src-tauri/ во время live-test. Делать с остановленным dev.

### E9 — PPTX export "error decoding response body"

**Симптом:** при нажатии «Презентация (PPTX)» на шаге Отчёт → ошибка парсинга HTTP response.

**Root cause:** `/export/pptx` без try/except → python exception → FastAPI HTTP 500 с HTML error page → reqwest ждёт JSON → decode fail.

**Workaround (pending):** try/except wrapper в server.py с JSONResponse error. См. `project_econometrica_reports_issues.md`.

### E10 — Optimizer `Singular matrix C` и `Iteration limit reached`

**Симптом:** в логе sidecar `Optimization did not converge` несколько раз.

**Root cause:** scipy optimizer не сходится когда все каналы в Hill saturation plateau (mROAS=0).

**Workaround:** это data issue (TRPs в пунктах), не backend. Фиксится когда разрулим смешанные единицы.

---

## Full Session Notes

### Хронология (30+ шагов за день)

1. Подхват контекста из предыдущей session log (`2026-04-18-2330`)
2. Замена header logo на Logo_PNG_3-2, итеративный подбор размера (31→36→29→26px)
3. Распространение header-logo фикса на 8 других приложений + commit + push
4. Первый запуск модели → ошибка `[Errno 2] No such file or directory`
5. **Fix 1:** data_file store рассинхрон (importData vs pipelineState)
6. Adstock default 'auto' + предупреждение о файле
7. Второй запуск модели → 20+ мин на 25%, выглядит как зависание
8. **Fix 10:** time-based progress interpolation на фронте
9. **Fix 9:** Stop training endpoint + Rust + UI кнопка
10. Первый крах: functools.partial после 16 мин обучения
11. **Fix 2:** vswhere.exe + vcvars64.bat для детекции MSVC
12. 11 повисших python.exe → taskkill + перезапуск
13. **Incident:** tauri icon во время активного live-test → убил sidecar (Logo_PNG_1)
14. Icon regen Logo_PNG_4_cuted (только пирамида, без текста)
15. Создание `SYSTEM_REQUIREMENTS.md` (платформа + econometrica)
16. WebSearch Tamburin → `COMPETITIVE_TAMBURIN.md`
17. Вопрос про SaaS-миграцию → `ROADMAP_SAAS_MIGRATION.md`
18. MCMC → Markov Chain Monte Carlo rename
19. Объяснение методологии Bayesian MMM + MCMC Антону
20. Obsidian KB sync (4 файла + 3 index)
21. Memory updates (session4, methodology, ols_fallback)
22. **Первый большой коммит** `74691f8`
23. Снова NUTS не детектился → глубокая диагностика check_compiler
24. **Ключевое открытие:** PyTensor требует g++, не MSVC
25. Обсуждение MinGW vs JAX → выбор JAX
26. Install jax 0.10 → JAX/NumPyro version mismatch
27. Downgrade to jax 0.7.2 → совместимость
28. NumPyro sampler работает: 5-секундное sampling
29. НО: Divergences=0, R-hat>4, R² = -86 млрд % (огромный overflow)
30. **Fix 6:** tight priors (Gamma(5,3), Beta(3,3)) → 0 divergences
31. **Fix 7:** control normalization → R² становится положительным
32. **Final victory:** MQS=95.6, R-hat<1.01, фит идеальный
33. Декомпозиция: waterfall + insights + таблица детализации + Share of Spend vs Effect
34. Оптимизация: +0.0% (все каналы на plateau — ожидаемо на искажённых TRPs)
35. Feedback: Optimizer slider не recalc, сценарии непонятны
36. Отчёт: MD ✅, XLSX ✅, PPTX ❌ `error decoding response body`
37. Feedback: в отчётах нет формулы спецификации модели
38. **Финальный коммит** `81d4d21` + 8 иконочных коммитов tight fit
39. Memory final updates (optimizer_ux, reports_issues)
40. Компрессия (этот документ)

### Скриншоты (ключевые)

- Home с hero logo + 3 кнопками ✅
- Validation success (ratio 2.38:1) ✅
- Model Expert с per-channel Adstock ✅
- TrainingProgress с Stop button (красная) ✅
- Error banner «functools.partial» (решён)
- Error banner `[Errno 2] ''` (решён)
- Model complete: MQS 95.6, Факт vs Прогноз идеальный фит ✅
- Decompose: waterfall 3.37B→11.23B + 6 channels
- Decompose: tooltip с разбивкой по датам (2025-02-01 = 562.9M)
- Detail таблица: ROI, Gap, Вердикты
- Optimizer: response curves + mROAS = 0 (plateau)
- Report: 3 кнопки экспорта (MD/XLSX/PPTX)
- Error banner PPTX: «error decoding response body»

### Commits (summary)

```
Econometrica:
  74691f8 feat(econometrica): NUTS detection via vswhere, MCMC UX polish, system docs
  81d4d21 feat(econometrica): JAX backend + tight priors + file logging + icons tight

Other 8 apps (Logo_PNG_4 round 1):
  6f10da4 (Creative_Hub) e6a9419 (Oracle) 8f0da77 (Parser) 9faf9e4 (PR_Master)
  0649809 (Creative) 8b7f497 (DocMaster) a2b6420 (Legal) 58c96be (Media)

Other 8 apps (tight icons round 2):
  [8 новых коммитов с tight fit]
```

**Итого:** 18 коммитов за сессию.

### Memory final state

- `project_econometrica_session4.md` — детальная сессия (этот compress дополняет)
- `project_econometrica_methodology.md` — Bayesian MMM + позиционирование
- `project_econometrica_ols_fallback.md` — OLS fallback task (6-8ч pending)
- `project_econometrica_optimizer_ux.md` — optimizer pending (4 задачи 16-24ч)
- `project_econometrica_reports_issues.md` — reports pending (3 задачи)
- `project_oracle_media_remote_conflict.md` — git remote conflict
- `MEMORY.md` — проиндексирован всеми ссылками

### Следующая сессия (завтра)

Читай:
1. `MEMORY.md` → `project_econometrica_session4.md`
2. Этот compress log
3. `project_econometrica_reports_issues.md`
4. `project_econometrica_optimizer_ux.md`

Начни с:
1. PPTX fix (1 час — блокер для релиза)
2. R² в UI (30 мин — cosmetic quick win)
3. Единая формула спецификации (4-6 часов — клиенту важно)
4. Optimizer UX (решить в каком порядке — 16-24 часа суммарно)

**Среда:** JAX 0.7.2 + NumPyro 0.20.1 — не трогай версии!
**При проблемах sidecar:** taskkill /F /IM python.exe + restart dev
**Логи:** `%APPDATA%\aurora-econometrica-gui\logs\sidecar-YYYY-MM-DD.log`
