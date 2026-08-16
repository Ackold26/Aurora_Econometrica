"""Methodology Certificate — hash generation for Aurora MMM Optimizer.

Computes a cryptographic hash (SHA-256 over JCS RFC 8785 canonical JSON) that
covers the full methodology payload for a completed MMM run. The hash is
embedded in the exported HTML report and bundle manifest so that
`verify.auroraai.pro` (Rust WASM, aurora-platform-core/c7-web-verifier) can
independently verify the model artefacts haven't been tampered with.

INV-06 compliance: JCS RFC 8785 (`rfc8785` package) is used for bit-stable
canonical serialization — Pydantic / json.dumps key ordering are NOT used for
the cryptographic payload (see feedback_jcs_canonical_hash.md).

### Certificate versioning (additive, ADR-017 / ADR-019)

- `certificate_version` field signals which fields are covered by the hash.
- v1.3.x verifier: ignores unknown fields, verifies only v1.3.x payload subset.
- v2.0.0 verifier: full payload (v1.3.x fields + v2.0.0 additive fields).
- Old certificates (absent `certificate_version`): treated as "1.3" by verifier.

### Backward-compat contract (ADR-017 additive schema)

v1.3.x model → `build_cert_payload()` returns v1.3.x-only fields + a
`certificate_version: "1.3"` tag (no v2.0.0 fields included). The resulting
hash equals what the old verifier expects.

v2.0.0 model → full payload including v2.0.0 fields + `certificate_version:
"2.0.0"`. Old verifier ignores v2.0.0 fields (per ADR-017) and verifies v1.3.x
subset; new verifier verifies full payload.

Usage:
    from engines.methodology_cert import build_cert_payload, compute_cert_hash

    payload = build_cert_payload(model_data, decompose_result, bundle_manifest)
    cert_hash = compute_cert_hash(payload)
    # Embed cert_hash in bundle/manifest.json + HTML report header.

Reference:
    docs/v2_0_0_design/PRE_FLIGHT_FIXES.md §N7 (Methodology Certificate schema)
    docs/v2_0_0_design/VERIFIER_SCHEMA_v2.md (verifier-side spec)
    ENGINEERING_INVARIANTS.md §INV-06 (JCS canonical hash)
    ADR-019 §11 (Phase E5)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Current certificate version ──────────────────────────────────────────────

CERT_VERSION_V13 = "1.3"
CERT_VERSION_V20 = "2.0.0"


class CertificateUnavailable(Exception):
    """Сертификат выдать нельзя — названа причина.

    Поднимается вместо возврата хеша, который заведомо не сойдётся у
    проверяющей стороны, и вместо подстановки нуля на месте отсутствующей
    величины. Вызывающий обязан поймать и отдать статус, а не уронить расчёт.
    """


# ── Canonical serialization (INV-06) ─────────────────────────────────────────

def compute_cert_hash(payload: dict[str, Any]) -> str:
    """SHA-256 над JCS-канонизацией payload (RFC 8785).

    🔴 Отказ вместо неверного хеша. Прежняя версия при отсутствии `rfc8785`
    тихо откатывалась на `json.dumps(sort_keys=True)` и печатала
    предупреждение в журнал — то есть выдавала хеш, который **заведомо** не
    сходится у `verify.auroraai.pro` (Rust `serde_jcs`). Клиент получал бы
    сертификат, не проходящий проверку, и узнал бы об этом только на стороне
    проверяющего. Теперь канонизация одна на весь продукт —
    `utils/canonical_hash.py`, и она сама поднимает `ImportError`, если пакета
    нет.

    Raises:
        CertificateUnavailable: канонизация недоступна (нет `rfc8785`).
    """
    from utils.canonical_hash import compute_project_hash
    try:
        return compute_project_hash(payload)
    except ImportError as exc:
        raise CertificateUnavailable(
            'Канонизация JCS недоступна: пакет rfc8785 не установлен. '
            'Сертификат не выдан – хеш без канонизации не сошёлся бы '
            'у проверяющей стороны.'
        ) from exc


# ── Payload builders ──────────────────────────────────────────────────────────

def _extract_v13_payload(
    model_data: dict[str, Any],
    decompose_result: dict[str, Any],
    bundle_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Extract v1.3.x hash payload fields (preserved exactly for compat).

    These fields are the ones the existing verify.auroraai.pro verifier knows
    about. They MUST stay byte-identical between v1.3.x and v2.0.0 certificates
    so that old verifiers can still verify v2.0.0 certificates via the v1.3
    subset.

    Fields:
        bundle_manifest_hash: SHA-256 канонизации манифеста **файла обученной
            модели** (формат `aurora-model`, `persistence_safe.read_manifest`):
            формат, версия формата, время создания, `model_version`,
            `sha256_data`, `sha256_arrays`. 🔴 Имя поля унаследовано от
            «бандла» — директории выгрузки данных с `manifest.json`, которая в
            продукте так и не была построена (`PRE_FLIGHT_FIXES §N7` её
            закладывал; свип по коду даёт ноль упоминаний вне этого модуля).
            Решение владельца 2026-08-03: поле наполняется манифестом файла
            модели — реальным артефактом со списком контрольных сумм, а не
            пустой строкой. Клиентский текст обязан говорить прямо: сертификат
            покрывает **файл модели**, а не выгрузку данных.
        model_spec: тип KPI, вид правдоподобия, число каналов, типы адстока.
            Апостериорные выборки не включаются (они в файле модели).
        decomposition_summary: вклад по категориям — база и каналы. Доли
            считаются от ОБЩИХ продаж, единообразно: в ответе декомпозера
            `baseline_pct` считается от общих продаж, а `contribution_pct`
            канала — от медиавклада (`decomposer.py:1058`), и смешивать две
            базы под одним именем нельзя.
        channel_roi: ROI по каналам. Границы включаются только когда обе
            присутствуют: подставленный ноль утверждал бы «нижняя граница
            ROI равна нулю», чего расчёт не говорил.

    Raises:
        CertificateUnavailable: отсутствует величина, без которой сертификат
            стал бы набором подстановок.
    """
    # ── bundle_manifest_hash ────────────────────────────────────────────────
    # Вызывающий читает манифест сам (`persistence_safe.read_manifest`) — модуль
    # не ходит в файловую систему, чтобы оставаться проверяемым на словарях.
    clean_manifest = {k: v for k, v in (bundle_manifest or {}).items()
                      if not str(k).startswith('_cert')}
    if not clean_manifest:
        raise CertificateUnavailable(
            'Манифест файла модели недоступен – сертификату не к чему '
            'привязаться. Файл модели старого формата либо повреждён.'
        )
    bundle_hash = compute_cert_hash(clean_manifest)

    # ── model_spec ──────────────────────────────────────────────────────────
    # Диагностика у моделей, обученных до v2.0.0, пуста (замер 2026-08-03: у всех
    # четырёх клиентских моделей `diagnostics` == {}), поэтому сборка из полей
    # модели — основной путь, а не запасной. Дефолтов нет: отсутствие типа KPI
    # или вида правдоподобия означает, что модель нечем описать.
    # 🔴 Внешний аудит блока, F-01 Critical: читать описание модели из
    # `model_data` НЕЛЬЗЯ. `load_model_with_compat` подставляет туда
    # `kpi_type='sales'` и `kpi_likelihood='normal'` (`persistence.py:191-192`)
    # ДО того, как сертификат проверит наличие полей, — то есть проверка
    # «нет величины → отказ» не срабатывала никогда, а в хеш уезжала
    # подстановка. У модели режима малых данных (OLS) верхнеуровневых полей нет
    # вовсе, и модель, обученная на знании марки, заверялась как модель продаж.
    # Настоящее значение живёт в конфигурации обучения.
    diagnostics = model_data.get('diagnostics') or {}
    model_spec_raw = diagnostics.get('model_spec') or {}
    if not model_spec_raw:
        config = model_data.get('config') or {}
        это_ols = str(model_data.get('model_version') or '').endswith('ols')
        # Конфигурация обучения — первичный источник: там лежит то, что выбрал
        # пользователь. Запись самого обучения (`modeler.py:1696`) — законный
        # запасной путь для байесовской ветки: она пишет фактически применённое
        # значение, и если пользователь тип не задавал, обучение и расчёт шли по
        # одному и тому же значению. А вот у режима малых данных обучение
        # верхний уровень не пишет вовсе — там всё, что видно, подставил
        # загрузчик, и доверять ему нельзя (в этом и была находка F-01).
        kpi_type = config.get('kpi_type')
        if not kpi_type and not это_ols:
            kpi_type = model_data.get('kpi_type')
        if not kpi_type:
            raise CertificateUnavailable(
                'В конфигурации модели нет типа целевой метрики. Подставлять '
                'значение по умолчанию нельзя – сертификат описывал бы не ту '
                'модель, которую обучили.'
            )
        model_spec_raw = {
            'kpi_type': str(kpi_type),
            'num_channels': len(model_data.get('channel_params') or {}),
        }

        # Вид правдоподобия существует только у байесовской ветки: закрытая
        # формула МНК его не использует, и печатать «normal» для неё значило бы
        # описывать модель, которой нет.
        if not str(model_data.get('model_version') or '').endswith('ols'):
            likelihood = config.get('kpi_likelihood') or model_data.get('kpi_likelihood')
            if likelihood:
                model_spec_raw['kpi_likelihood'] = str(likelihood)

        # F-09: карта адстоков заполняется ФАКТИЧЕСКИ применёнными типами.
        # 🔴 Аудит починки, Ф-01 High: первая версия достраивала её через
        # `persistence.get_adstock_type`, а тот читает ровно ту же пустую карту
        # и отдаёт `geometric` ВСЕМ каналам. У модели режима малых данных карты
        # не бывает никогда — значит в хеш всегда уезжал бы `geometric`, даже
        # когда пользователь выбрал Вейбулла и расчёт шёл по Вейбуллу. То есть
        # починка сама сделала ровно то, ради чего чинили F-01: подставила
        # умолчание в заверенное описание модели.
        # Настоящее значение лежит в двух местах, оба независимы от карты.
        # ⚠️ Долг продукта (зонд 2026-08-03): модель хранит НАСТРОЙКУ, а не
        # результат её применения — на реальных проектах здесь стоит `'auto'`,
        # и фактически применённый тип (геометрический по откату) нигде не
        # записан. Сертификат отражает записанное и не домысливает: вывести тип
        # из пустоты весовых параметров значило бы вернуть ту самую подстановку.
        # Лечение — чтобы обучение сохраняло разрешённый тип рядом с настройкой.
        # 🔴 Аудит хвоста блока, High: в карту допускаются только НАСТОЯЩИЕ типы.
        # На реальных проектах и в конфигурации, и в параметрах каналов стоит
        # `'auto'` — это настройка «выбери сам», а не тип: движок такого типа не
        # знает и молча считает по геометрическому (`utils/adstock.py:95-107`).
        # Прежняя версия клала `'auto'` в хешируемое описание под именем
        # «фактически применённый тип» — то есть заверяла настройку вместо
        # факта, третий раз тот же класс, что F-01 и Ф-01.
        ИЗВЕСТНЫЕ_АДСТОКИ = ('geometric', 'weibull')
        adstock_types = {
            str(канал): str(тип)
            for канал, тип in (model_data.get('channel_adstock_types') or {}).items()
            if str(тип) in ИЗВЕСТНЫЕ_АДСТОКИ
        }
        if not adstock_types:
            из_конфига = dict((config.get('adstock_config') or {}))
            параметры = model_data.get('channel_params') or {}
            восстановленные: dict[str, str] = {}
            for канал, параметр in параметры.items():
                тип = из_конфига.get(канал)
                if not тип and isinstance(параметр, dict):
                    тип = ((параметр.get('adstock') or {}).get('type')
                           if isinstance(параметр.get('adstock'), dict) else None)
                if тип and str(тип) in ИЗВЕСТНЫЕ_АДСТОКИ:
                    восстановленные[str(канал)] = str(тип)
            # Ключ не кладётся вовсе, если тип известен не для всех каналов:
            # частичная карта утверждала бы об остальных то, чего мы не знаем.
            if восстановленные and len(восстановленные) == len(параметры):
                adstock_types = восстановленные
        if adstock_types:
            model_spec_raw['adstock_types'] = adstock_types

    # ── decomposition_summary ───────────────────────────────────────────────
    # 🔴 Прежний код итерировал `waterfall` как список словарей с ключом
    # `category`, а декомпозер отдаёт `{labels, values, types}`
    # (`decomposer.py:1410-1414`): обход дал бы строки вместо словарей и упал
    # бы на `item.get`. Ещё одно доказательство, что модуль не вызывался ни разу.
    total_sales = decompose_result.get('total_sales')
    baseline = decompose_result.get('baseline')
    channels_raw = decompose_result.get('channels') or []
    if total_sales in (None, 0) or baseline is None or not channels_raw:
        raise CertificateUnavailable(
            'Результат декомпозиции неполон (нет общих продаж, базы или '
            'каналов) – заверять нечего.'
        )
    total_sales = float(total_sales)
    if total_sales != total_sales or total_sales in (float('inf'), float('-inf')):
        raise CertificateUnavailable(
            'Итог по целевой метрике – не число, заверять такую разбивку нельзя.'
        )

    def _конечное(значение: Any, что: str) -> float:
        """Число или отказ с человеческой причиной.

        🔴 Аудит F-08: канонизация RFC 8785 не умеет `nan`/`inf` и поднимает
        свою ошибку, которая до правки уезжала клиенту в отчёт технической
        строкой («Сертификат не удалось собрать: FloatDomainError»). Вырожденный
        канал в продукте — известный случай, ради него живёт `sanitize_nonfinite`.
        """
        число = float(значение)
        if число != число or число in (float('inf'), float('-inf')):
            raise CertificateUnavailable(
                f'{что} – не число, заверять такую разбивку нельзя. '
                f'Проверьте данные канала: расчёт мог не сойтись.'
            )
        return число

    def _pct_of_total(value: float) -> float:
        return round(value / float(total_sales) * 100, 2)

    КЛЮЧ_БАЗЫ = 'Base'
    decomp_summary: dict[str, Any] = {
        КЛЮЧ_БАЗЫ: {
            'value': _конечное(baseline, 'Базовый уровень'),
            'contribution_pct': _pct_of_total(_конечное(baseline, 'Базовый уровень')),
        }
    }
    for ch in channels_raw:
        name = ch.get('name')
        contribution = ch.get('contribution')
        if not name or contribution is None:
            raise CertificateUnavailable(
                'В разбивке есть канал без имени или без вклада – '
                'заверять неполную разбивку нельзя.'
            )
        # 🔴 Аудит F-07: имя канала приходит из столбца пользовательской
        # таблицы. Совпадение с ключом базы затирало её запись целиком, и в
        # хеш уезжала сводка, где под словом «Base» стоит число канала —
        # неверное число под верным именем, без единого предупреждения.
        if str(name) == КЛЮЧ_БАЗЫ:
            raise CertificateUnavailable(
                f'Канал назван «{КЛЮЧ_БАЗЫ}» – этим именем в сертификате '
                f'обозначается базовый уровень. Переименуйте столбец, иначе '
                f'заверенная разбивка окажется неверной.'
            )
        вклад = _конечное(contribution, f'Вклад канала «{name}»')
        decomp_summary[str(name)] = {
            'value': вклад,
            'contribution_pct': _pct_of_total(вклад),
        }

    # ── channel_roi ─────────────────────────────────────────────────────────
    channel_roi: dict[str, Any] = {}
    for ch in channels_raw:
        roi = ch.get('roi')
        if roi is None:
            # Режим эффективности и счётный KPI без стоимости единицы дают
            # разбивку без ROI — это законно, канал просто не попадает в раздел.
            continue
        # 🔴 Аудит F-04: канал без бюджета либо без обучаемой дисперсии получает
        # от декомпозера `roi = 0.0` и маркер неприменимости — но расчёт не
        # утверждал, что окупаемость нулевая, он утверждал, что она НЕ
        # ОПРЕДЕЛЕНА. В сочетании `zero_spend` туда же дописывались границы
        # `[0; 0]`, которых модель не считала. В сводке вкладов такой канал
        # остаётся (нулевой вклад — факт), а в разделе окупаемости его нет.
        if ch.get('ci_skip_reason'):
            continue
        имя_канала = ch.get('name')
        entry: dict[str, Any] = {
            'roi': _конечное(roi, f'Окупаемость канала «{имя_канала}»'),
        }
        ci_low = ch.get('roi_ci_low')
        ci_high = ch.get('roi_ci_high')
        if ci_low is not None and ci_high is not None:
            entry['roi_ci_low'] = _конечное(ci_low, f'Нижняя граница по каналу «{имя_канала}»')
            entry['roi_ci_high'] = _конечное(ci_high, f'Верхняя граница по каналу «{имя_канала}»')
        channel_roi[str(ch.get('name'))] = entry

    return {
        'bundle_manifest_hash': bundle_hash,
        'model_spec': model_spec_raw,
        'decomposition_summary': decomp_summary,
        'channel_roi': channel_roi,
    }


def _extract_v20_fields(
    model_data: dict[str, Any],
    decompose_result: dict[str, Any],
) -> dict[str, Any]:
    """Extract v2.0.0 additive fields for the certificate hash payload.

    These fields are ADDITIVE to the v1.3.x payload. A v1.3.x verifier that
    doesn't know about them will skip them per ADR-017 additive schema; a
    v2.0.0 verifier includes them in the hash check.

    Fields per PRE_FLIGHT_FIXES §N7 + task spec:
        analysisMode: 'roi' | 'effectiveness' | 'mixed'
        signed_factor_contributions: full per-factor breakdown from decomposer
        holiday_dummies_injected: list of 12 РФ holiday event names present in
            training dataset (subset of the 12 hardcoded holidays from modeler.py)
        mcmc_diagnostics: r_hat_max, ess_min (convergence indicators)
        backtest_results: mape, rmse, r2 (holdout validation)
        ppc_results: r2, durbin_watson (posterior predictive check)
    """
    # analysisMode — recorded at train time (ADR-019 §1). Default 'roi' if
    # absent (pre-v2.0.0 pickle migrated into default per _inject_v20_defaults).
    analysis_mode = str(model_data.get('analysis_mode') or 'roi')

    # signed_factor_contributions — full breakdown from decomposer v2.0.0 output.
    # Key: factor name. Value: {value, pct, type, beta_mean}.
    # If decompose_result doesn't include signed_factors (v1.3.x decomposer),
    # fall back to reconstructing from model_data.normalization.
    signed_factors_raw = decompose_result.get('signed_factor_contributions') or {}
    if not signed_factors_raw:
        # Fallback reconstruction from control betas (same logic as json_export.py).
        norm = model_data.get('normalization') or {}
        control_cols = (model_data.get('config') or {}).get('control_columns') or []
        control_betas_mean = norm.get('control_betas_mean') or []
        if len(control_betas_mean) == len(control_cols):
            try:
                from utils.column_detection import classify_column  # type: ignore[import]
                for i, col in enumerate(control_cols):
                    kind = classify_column(col)
                    if kind in ('signed_competitor', 'signed_price', 'signed_weather',
                                'signed_macro', 'holiday'):
                        signed_factors_raw[str(col)] = {
                            'beta_mean': float(control_betas_mean[i]),
                            'type': kind,
                        }
            except Exception as exc:
                logger.warning('Signed factor reconstruction failed for cert: %s', exc)

    # Normalize: ensure all values are plain Python types (no numpy floats).
    signed_factors_cert: dict[str, Any] = {}
    for factor_name, factor_data in signed_factors_raw.items():
        signed_factors_cert[str(factor_name)] = {
            k: (float(v) if isinstance(v, (int, float)) else
                [float(x) for x in v] if isinstance(v, list) else str(v))
            for k, v in (factor_data or {}).items()
        }

    # holiday_dummies_injected — list of holiday dummy column names present in
    # training data (from persistence._inject_v20_defaults or set at train time).
    holidays_raw = model_data.get('holiday_dummies_injected') or []
    holidays_cert = sorted(str(h) for h in holidays_raw)  # sorted for JCS stability

    # mcmc_diagnostics — r_hat_max + ess_min summary.
    mcmc_raw = model_data.get('mcmc_diagnostics') or {}
    if isinstance(mcmc_raw, dict):
        mcmc_cert: dict[str, Any] = {
            'r_hat_max': float(mcmc_raw.get('r_hat_max') or 0),
            'ess_min': float(mcmc_raw.get('ess_min') or 0),
        }
    else:
        mcmc_cert = {'r_hat_max': 0.0, 'ess_min': 0.0}

    # backtest_results — summary metrics only (not per-period predictions, те
    # слишком большие для cert payload и не нужны для verification).
    backtest_raw = model_data.get('backtest_results') or {}
    if isinstance(backtest_raw, dict):
        metrics_raw = backtest_raw.get('metrics') or backtest_raw  # supports nested or flat
        backtest_cert: dict[str, Any] = {
            'mape': float(metrics_raw.get('mape') or metrics_raw.get('mape_pct') or 0),
            'rmse': float(metrics_raw.get('rmse') or 0),
            'r2': float(metrics_raw.get('r2') or metrics_raw.get('r_squared') or 0),
        }
    else:
        backtest_cert = {'mape': 0.0, 'rmse': 0.0, 'r2': 0.0}

    # ppc_results — r2 + durbin_watson summary.
    ppc_raw = model_data.get('ppc_results') or {}
    if isinstance(ppc_raw, dict):
        ppc_cert: dict[str, Any] = {
            'r2': float(ppc_raw.get('r2') or ppc_raw.get('r_squared') or 0),
            'durbin_watson': float(ppc_raw.get('durbin_watson') or ppc_raw.get('residual_durbin_watson') or 0),
        }
    else:
        ppc_cert = {'r2': 0.0, 'durbin_watson': 0.0}

    return {
        'analysisMode': analysis_mode,
        'signed_factor_contributions': signed_factors_cert,
        'holiday_dummies_injected': holidays_cert,
        'mcmc_diagnostics': mcmc_cert,
        'backtest_results': backtest_cert,
        'ppc_results': ppc_cert,
    }


def build_cert_payload(
    model_data: dict[str, Any],
    decompose_result: dict[str, Any],
    bundle_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build the full Methodology Certificate hash payload.

    Detects whether the model is v2.0.0 or v1.3.x (via `is_v20_compatible()`)
    and includes the corresponding fields.

    Args:
        model_data: loaded model dict from `persistence.load_model_with_compat()`.
        decompose_result: decomposer output dict (from `decomposer.decompose()`).
        bundle_manifest: bundle manifest dict (from manifest.json). May include
            `_cert_bundle_hash` pre-computed by caller (Rust side or Python
            bundle writer).

    Returns:
        Payload dict ready for `compute_cert_hash()`. Also returned to caller
        so it can be embedded in the bundle for transparency.
    """
    # Base v1.3.x payload (always present regardless of version).
    payload = _extract_v13_payload(model_data, decompose_result, bundle_manifest)

    # Detect v2.0.0 compatibility (uses persistence helper or fallback heuristic).
    try:
        from engines.persistence import is_v20_compatible  # type: ignore[import]
        is_v20 = is_v20_compatible(model_data)
    except ImportError:
        # Fallback: check model_version string directly.
        model_ver = str(model_data.get('model_version') or '1.3')
        is_v20 = model_ver.startswith('2.')

    if is_v20:
        # 🔴 ВЕТКА НЕДОСТИЖИМА И СЛОМАНА ПО КОНТРАКТУ — оставлена как есть,
        # решение о ней за владельцем (зонды 2026-08-03):
        #   1. Недостижима: `model_version` при обучении равен '1.2'/'1.3'
        #      (`modeler.py:1673`), до '2.0.0' его поднимает только
        #      `save_v20_diagnostics`, у которой нет ни одного живого
        #      вызывающего. У всех четырёх клиентских моделей на машине —
        #      '1.2', то есть `is_v20_compatible` всегда False.
        #   2. Сломана: ключ режима кладётся как `analysisMode` (строка ниже),
        #      а парсер проверяющей стороны объявлен как `analysis_mode` без
        #      переименования (`docs/v2_0_0_design/VERIFIER_SCHEMA_v2.md:227`) —
        #      при десериализации поле выпадает, пересериализация даёт другой
        #      payload, и хеш не сойдётся НИКОГДА.
        # Чинить написание — правка внешнего контракта; без ответа проверяющей
        # стороны схему не трогаем (шаг 13 плана P0.7).
        payload.update(_extract_v20_fields(model_data, decompose_result))
        payload['certificate_version'] = CERT_VERSION_V20
    else:
        # v1.3.x certificate — no v2.0.0 additive fields.
        payload['certificate_version'] = CERT_VERSION_V13

    return payload


def generate_methodology_certificate(
    model_data: dict[str, Any],
    decompose_result: dict[str, Any],
    bundle_manifest: dict[str, Any],
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a complete Methodology Certificate dict for embedding in bundle.

    This is the top-level entry point. Returns a dict containing:
        - `payload`: the full hash payload (for transparency / embed in report)
        - `hash`: SHA-256 hex of JCS-canonical payload
        - `certificate_version`: "1.3" or "2.0.0"
        - `jcs_available`: bool — True if rfc8785 was used (INV-06 compliance)

    Args:
        model_data: loaded model dict.
        decompose_result: decomposer output dict.
        bundle_manifest: bundle manifest dict.

    Returns:
        {
            "status": "issued" | "not_attested" | "unavailable",
            "reason": <строка, если статус не issued>,
            "payload": {...},            # входит в хеш
            "hash": "abc123...",
            "certificate_version": "1.3",
            "reproducibility": {...},    # ВНЕ хеша
            "checks": {...},             # ВНЕ хеша
        }

    🔴 Всё, что не входит в схему v1.3, лежит **рядом** с payload, а не внутри
    него: проверяющая сторона десериализует payload в свою структуру и
    пересериализует, и незнакомый ключ на любом уровне выпадает — хеш перестаёт
    сходиться. Поэтому паспорт воспроизводимости и статусы проверок в payload
    не кладутся.
    """
    reproducibility = _extract_reproducibility(model_data)
    checks = _extract_checks(model_data, diagnostics)
    data_fingerprint = _extract_data_fingerprint(model_data)
    adstock_protocol = _extract_adstock_protocol(model_data)
    repro_tolerance = _extract_repro_tolerance(reproducibility)

    try:
        payload = build_cert_payload(model_data, decompose_result, bundle_manifest)
        cert_hash = compute_cert_hash(payload)
    except CertificateUnavailable as exc:
        # Расчёт не роняем: клиент получает разбивку и честную причину, почему
        # заверения нет.
        logger.warning('Сертификат методологии не выдан: %s', exc)
        return {
            'status': 'unavailable',
            'reason': str(exc),
            'payload': None,
            'hash': None,
            'certificate_version': CERT_VERSION_V13,
            'reproducibility': reproducibility,
            'checks': checks,
            'data_fingerprint': data_fingerprint,
            'adstock_protocol': adstock_protocol,
            'repro_tolerance': repro_tolerance,
        }

    # Модель, обученная до появления паспорта воспроизводимости (P0.2), заверить
    # полноценно нельзя: зерно сэмплера не записано, повторить прогон
    # побитово невозможно. Хеш при этом честен для тех полей, что есть, —
    # поэтому статус, а не отказ.
    # Заверение полное в двух случаях: паспорт записан (байесовская ветка) либо
    # расчёт детерминирован по построению (закрытая формула, аудит F-02).
    attested = reproducibility.get('status') in ('recorded', 'deterministic')

    return {
        'status': 'issued' if attested else 'not_attested',
        'reason': None if attested else (
            'Модель обучена до появления паспорта воспроизводимости: зерно '
            'сэмплера не записано, побитовое повторение прогона не '
            'гарантируется. Переобучите модель, чтобы получить полное заверение.'
        ),
        'payload': payload,
        'hash': cert_hash,
        'certificate_version': payload.get('certificate_version', CERT_VERSION_V13),
        'reproducibility': reproducibility,
        'checks': checks,
        'data_fingerprint': data_fingerprint,
        'adstock_protocol': adstock_protocol,
        'repro_tolerance': repro_tolerance,
    }


def _extract_reproducibility(model_data: dict[str, Any]) -> dict[str, Any]:
    """Паспорт воспроизводимости — вне хеша, для клиента.

    Источник — `model_data['reproducibility']` (`modeler.py:1608`), запасной —
    та же копия в диагностике (`modeler.py:1380`). У моделей, обученных до
    P0.2, паспорта нет вовсе: статус `absent`.
    """
    snapshot = model_data.get('reproducibility')
    if not isinstance(snapshot, dict) or not snapshot:
        diag = model_data.get('diagnostics') or {}
        snapshot = diag.get('reproducibility') if isinstance(diag, dict) else None
    if not isinstance(snapshot, dict) or not snapshot:
        # 🔴 Аудит F-02: «паспорта нет» — не одна причина, а две. Режим малых
        # данных (закрытая формула МНК) паспорта не пишет вовсе и не может:
        # случайного сэмплера у него нет, а зерно бутстрапа и конформных
        # интервалов зашито в код (`ols_modeler.py:300,320`, `seed=42`). То есть
        # расчёт воспроизводим по построению, и говорить клиенту «модель
        # обучена в ранней версии программы» — ложь: он обучил её только что,
        # а совет переобучить не поможет, малые данные снова уйдут в тот же режим.
        if str(model_data.get('model_version') or '').endswith('ols'):
            return {'status': 'deterministic'}
        return {'status': 'absent'}

    versions = snapshot.get('versions') or {}
    return {
        'status': 'recorded',
        'seed': snapshot.get('seed'),
        'seed_source': snapshot.get('seed_source'),
        'sampler_tier': snapshot.get('sampler_tier'),
        'mcmc': snapshot.get('mcmc'),
        'versions': {k: versions.get(k) for k in ('python', 'numpy', 'pymc')
                     if versions.get(k)},
    }


def _extract_checks(
    model_data: dict[str, Any],
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Статусы проверок канона — вне хеша.

    🔴 Долг блока P0.6: сертификат не вправе утверждать, что проверка
    отрицательного базового уровня пройдена, если она была **неприменима**.
    Приор свободного члена делает отрицательную базу структурно недостижимой
    на данных с малым разбросом продаж, поэтому «годно» там означало бы не
    «модель здорова», а «проверка не могла сработать»
    (`utils/negative_baseline.py:203-208`).

    🔴 Источник диагностики — `results/model-diagnostics.json`, а НЕ поле
    `diagnostics` внутри модели: у сохранённой модели оно пустое (замер
    2026-08-03 по четырём клиентским моделям и по свежеобученной). Первая
    версия читала только модель и объявляла проверку отсутствующей там, где
    она была выполнена и оказалась нечувствительной — живой сторож поймал это
    сразу. Аргумент `diagnostics` передаёт вызывающий; поле модели остаётся
    запасным путём.
    """
    diag = diagnostics if isinstance(diagnostics, dict) and diagnostics else (
        model_data.get('diagnostics') or {}
    )
    nb = diag.get('negative_baseline') if isinstance(diag, dict) else None
    if not isinstance(nb, dict) or not nb:
        return {'negative_baseline': 'absent'}

    verdict = nb.get('verdict')
    if verdict == 'not_applicable' or not nb.get('detectable', True):
        state = 'not_applicable'
    elif verdict == 'ok':
        state = 'passed'
    elif verdict in ('watch', 'fail'):
        state = 'failed' if verdict == 'fail' else 'watch'
    else:
        state = 'absent'
    return {'negative_baseline': state}


# ── Отпечаток исходных данных – вне хеша, для клиента ────────────────────────

# Длина шестнадцатеричного представления SHA-256. Значение короче – не отпечаток,
# и печатать его как отпечаток нельзя.
ДЛИНА_SHA256 = 64


def _годный_хеш(значение: Any) -> str | None:
    """Строка ровно из 64 шестнадцатеричных знаков либо ничего.

    Проверка не педантизм: усечённое, пустое или подставленное значение,
    напечатанное под словом «отпечаток», выглядит для читателя документа
    ровно так же, как настоящее, и сверить его он не сможет.
    """
    if not isinstance(значение, str):
        return None
    текст = значение.strip().lower()
    if len(текст) != ДЛИНА_SHA256:
        return None
    if any(знак not in '0123456789abcdef' for знак in текст):
        return None
    return текст


def _extract_data_fingerprint(model_data: dict[str, Any]) -> dict[str, Any]:
    """Отпечаток исходных данных из паспорта воспроизводимости.

    Источник – `model_data['reproducibility']['data_fingerprint']`
    (`utils/seeding.py:165`), запасной – та же копия в диагностике. Половины
    независимы по построению (`utils/data_fingerprint.build_data_fingerprint`):
    таблица может быть снята, а файл к моменту обучения уже удалён.

    🔴 Поля не достраиваются ни из чего. У моделей, обученных до 06.07.2026,
    отпечатка нет вовсе, и посчитать его задним числом не по чему: исходный
    файл мог измениться, а таблицы в модели не сохранено. Статус `absent` –
    это ответ «не записано», а не «данные не сходятся».

    Returns:
        `{'status': 'absent'}` либо
        `{'status': 'recorded'|'partial', 'content': {...}|None, 'file': {...}|None}`.
        `partial` – записана только одна половина.
    """
    snapshot = model_data.get('reproducibility')
    if not isinstance(snapshot, dict) or not snapshot:
        diag = model_data.get('diagnostics') or {}
        snapshot = diag.get('reproducibility') if isinstance(diag, dict) else None
    if not isinstance(snapshot, dict) or not snapshot:
        return {'status': 'absent'}

    отпечаток = snapshot.get('data_fingerprint')
    if not isinstance(отпечаток, dict) or not отпечаток:
        return {'status': 'absent'}

    содержимое = отпечаток.get('content')
    файл = отпечаток.get('file')

    часть_содержимого: dict[str, Any] | None = None
    if isinstance(содержимое, dict) and содержимое.get('status') == 'ok':
        хеш = _годный_хеш(содержимое.get('content_sha256'))
        if хеш:
            часть_содержимого = {
                'algo': str(содержимое.get('algo') or ''),
                'sha256': хеш,
                'n_rows': содержимое.get('n_rows'),
                'n_cols': содержимое.get('n_cols'),
            }

    часть_файла: dict[str, Any] | None = None
    if isinstance(файл, dict) and файл.get('status') == 'ok':
        хеш = _годный_хеш(файл.get('file_sha256'))
        if хеш:
            часть_файла = {
                'algo': str(файл.get('algo') or ''),
                'sha256': хеш,
                'size_bytes': файл.get('size_bytes'),
                # Полного пути в отпечатке нет намеренно (он содержит имя
                # клиента), и здесь мы его тоже не восстанавливаем.
                'file_name': str(файл.get('file_name') or ''),
            }

    if not часть_содержимого and not часть_файла:
        return {'status': 'absent'}
    return {
        'status': 'recorded' if (часть_содержимого and часть_файла) else 'partial',
        'content': часть_содержимого,
        'file': часть_файла,
    }


# ── Протокол выбора переноса эффекта – вне хеша, для клиента ─────────────────

# Типы переноса, которые расчётные пути продукта действительно знают
# (`utils/adstock.py`). Всё прочее – включая настройку `auto` – типом не
# является: движок такого не считает.
ИЗВЕСТНЫЕ_ТИПЫ_ПЕРЕНОСА = ('geometric', 'weibull')


def _extract_adstock_protocol(model_data: dict[str, Any]) -> dict[str, Any]:
    """Протокол выбора переноса: что просили, что применилось, кто выбрал.

    Источник – `model_data['adstock_selection']` (`modeler.py:1792`), который
    пишет сам резолвер: исходная настройка снимается ДО мутации конфигурации,
    применённый тип – после. Другого источника у этого факта нет: после
    обучения `channel_adstock_types` и `config['adstock_config']` – один и тот
    же мутированный объект.

    🔴 Запасного пути здесь нет и быть не может. У моделей, обученных до
    06.07.2026, в `channel_adstock_types` стоит `'auto'` – это НАСТРОЙКА «выбери
    сам», а не тип. Вывести из неё применённый тип означало бы утверждать в
    заверяемом документе то, чего в модели не записано, опираясь на сегодняшний
    код – а модель обучена прежней версией программы, поведение которой этот
    документ не заверяет. В продукте этот класс подстановки выкорчёвывали
    трижды (F-01, Ф-01, хвост блока P0.7).

    Returns:
        `{'status': 'absent', 'channels': []}` либо
        `{'status': 'recorded', 'channels': [{'name', 'requested', 'resolved',
        'by'}, ...]}` в порядке записи модели.
    """
    протокол = model_data.get('adstock_selection')
    if not isinstance(протокол, dict) or not протокол:
        return {'status': 'absent', 'channels': []}

    каналы: list[dict[str, Any]] = []
    for имя, запись in протокол.items():
        if not isinstance(запись, dict):
            continue
        применено = запись.get('resolved')
        применено = str(применено) if применено is not None else ''
        # Канал попадает в протокол только с НАСТОЯЩИМ типом: незнакомое
        # значение фактом не является, и печатать его нельзя.
        if применено not in ИЗВЕСТНЫЕ_ТИПЫ_ПЕРЕНОСА:
            continue
        запрошено = запись.get('requested')
        каналы.append({
            'name': str(имя),
            'requested': str(запрошено) if запрошено is not None else None,
            'resolved': применено,
            'by': str(запись.get('by') or ''),
        })

    if not каналы:
        return {'status': 'absent', 'channels': []}
    return {'status': 'recorded', 'channels': каналы}


# ── Клиентские витрины: один источник для отчёта и презентации ───────────────
#
# 🔴 Строки живут здесь, а не в двух рендерах. Расхождение отчёта и презентации
# в продукте – самостоятельный дефект: клиент читает два документа об одном
# расчёте и видит разные утверждения. Отчёт берёт подробную форму, презентация –
# краткую, но факты у них по построению одни и те же.

ПЕРЕНОС_ПО_РУССКИ = {
    'geometric': 'геометрический',
    'weibull': 'вейбулловский',
}

# Что стояло в настройке до обучения. `auto` – просьба подобрать, а не тип.
ЗАПРОШЕНО_ПО_РУССКИ = {
    'auto': 'автоматический подбор',
    'geometric': 'геометрический',
    'weibull': 'вейбулловский',
}

# Кто принял решение. Ключи – константы `ADSTOCK_BY_*` из `engines/modeler.py`.
КТО_ВЫБРАЛ = {
    'user': 'задан вами в настройках',
    'default': 'канал в настройках не указан, применено значение по умолчанию',
    'bic': 'подобран программой по критерию BIC',
    'fallback_selector_error': 'автоматический подбор не выполнился, '
                               'применено значение по умолчанию',
    'fallback_selector_status': 'автоматический подбор не выполнился, '
                                'применено значение по умолчанию',
    'fallback_no_selection': 'автоматический подбор не дал ответа по этому каналу, '
                             'применено значение по умолчанию',
}

# Краткая форма того же – для узкой колонки слайда.
КТО_ВЫБРАЛ_КРАТКО = {
    'user': 'задан вами',
    'default': 'по умолчанию',
    'bic': 'подобран программой',
    'fallback_selector_error': 'подбор не выполнился',
    'fallback_selector_status': 'подбор не выполнился',
    'fallback_no_selection': 'подбор без ответа',
}

# Сколько знаков отпечатка показывать в краткой форме. Двенадцать – столько же,
# сколько у отпечатка расчёта на слайде: два отпечатка рядом должны читаться
# одинаково.
ЗНАКОВ_КРАТКО = 12


def _кратко(хеш: str) -> str:
    return f'{хеш[:ЗНАКОВ_КРАТКО]}…'


def _разряды(число: Any) -> str:
    """Целое с пробелами по разрядам либо пусто."""
    try:
        return f'{int(число):,}'.replace(',', ' ')
    except (TypeError, ValueError):
        return ''


def строки_отпечатка_данных(cert: Any, *, полностью: bool) -> list[tuple[str, str]]:
    """Пары «подпись – значение» об исходных данных.

    Args:
        cert: сертификат целиком (`generate_methodology_certificate`).
        полностью: True – форма отчёта (оба отпечатка целиком, размер таблицы
            и файла); False – форма слайда, где узкая колонка и нет места под
            оговорку о двух отпечатках. В краткой форме показывается ТОЛЬКО
            отпечаток содержимого: показать рядом отпечаток файла без оговорки
            значило бы подтолкнуть клиента к выводу «данные подменили» после
            обычного пересохранения таблицы в Excel.
    """
    отпечаток = (cert or {}).get('data_fingerprint') if isinstance(cert, dict) else None
    if not isinstance(отпечаток, dict) or отпечаток.get('status') == 'absent':
        return []

    строки: list[tuple[str, str]] = []
    содержимое = отпечаток.get('content')
    if isinstance(содержимое, dict) and содержимое.get('sha256'):
        хеш = содержимое['sha256']
        строки.append((
            'Отпечаток данных (содержимое)',
            хеш if полностью else _кратко(хеш),
        ))
        строк = _разряды(содержимое.get('n_rows'))
        столбцов = _разряды(содержимое.get('n_cols'))
        if полностью and строк and столбцов:
            строки.append(('Размер таблицы', f'строк: {строк}, столбцов: {столбцов}'))

    файл = отпечаток.get('file')
    if полностью and isinstance(файл, dict) and файл.get('sha256'):
        имя = файл.get('file_name') or ''
        размер = _разряды(файл.get('size_bytes'))
        if имя and размер:
            строки.append(('Файл исходных данных', f'{имя}, {размер} байт'))
        elif имя:
            строки.append(('Файл исходных данных', str(имя)))
        строки.append(('Отпечаток файла данных', файл['sha256']))
    return строки


def пояснение_отпечатка_данных(cert: Any) -> str:
    """Одна фраза о том, что означает раздел исходных данных."""
    отпечаток = (cert or {}).get('data_fingerprint') if isinstance(cert, dict) else None
    if not isinstance(отпечаток, dict) or not отпечаток:
        return ''
    if отпечаток.get('status') == 'absent':
        # Тон тот же, что у неполного заверения: названо, чего нет, и что с
        # этим делать. Никакого «данные не совпали».
        return ('Отпечаток исходных данных не записан: модель обучена в ранней '
                'версии программы, где он не сохранялся. Переобучите модель, '
                'чтобы отпечаток данных попал в заверение.')
    # 🔴 Уточнение обязательно: выше в том же блоке сказано, что отпечаток
    # расчёта покрывает файл модели, а исходные данные в него не входят. Без
    # этой фразы два соседних утверждения читаются как противоречие.
    return ('Отпечаток исходных данных снят при обучении: по нему проверяющий '
            'убеждается, что у него тот же набор данных. Это отдельный '
            'отпечаток: тот, что выше, покрывает файл модели, а этот – данные, '
            'на которых её обучили.')


def оговорки_отпечатка_данных(cert: Any) -> list[str]:
    """Оговорки к разделу исходных данных – только правдивые при этих полях."""
    отпечаток = (cert or {}).get('data_fingerprint') if isinstance(cert, dict) else None
    if not isinstance(отпечаток, dict) or отпечаток.get('status') == 'absent':
        return []

    оговорки: list[str] = []
    есть_содержимое = bool((отпечаток.get('content') or {}).get('sha256'))
    есть_файл = bool((отпечаток.get('file') or {}).get('sha256'))
    if есть_содержимое and есть_файл:
        # 🔴 Без этой оговорки первый же клиент, пересохранивший таблицу в Excel,
        # прочитает расхождение по файлу как подмену данных. xlsx – это архив со
        # временными метками внутри: два пересохранения одной таблицы дают два
        # разных набора байтов при одном и том же содержимом.
        оговорки.append(
            'Два отпечатка отвечают на разные вопросы. Отпечаток содержимого '
            'считается по значениям таблицы: он не меняется, если вы просто '
            'откроете файл и пересохраните его. Отпечаток файла считается по '
            'байтам и от пересохранения меняется закономерно, поэтому его '
            'расхождение при совпавшем содержимом означает другой файл, а не '
            'другие данные.'
        )
    elif есть_содержимое:
        оговорки.append(
            'Отпечаток содержимого считается по значениям таблицы и не меняется '
            'от пересохранения файла. Отпечатка самого файла в этой модели нет: '
            'на момент обучения файл прочитать не удалось.'
        )
    elif есть_файл:
        оговорки.append(
            'Записан отпечаток файла: он считается по байтам и от пересохранения '
            'меняется закономерно. Отпечатка содержимого таблицы в этой модели нет.'
        )
    if есть_содержимое:
        оговорки.append(
            'Отпечаток содержимого чувствителен к значениям ячеек, именам и '
            'порядку столбцов, числу и порядку строк, и не видит того, что не '
            'попало в таблицу: других листов книги, оформления, имени файла.'
        )
    return оговорки


def строки_протокола_затухания(cert: Any, *, подробно: bool) -> list[tuple[str, str]]:
    """Пары «подпись – значение» о переносе эффекта по каналам.

    Args:
        подробно: True – форма отчёта, строка на канал: что просили, что
            применилось, кто выбрал. False – форма слайда: одна сводная строка.
    """
    протокол = (cert or {}).get('adstock_protocol') if isinstance(cert, dict) else None
    if not isinstance(протокол, dict) or протокол.get('status') != 'recorded':
        return []
    каналы = протокол.get('channels') or []
    if not каналы:
        return []

    if подробно:
        строки: list[tuple[str, str]] = []
        for канал in каналы:
            применено = ПЕРЕНОС_ПО_РУССКИ.get(канал.get('resolved'), '')
            if not применено:
                continue
            кто = КТО_ВЫБРАЛ.get(канал.get('by'), '')
            запрошено = канал.get('requested')
            части = [f'применён {применено}']
            if запрошено is not None:
                названо = ЗАПРОШЕНО_ПО_РУССКИ.get(запрошено)
                # Незнакомое значение настройки печатается как есть, в кавычках:
                # оно записано в модели, и подменять его толкованием нельзя.
                части.insert(0, f'запрошен {названо}' if названо
                             else f'запрошено «{запрошено}»')
            else:
                части.insert(0, 'в настройках не задан')
            if кто:
                части.append(кто)
            строки.append((str(канал.get('name') or ''), '; '.join(части)))
        return строки

    типы = {канал.get('resolved') for канал in каналы}
    if len(типы) == 1:
        применено = ПЕРЕНОС_ПО_РУССКИ.get(next(iter(типы)), '')
        if not применено:
            return []
        причины = {канал.get('by') for канал in каналы}
        кто = КТО_ВЫБРАЛ_КРАТКО.get(next(iter(причины)), '') if len(причины) == 1 else ''
        значение = f'{применено} ({кто})' if кто else применено
    else:
        значение = 'по каналам различается'
    return [('Перенос эффекта', значение)]


def пояснение_протокола_затухания(cert: Any) -> str:
    """Одна фраза о том, что означает раздел переноса эффекта."""
    протокол = (cert or {}).get('adstock_protocol') if isinstance(cert, dict) else None
    if not isinstance(протокол, dict) or not протокол:
        return ''
    if протокол.get('status') != 'recorded':
        # 🔴 Формулировка намеренно не говорит, КАК считалось. Соблазн написать
        # «расчёт шёл по геометрическому переносу» опирается на сегодняшний код,
        # а модель обучена прежней версией программы.
        return ('Тип переноса эффекта при обучении не зафиксирован: модель '
                'обучена в ранней версии программы, где записывалась настройка, '
                'а не применённое значение. Восстановить его задним числом '
                'нельзя. Переобучите модель, чтобы выбор был зафиксирован.')
    return ('Перенос эффекта (adstock) – это то, какая часть отдачи канала '
            'приходится на последующие недели. Ниже по каждому каналу видно, '
            'что было запрошено в настройках, что применилось и кто выбрал.')


def краткие_строки_данных_и_переноса(cert: Any) -> list[tuple[str, str]]:
    """Форма слайда: те же факты, что в отчёте, а при их отсутствии – статус.

    🔴 Молчать на слайде нельзя. Отчёт для модели ранней версии прямо говорит,
    что отпечаток данных не записан и тип переноса не зафиксирован; слайд,
    который в этом случае просто не показывает строк, оставляет читателя с
    впечатлением, что показывать было нечего. Два документа об одном расчёте
    обязаны утверждать одно и то же.
    """
    if not isinstance(cert, dict) or not cert:
        return []
    строки = list(строки_отпечатка_данных(cert, полностью=False))
    отпечаток = cert.get('data_fingerprint')
    if not строки and isinstance(отпечаток, dict) and отпечаток:
        строки.append(('Отпечаток данных', 'не записан'))

    перенос = list(строки_протокола_затухания(cert, подробно=False))
    протокол = cert.get('adstock_protocol')
    if not перенос and isinstance(протокол, dict) and протокол:
        перенос.append(('Перенос эффекта', 'не зафиксирован'))
    return строки + перенос


def оговорка_о_выгрузке_параметров() -> str:
    """Где смотреть полные параметры модели.

    Сами параметры в отчёт не входят по решению владельца (16.08): полное
    раскрытие – по отдельному действию пользователя, а не в каждом документе.
    """
    return ('Полный набор параметров модели по каждому каналу – коэффициенты, '
            'разбросы, правдоподобные диапазоны, параметры переноса и '
            'насыщения, нормировка и приоры – в отчёт не входит и выгружается '
            'отдельно, по вашему запросу.')


# ── Критерий совпадения двух расчётов – вне хеша, для клиента ────────────────

def _extract_repro_tolerance(reproducibility: dict[str, Any]) -> dict[str, Any]:
    """Критерий совпадения: какое расхождение двух расчётов считается совпадением.

    🔴 Паспорт прогона отвечает на вопрос «как повторить», критерий – на вопрос
    «что считать повтором». Без второго первый неполон: оценка опирается на
    случайную процедуру, повтор с другим зерном даёт другие числа, и без
    объявленного допуска спор о результате неразрешим (замечание постороннего
    аналитика, 2026-08-16).

    Числа не задаются здесь: они берутся из `utils/repro_tolerance`, того же
    источника, которым сверка и пользуется. Документ и проверка не вправе
    разойтись.

    Три состояния:
      * `declared`     – расчёт случайный, паспорт записан, критерий применим;
      * `deterministic`– режим малых данных, закрытая формула: повтор даёт те же
        числа всегда, допуск не нужен;
      * `absent`       – паспорта нет (модель ранней версии): зерно не записано,
        режим сверки определить нечем, применим только самый широкий допуск.

    🔴 При статусе `recorded` паспорт передаётся в критерий целиком: критерий
    обязан САМ назвать ветвь допусков, применимую к этому расчёту, – по числу
    итоговых выборок из раздела прогона. Пока он молчал, добросовестный
    проверяющий брал строгую ветвь (она требует полного расчёта от 8000 выборок)
    и получал ложное «не совпало» на паспорте прогона в 600 выборок – ровно это
    и произошло у внешнего аналитика 2026-08-16 (замечание С-2).
    """
    from utils.repro_tolerance import criterion_for_certificate

    статус = (reproducibility or {}).get('status')
    if статус == 'deterministic':
        критерий = criterion_for_certificate()
        критерий['status'] = 'deterministic'
        return критерий
    if статус == 'recorded':
        критерий = criterion_for_certificate(reproducibility)
        критерий['status'] = 'declared'
        return критерий
    критерий = criterion_for_certificate()
    критерий['status'] = 'absent'
    return критерий


def строки_критерия_совпадения(cert: Any, *, подробно: bool) -> list[tuple[str, str]]:
    """Пары «подпись – значение» о том, что считается повторением расчёта.

    Args:
        подробно: True – форма отчёта, строка на каждое условие. False – форма
            слайда: одна строка, самое главное.
    """
    критерий = (cert or {}).get('repro_tolerance') if isinstance(cert, dict) else None
    if not isinstance(критерий, dict) or not критерий:
        return []
    статус = критерий.get('status')

    if статус == 'deterministic':
        return [('Совпадение расчётов', 'повтор даёт те же числа: расчёт '
                                        'выполняется по закрытой формуле, случайной '
                                        'процедуры в нём нет')]
    if статус == 'absent':
        # Молчать нельзя, но и объявлять допуск нечему: без зерна и настроек в
        # паспорте режим сверки не определить, а назвать наугад – обмануть.
        return [('Совпадение расчётов', 'критерий не применим: в модели не записаны '
                                        'зерно и настройки расчёта, сверить повтор не с чем')]

    from utils.repro_tolerance import criterion_lines
    строки = criterion_lines(критерий)
    if подробно:
        return строки

    # Форма слайда: одна строка – и это строка о ветви, применимой К ЭТОМУ
    # расчёту. Прежняя обещала «то же зерно – числа совпадают точно» и называла
    # строгий допуск, не глядя на полноту прогона: на слайде это ровно та
    # подмена, из-за которой сторонний проверяющий брал недостижимый допуск.
    применимая = критерий.get('applicable')
    if isinstance(применимая, dict) and применимая.get('tolerances'):
        окупаемость = (применимая.get('tolerances') or {}).get('roi')
        заголовок = применимая.get('title') or ''
    else:
        строгий = критерий.get('other_seed_full') or {}
        окупаемость = (строгий.get('tolerances') or {}).get('roi')
        заголовок = (строгий.get('title') or '')
    if окупаемость is None or not заголовок:
        return []
    число = f'{окупаемость:.1f}'.rstrip('0').rstrip('.').replace('.', ',')
    return [('Совпадение расчётов', f'проверка стороннего – ветвь «{заголовок}»: '
                                    f'расхождение до {число} %')]


def пояснение_критерия_совпадения(cert: Any) -> str:
    """Одна фраза о том, зачем в документе объявлен допуск."""
    критерий = (cert or {}).get('repro_tolerance') if isinstance(cert, dict) else None
    if not isinstance(критерий, dict) or not критерий:
        return ''
    if критерий.get('status') == 'deterministic':
        return ('Повторный расчёт на тех же данных даёт те же числа: в режиме малых '
                'данных модель считается по закрытой формуле, случайной процедуры в '
                'ней нет.')
    if критерий.get('status') == 'absent':
        return ('Критерий совпадения к этой модели не применяется: она обучена в '
                'ранней версии программы, где зерно и настройки расчёта не '
                'записывались. Переобучите модель, чтобы повтор можно было сверить.')

    from utils.repro_tolerance import criterion_note
    return criterion_note()
