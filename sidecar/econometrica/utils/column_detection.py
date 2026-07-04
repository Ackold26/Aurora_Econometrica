"""
Aurora Econometrica - column auto-detection (v2.0.0).

Auto-classification колонок Excel/CSV по именам. Расширенный variable classifier
per ADR-019 (supersedes ADR-015):

- Target metrics — 13 types (sales_rub, sales_packs, revenue, profit, leads,
  registrations, subscriptions, applications, bookings, transactions, traffic,
  loyalty_cards, app_installs)
- Media inputs — monetary (₽) vs physical (TRP, impressions, clicks, views)
- Media format detection (channel categorization) — TV / Digital / OLV /
  Performance / Social / OOH / Print / Radio / Cinema / Аптечный OOH /
  Retail Media / Influencer / Email-CRM / Programmatic / Affiliates
- **Signed control factors** (NEW v2.0.0) — competitor (negative-leaning prior),
  price / weather / macro (signed unconstrained prior). Per ADR-019 §4.
- Holiday recognition (NEW) — если customer уже имеет holiday columns в data.

Per ADR-019 (Mode as explicit Manager choice) — wizard auto-detect делает 60-80%
работы. PerChannelInputSelector скрыт в Manager mode независимо от detection.
Best-practice recommendations (warn-level) surface через best_practice_rules.py.

Usage:
    from utils.column_detection import (
        classify_columns,
        detect_available_metrics,
        detect_media_format,
        detect_signed_controls,
    )

    columns = ['tv_spend', 'tv_grp', 'olv_impressions', 'sales_packs',
               'competitor_trp', 'price_average', 'holiday_newyear']
    classified = classify_columns(columns)
    # {'tv_spend': 'monetary', 'tv_grp': 'physical', 'olv_impressions': 'physical',
    #  'sales_packs': 'target_count', 'competitor_trp': 'signed_competitor',
    #  'price_average': 'signed_price', 'holiday_newyear': 'holiday'}

References:
- ADR-019 (Mode as Explicit Manager Choice) - main spec.
- ADR-015 (superseded).
- docs/v2_0_0_design/WIZARD_FLOW_v2_FINAL.md §1.2.
- aurora-meta/ENGINEERING_INVARIANTS.md INV-30 (single-unit preference).
"""
from __future__ import annotations

import re
from typing import Dict, List, Literal, Optional

# Output classification type (v2.0.0 extended).
ColumnKind = Literal[
    'monetary',           # media spend in ₽
    'physical',           # media physical metrics (TRP, impressions, clicks, views)
    'target_monetary',    # KPI target in ₽ (sales_rub, revenue, profit)
    'target_count',       # KPI target в штуках (sales_packs, leads, etc.)
    'date',               # date column
    'control',            # positive control (distribution, trade_activity)
    'signed_competitor',  # NEW v2.0.0 - competitor activity (negative-leaning)
    'signed_price',       # NEW v2.0.0 - price (signed unconstrained)
    'signed_weather',     # NEW v2.0.0 - weather (signed unconstrained)
    'signed_macro',       # NEW v2.0.0 - macroeconomic (CPI, GDP, FX)
    'holiday',            # NEW v2.0.0 - holiday dummy
    'seasonality',        # NEW 2026-07-04 - auto-injected Fourier sin/cos harmonics
    'category',           # NEW 2026-07-04 (Фаза Б) - продажи рынка/категории (spread demand)
    'unknown',            # unrecognized
]

# ─── Regex patterns (RU + EN, case-insensitive, separator-aware) ────────────

# Helper: pattern matches if surrounded by separator (_-space-hyphen) or start/end.
# Python `\b` word boundary НЕ работает между `_` и letter (оба word chars).
# Используем lookbehind+lookahead для (start|sep) + token + (sep|end|word_suffix).
_SEP = r'(?:^|(?<=[_\s\-]))'    # start of string OR preceded by sep
_END = r'(?=[_\s\-]|$)'         # followed by sep OR end of string


def _sep_pattern(token: str) -> str:
    """Wrap token с separator-aware boundaries для Cyrillic + underscore-prefixed names."""
    return _SEP + token + _END


# Money / budget / spend / cost. Matches: tv_spend, tv_budget, тв_бюджет, costs_tv,
# brand_spend_eur, ad_cost, маркетинг_бюджет, рекл_расходы.
MONETARY_PATTERNS = [
    _sep_pattern(r'spend(?:s|ing)?'),
    _sep_pattern(r'budget'),
    _sep_pattern(r'cost(?:s)?'),
    _sep_pattern(r'expense(?:s)?'),
    _sep_pattern(r'investment(?:s)?'),
    _sep_pattern(r'бюджет(?:ы|а|ов)?'),
    _sep_pattern(r'расход(?:ы|ов|а)?'),
    _sep_pattern(r'затрат(?:ы|а|ов)?'),
    _sep_pattern(r'стоимость'),
    _sep_pattern(r'трат(?:ы|а)?'),
    _sep_pattern(r'инвестиц(?:ии|ия|ий)'),
    # Currency markers в названии колонки = monetary.
    _sep_pattern(r'rub'),
    _sep_pattern(r'usd'),
    _sep_pattern(r'eur'),
    r'₽',  # currency symbol - matches anywhere.
]

# Physical metrics: impressions, clicks, visits, GRP, reach, views.
PHYSICAL_PATTERNS = [
    _sep_pattern(r'impression(?:s)?'),
    _sep_pattern(r'impr(?:s)?'),
    _sep_pattern(r'show(?:s|n)?'),
    _sep_pattern(r'view(?:s)?'),
    _sep_pattern(r'click(?:s)?'),
    _sep_pattern(r'visit(?:s)?'),
    _sep_pattern(r'session(?:s)?'),
    _sep_pattern(r'reach'),
    _sep_pattern(r'contact(?:s)?'),
    _sep_pattern(r'grp(?:s)?'),
    _sep_pattern(r'trp(?:s)?'),
    _sep_pattern(r'open(?:s|ed)?'),
    _sep_pattern(r'delivery'),
    _sep_pattern(r'delivered'),
    _sep_pattern(r'показ(?:ы|ов|а)?'),
    _sep_pattern(r'кликов?'),
    _sep_pattern(r'клики'),
    _sep_pattern(r'визит(?:ы|ов|а)?'),
    _sep_pattern(r'охват(?:ы|ом)?'),
    _sep_pattern(r'просмотр(?:ы|ов|а)?'),
    _sep_pattern(r'контакт(?:ы|ов|а)?'),
    _sep_pattern(r'аудитори(?:я|и|ей)'),
    _sep_pattern(r'трафик'),
    _sep_pattern(r'грп'),
    _sep_pattern(r'трп'),
    _sep_pattern(r'выдач(?:и|а|ам)?'),
]

# Target metrics - monetary (продажи в ₽, выручка, прибыль).
# Эти паттерны проверяются ДО MONETARY_PATTERNS - sales_rub имеет priority над `rub`.
TARGET_MONETARY_PATTERNS = [
    _sep_pattern(r'sales_rub'),
    _sep_pattern(r'sales_revenue'),
    _sep_pattern(r'revenue'),
    _sep_pattern(r'profit'),
    _sep_pattern(r'gmv'),
    _sep_pattern(r'gross_revenue'),
    _sep_pattern(r'sales_money'),
    # Note: bare 'sales' assumed monetary, но только если нет суффикса `_pack` / `_unit` / `_volume`.
    # Pattern matches `sales`, `sales_total`, etc. но не `sales_packs` (т.к. TARGET_COUNT_PATTERNS checked first).
    _sep_pattern(r'sales'),
    _sep_pattern(r'продаж(?:и|ь)_руб'),
    _sep_pattern(r'продаж(?:и|ь)_money'),
    _sep_pattern(r'выручка'),
    _sep_pattern(r'выручки'),
    _sep_pattern(r'выручке'),
    _sep_pattern(r'оборот'),
]

# Target metrics - count (продажи в штуках, лиды, регистрации).
# v2.0.0 extension: применять, бронирования, транзакции, трафик.
# Проверяются ДО PHYSICAL_PATTERNS (sales_packs не должен попасть в physical).
TARGET_COUNT_PATTERNS = [
    # Sales counts (packs, units, volume)
    _sep_pattern(r'sales_pack(?:s)?'),
    _sep_pattern(r'sales_unit(?:s)?'),
    _sep_pattern(r'sales_volume'),
    _sep_pattern(r'units_sold'),
    _sep_pattern(r'продаж(?:и|ь)_шт'),
    _sep_pattern(r'продаж(?:и|ь)_упак'),
    _sep_pattern(r'упаков(?:ки|ок)?'),
    _sep_pattern(r'штуки'),
    _sep_pattern(r'pack(?:s)?_sold'),
    # Leads / applications
    _sep_pattern(r'lead(?:s)?'),
    _sep_pattern(r'лид(?:ы|ов|а)?'),
    _sep_pattern(r'лиды'),
    _sep_pattern(r'заявк(?:а|и|ам|ой)?'),
    _sep_pattern(r'application(?:s)?'),
    _sep_pattern(r'заявлени(?:я|ий|е)?'),
    # Registrations / signups
    _sep_pattern(r'registration(?:s)?'),
    _sep_pattern(r'signup(?:s)?'),
    _sep_pattern(r'sign_up(?:s)?'),
    _sep_pattern(r'регистрац(?:ии|ия|ий)'),
    _sep_pattern(r'активаци(?:и|я|ий)?'),
    # Subscriptions
    _sep_pattern(r'subscription(?:s)?'),
    _sep_pattern(r'sub(?:s)?'),
    _sep_pattern(r'mrr(?:_units|_subs)?'),
    _sep_pattern(r'подписк(?:а|и|ам)?'),
    _sep_pattern(r'подписки'),
    # Loyalty / cards
    _sep_pattern(r'card(?:s)?_issued'),
    _sep_pattern(r'loyalty_card(?:s)?'),
    _sep_pattern(r'cards_loyalty'),
    _sep_pattern(r'карт(?:а|ы|ам)?_выдан'),
    _sep_pattern(r'карт(?:а|ы)?_лояльности'),
    # App / digital
    _sep_pattern(r'install(?:s)?'),
    _sep_pattern(r'download(?:s)?'),
    _sep_pattern(r'app_install(?:s)?'),
    _sep_pattern(r'установк(?:а|и)?'),
    _sep_pattern(r'загрузк(?:а|и)?'),
    # NEW v2.0.0 — Bookings (travel/hospitality)
    _sep_pattern(r'booking(?:s)?'),
    _sep_pattern(r'reservation(?:s)?'),
    _sep_pattern(r'бронирован(?:ия|ие|ий)?'),
    _sep_pattern(r'заказ(?:ы|а|ов)?'),
    _sep_pattern(r'orders'),
    # NEW v2.0.0 — Transactions (e-commerce / marketplaces)
    _sep_pattern(r'transaction(?:s)?'),
    _sep_pattern(r'транзакци(?:и|я|й|ей)?'),
    _sep_pattern(r'purchases'),
    _sep_pattern(r'покупк(?:а|и|ам)?'),
    # NEW v2.0.0 — Traffic (retail offline)
    _sep_pattern(r'traffic'),
    _sep_pattern(r'visit(?:s|ors)?'),
    _sep_pattern(r'трафик_магазин'),
    _sep_pattern(r'посетител(?:и|ей|ями)?'),
    _sep_pattern(r'check(?:s|out)?'),
    _sep_pattern(r'чек(?:и|ов|а)?'),
]

# ─── NEW v2.0.0: Signed control factors ────────────────────────────────────
# Per ADR-019 §4: factors с unconstrained sign (могут быть positive OR negative
# в зависимости от data). Bayesian model uses unconstrained or negative-leaning
# priors (vs HalfNormal positivity-constrained для media channels).

# Competitor activity - negative-leaning prior (их активность typically снижает
# наши продажи). Patterns: competitor_*, share_of_voice_competitor, comp_trp.
SIGNED_COMPETITOR_PATTERNS = [
    _sep_pattern(r'competitor(?:s)?'),
    _sep_pattern(r'competitor_(?:trp|grp|spend|impressions|share|sov|reach)'),
    _sep_pattern(r'comp_(?:trp|grp|spend|impressions|share|sov)'),
    _sep_pattern(r'share_of_voice_competitor(?:s)?'),
    _sep_pattern(r'sov_competitor(?:s)?'),
    _sep_pattern(r'sov_comp'),
    _sep_pattern(r'конкурент(?:ы|ов|а|ам)?'),
    _sep_pattern(r'конкурент_(?:трп|показы|спенд|охват)'),
    _sep_pattern(r'доля_голоса_конкурент(?:ов|а)?'),
    _sep_pattern(r'svok'),  # ROSST industry term: share_of_voice_konkurentov
]

# Price - signed unconstrained (может быть positive [premium effect, BOGO] или
# negative [demand elasticity на rising price]).
SIGNED_PRICE_PATTERNS = [
    _sep_pattern(r'price'),
    _sep_pattern(r'price_(?:avg|average|mean|level|index)'),
    _sep_pattern(r'avg_price'),
    _sep_pattern(r'mean_price'),
    _sep_pattern(r'unit_price'),
    _sep_pattern(r'price_index'),
    _sep_pattern(r'price_elasticity'),
    _sep_pattern(r'цена'),
    _sep_pattern(r'цены'),
    _sep_pattern(r'средняя_цена'),
    _sep_pattern(r'индекс_цен'),
]

# Weather - signed unconstrained (category-dependent: ice cream → positive temp,
# umbrellas → negative temp, etc.).
SIGNED_WEATHER_PATTERNS = [
    _sep_pattern(r'weather'),
    _sep_pattern(r'temp(?:erature)?'),
    _sep_pattern(r'precipitation'),
    _sep_pattern(r'humidity'),
    _sep_pattern(r'snow(?:fall)?'),
    _sep_pattern(r'rain(?:fall)?'),
    _sep_pattern(r'погода'),
    _sep_pattern(r'температур(?:а|ы)?'),
    _sep_pattern(r'осадк(?:и|ов)?'),
    _sep_pattern(r'влажность'),
]

# Macroeconomic - signed unconstrained (CPI, GDP, FX rates, inflation).
SIGNED_MACRO_PATTERNS = [
    _sep_pattern(r'cpi'),
    _sep_pattern(r'consumer_price'),
    _sep_pattern(r'inflation'),
    _sep_pattern(r'gdp'),
    _sep_pattern(r'gdp_(?:nominal|real|growth)'),
    _sep_pattern(r'fx_(?:rate|usd|eur)'),
    _sep_pattern(r'exchange_rate'),
    _sep_pattern(r'usd_rub'),
    _sep_pattern(r'eur_rub'),
    _sep_pattern(r'ввп'),
    _sep_pattern(r'ипц'),
    _sep_pattern(r'инфляция'),
    _sep_pattern(r'курс_(?:рубля|доллара|евро)'),
]

# Holiday markers - бинарные dummies для известных событий. Recognition если
# customer уже включил holiday columns в data file. Aurora auto-injects 12
# events независимо (см. holiday_calendar_ru.py).
HOLIDAY_PATTERNS = [
    _sep_pattern(r'holiday(?:s)?'),
    _sep_pattern(r'holiday_(?:newyear|christmas|valentine|march8|may|easter)'),
    _sep_pattern(r'holiday_(?:defender|russia_day|unity|black_friday|cyber_monday)'),
    _sep_pattern(r'holiday_(?:school_break|back_to_school|summer_break)'),
    _sep_pattern(r'event(?:s)?'),
    _sep_pattern(r'праздник(?:и|ов|а)?'),
    _sep_pattern(r'выходн(?:ой|ые|ых)?'),
    _sep_pattern(r'каникул(?:ы|ам)?'),
    _sep_pattern(r'новый_год'),
    _sep_pattern(r'нг(?:_активность)?'),
    _sep_pattern(r'8_март(?:а|ом)?'),
    _sep_pattern(r'23_феврал(?:я|ем)?'),
    _sep_pattern(r'9_ма(?:я|ем)?'),
]

# Category demand — продажи ВСЕЙ категории/рынка (ОБЪЁМ, не доля). Экзогенный
# контроль спроса (Chan & Perry §4.2.2): спрос всей категории не зависит от медиа
# одного бренда, но задаёт волну, на которую бренд «плывёт» → сильнейший прокси
# спроса (сильнее Фурье: реальный ряд, не гладкая аппроксимация). Детектится комбо
# ТЕМА(категория/рынок) И ОБЪЁМ(продажи/руб/шт/...) — зеркало validator.detect_column_role
# (Фаза Б 2026-07-04, F-AUD-5: голое «категори» ловило текстовые атрибуты). classify_column
# использует это для prior (positive-leaning shared demand); validator — для роли UI.
# 🔴 ПАРИТЕТ: списки синхронизированы с validator.py::_CATEGORY_THEME/_CATEGORY_VOLUME.
_CATEGORY_THEME = ('категори', 'рынок', 'рынк', 'market', 'category')
_CATEGORY_VOLUME = (
    'продаж', 'объем', 'объём', 'руб', 'уп.', 'уп ', 'шт', 'спрос', 'всего',
    'sales', 'volume', 'units', 'value', 'total', 'demand',
)


# Seasonality — auto-injected Fourier harmonics (season_fourier_sin_K / _cos_K).
# Инжектятся движком (modeler) как гладкая сезонная волна спроса, семантически
# ОТДЕЛЬНЫЙ фактор (не generic control): decomposer выносит их одной агрегированной
# полосой «Сезонность». Prior — zero-centered (sin/cos симметричны, modeler.py).
# 🔴 ПАРИТЕТ: префикс синхронизирован с utils/fourier_seasonality.FOURIER_COL_PREFIX
# = 'season_fourier'. При смене префикса там — обновить паттерн здесь.
SEASONALITY_PATTERNS = [
    _sep_pattern(r'season_fourier'),
]

# Positive control factors - distribution, trade_activity, promo. Sign expected
# positive (more distribution → more sales). Existing v1.3.x patterns preserved.
CONTROL_POSITIVE_PATTERNS = [
    _sep_pattern(r'distribution'),
    _sep_pattern(r'numeric_distribution'),
    _sep_pattern(r'weighted_distribution'),
    _sep_pattern(r'дистрибуция'),
    _sep_pattern(r'дистриб'),
    _sep_pattern(r'trade_activity(?:_score)?'),
    _sep_pattern(r'trade_score'),
    _sep_pattern(r'промо_активность'),
    _sep_pattern(r'торгов(?:ая|ой)_активность'),
    _sep_pattern(r'promo(?:_indicator|_active)?'),
    _sep_pattern(r'pos_count'),
    _sep_pattern(r'product_launch(?:es)?'),
    _sep_pattern(r'npd_count'),
    _sep_pattern(r'new_sku(?:_count)?'),
]

# ─── NEW v2.0.0: Media format detection ────────────────────────────────────
# Classification channel name → media format category. Используется для:
# 1. Best-practice recommendations (Performance → клики, OLV → просмотры)
# 2. Default channel categorization (brand vs performance) для hierarchical priors
# 3. UI grouping в отчётах и charts
#
# MediaFormat type: TV, Digital (display), OLV (online video), Performance,
# Social, OOH, Print, Radio, Cinema, Aptechi_OOH, Retail_Media, Influencer,
# Email_CRM, Programmatic, Affiliates. + Unknown fallback.

MediaFormat = Literal[
    'tv', 'digital', 'olv', 'performance', 'social', 'ooh', 'print', 'radio',
    'cinema', 'aptechi_ooh', 'retail_media', 'influencer', 'email_crm',
    'programmatic', 'affiliates', 'unknown',
]

# Channel name prefix patterns → media format. Order matters (more specific first).
MEDIA_FORMAT_PATTERNS: Dict[str, List[str]] = {
    'aptechi_ooh': [r'^аптечн', r'^pharma_ooh', r'^pharm_ooh', r'^apteka', r'^drug_store'],
    'retail_media': [r'^retail_media', r'^in_store', r'^pos_ad', r'^supermarket_ad'],
    'performance': [r'^performance', r'^perf$', r'^search', r'^ppc', r'^paid_search',
                    r'^контекст', r'^перформанс', r'^яндекс_директ', r'^google_ads'],
    'olv': [r'^olv', r'^online_video', r'^видеоролик', r'^pre_roll', r'^mid_roll',
            r'^post_roll', r'^видео_цифров', r'^youtube_video'],
    'social': [r'^social', r'^smm', r'^vk', r'^facebook', r'^instagram', r'^tiktok',
               r'^telegram_ads', r'^одноклассники'],
    'cinema': [r'^cinema', r'^кинотеатр', r'^кино'],
    'influencer': [r'^influencer', r'^blogger', r'^блоггер', r'^opinion_leader',
                   r'^lider_mneniy', r'^kol'],
    'programmatic': [r'^programmatic', r'^rtb', r'^dsp', r'^pmp'],
    'affiliates': [r'^affiliate(?:s)?', r'^cpa', r'^партнерк'],
    'email_crm': [r'^email', r'^crm', r'^newsletter', r'^рассылк', r'^crm_email'],
    'tv': [r'^tv', r'^tv_(?:brand|performance|short|long|sponsor)', r'^тв', r'^телевизор',
           r'^bcast', r'^broadcast'],
    'radio': [r'^radio', r'^радио'],
    'print': [r'^print', r'^magazine', r'^newspaper', r'^журнал', r'^газет'],
    'ooh': [r'^ooh', r'^outdoor', r'^наружн', r'^биллборд', r'^billboard'],
    'digital': [r'^digital', r'^display', r'^banner', r'^цифров', r'^баннер'],
}


def detect_media_format(channel_name: str) -> MediaFormat:
    """Classify channel name → media format category.

    Args:
        channel_name: имя канала (e.g., 'tv_brand', 'performance_search', 'olv_youtube').

    Returns:
        MediaFormat literal или 'unknown'.

    Examples:
        >>> detect_media_format('tv_brand')
        'tv'
        >>> detect_media_format('performance_search')
        'performance'
        >>> detect_media_format('olv_pre_roll')
        'olv'
        >>> detect_media_format('something_obscure')
        'unknown'
    """
    name_lower = channel_name.lower()
    # Check специфические patterns first (more specific → less specific).
    for fmt, patterns in MEDIA_FORMAT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, name_lower, re.IGNORECASE | re.UNICODE):
                return fmt  # type: ignore[return-value]
    return 'unknown'

# Date columns.
DATE_PATTERNS = [
    _sep_pattern(r'date'),
    _sep_pattern(r'day'),
    _sep_pattern(r'week'),
    _sep_pattern(r'month'),
    _sep_pattern(r'period'),
    _sep_pattern(r'time'),
    _sep_pattern(r'timestamp'),
    _sep_pattern(r'дата'),
    _sep_pattern(r'день'),
    _sep_pattern(r'недел(?:я|и|ю)?'),
    _sep_pattern(r'месяц'),
    _sep_pattern(r'период'),
    _sep_pattern(r'время'),
]


def _matches_any(text: str, patterns: List[str]) -> bool:
    """Test if text matches any regex pattern (case-insensitive)."""
    text_lower = text.lower()
    for pattern in patterns:
        if re.search(pattern, text_lower, re.IGNORECASE | re.UNICODE):
            return True
    return False


def classify_column(column_name: str) -> ColumnKind:
    """Classify single column name → kind.

    Order of precedence:
    1. Date (наиболее однозначно).
    2. Target monetary (sales_rub, revenue).
    3. Target count (sales_packs, leads, registrations).
    4. Monetary input (budget, spend, cost).
    5. Physical input (impressions, clicks, GRP).
    6. Unknown.

    Args:
        column_name: имя колонки из Excel/CSV.

    Returns:
        ColumnKind.

    Examples:
        >>> classify_column('tv_spend')
        'monetary'
        >>> classify_column('olv_impressions')
        'physical'
        >>> classify_column('sales_packs')
        'target_count'
        >>> classify_column('date')
        'date'
        >>> classify_column('something_obscure')
        'unknown'
    """
    # Order matters: more specific patterns (target_count, signed_*, holiday) checked
    # before less specific (target_monetary, monetary, physical).
    # 'sales_packs' classified as count, не как monetary (bare 'sales' lower priority).
    # 'competitor_trp' classified as signed_competitor, не как physical (бы поймал 'trp').
    # 'holiday_newyear' classified as holiday, не как monetary/physical.

    # v2.0.0 priority order:
    # 1. Date (наиболее однозначно)
    # 2. Seasonality (auto-injected Fourier season_fourier_* — префикс однозначен)
    # 3. Signed controls (specific patterns: competitor, price, weather, macro)
    # 4. Holiday markers
    # 5. Positive controls (distribution, trade_activity)
    # 6. Target count (sales_packs, leads — before bare 'sales')
    # 7. Target monetary (sales_rub, revenue, profit)
    # 8. Monetary input (budget, spend, cost)
    # 9. Physical input (impressions, clicks, TRP, GRP)

    if _matches_any(column_name, DATE_PATTERNS):
        return 'date'

    # Seasonality (auto-injected Fourier) — префикс однозначен, проверяем рано.
    if _matches_any(column_name, SEASONALITY_PATTERNS):
        return 'seasonality'

    # Signed controls — specific patterns checked before general monetary/physical
    if _matches_any(column_name, SIGNED_COMPETITOR_PATTERNS):
        return 'signed_competitor'
    if _matches_any(column_name, SIGNED_PRICE_PATTERNS):
        return 'signed_price'
    if _matches_any(column_name, SIGNED_WEATHER_PATTERNS):
        return 'signed_weather'
    if _matches_any(column_name, SIGNED_MACRO_PATTERNS):
        return 'signed_macro'

    # Holiday markers (auto-injected или user-supplied)
    if _matches_any(column_name, HOLIDAY_PATTERNS):
        return 'holiday'

    # Category demand (Фаза Б, 2026-07-04): ТЕМА(категория/рынок) И ОБЪЁМ(продажи/руб/...)
    # — экзогенный контроль спроса. Комбо-условие (не single-pattern) → не в registry
    # export; проверяется ДО generic control/target, иначе «Продажи категории руб» ушло
    # бы в target_monetary (по «продаж...руб»). Derived (доля рынка/SOM) сюда не доходит:
    # validator помечает их unused → не попадают в control_cols → modeler их не видит.
    _lower_cat = column_name.lower()
    if (any(k in _lower_cat for k in _CATEGORY_THEME)
            and any(v in _lower_cat for v in _CATEGORY_VOLUME)):
        return 'category'

    # Positive controls (distribution, trade_activity)
    if _matches_any(column_name, CONTROL_POSITIVE_PATTERNS):
        return 'control'

    # Target columns (count перед monetary чтобы sales_packs не словил 'sales' bare)
    if _matches_any(column_name, TARGET_COUNT_PATTERNS):
        return 'target_count'
    if _matches_any(column_name, TARGET_MONETARY_PATTERNS):
        return 'target_monetary'

    # Media inputs
    if _matches_any(column_name, MONETARY_PATTERNS):
        return 'monetary'
    if _matches_any(column_name, PHYSICAL_PATTERNS):
        return 'physical'

    return 'unknown'


def classify_columns(column_names: List[str]) -> Dict[str, ColumnKind]:
    """Classify all columns в файле.

    Args:
        column_names: список имён колонок.

    Returns:
        Dict {column_name: ColumnKind}.
    """
    return {name: classify_column(name) for name in column_names}


# ─── v2.0.1: Unit label rules для UI ────────────────────────────────────────
# Per-channel-name keyword detection для human-readable unit label.
# Order matters (more specific first). Используется AppliedModeSummary UI
# для отображения «₽ за 1 TRP» / «₽ за 1000 показов» и т.п.
_UNIT_LABEL_RULES = [
    (re.compile(r'(?<![a-zA-Zа-яА-Я])(trp|трп)', re.IGNORECASE), '₽ за 1 TRP'),
    (re.compile(r'(?<![a-zA-Zа-яА-Я])(grp|грп)', re.IGNORECASE), '₽ за 1 GRP'),
    (re.compile(r'(impression|показ)', re.IGNORECASE), '₽ за 1000 показов (CPM)'),
    (re.compile(r'(click|клик)', re.IGNORECASE), '₽ за 1 клик (CPC)'),
    (re.compile(r'(visit|визит)', re.IGNORECASE), '₽ за 1 визит'),
    (re.compile(r'(view|просмотр)', re.IGNORECASE), '₽ за 1 просмотр'),
    (re.compile(r'(reach|охват)', re.IGNORECASE), '₽ за 1000 охвата'),
    (re.compile(r'(прочтен)', re.IGNORECASE), '₽ за 1 прочтение'),
]


def unit_label_for(channel_name: str) -> str:
    """Human-readable unit label для physical channel в Manager ROI UI.

    Examples:
        >>> unit_label_for('TRPs бренд (W 25-54)')
        '₽ за 1 TRP'
        >>> unit_label_for('Banners Показы')
        '₽ за 1000 показов (CPM)'
        >>> unit_label_for('Unknown channel')
        '₽ за 1 единицу'
    """
    if not channel_name:
        return '₽ за 1 единицу'
    for rx, label in _UNIT_LABEL_RULES:
        if rx.search(channel_name):
            return label
    return '₽ за 1 единицу'


# Mapping kind → pattern list для SSOT export.
_PATTERN_KIND_REGISTRY = {
    'monetary': MONETARY_PATTERNS,
    'physical': PHYSICAL_PATTERNS,
    'target_monetary': TARGET_MONETARY_PATTERNS,
    'target_count': TARGET_COUNT_PATTERNS,
    'signed_competitor': SIGNED_COMPETITOR_PATTERNS,
    'signed_price': SIGNED_PRICE_PATTERNS,
    'signed_weather': SIGNED_WEATHER_PATTERNS,
    'signed_macro': SIGNED_MACRO_PATTERNS,
    'holiday': HOLIDAY_PATTERNS,
    'seasonality': SEASONALITY_PATTERNS,
    'control': CONTROL_POSITIVE_PATTERNS,
    'date': DATE_PATTERNS,
}

# Priority order matches classify_column() decision tree.
_CLASSIFY_PRIORITY = [
    'date',
    'seasonality',
    'signed_competitor',
    'signed_price',
    'signed_weather',
    'signed_macro',
    'holiday',
    'control',
    'target_count',
    'target_monetary',
    'monetary',
    'physical',
]


def export_patterns_as_json() -> Dict[str, object]:
    """Export classifier patterns + metadata для frontend SSOT consumption.

    Frontend (src/lib/services/classifier-patterns.js) fetches this via
    `GET /api/static/classifier-patterns-v1.json`, caches result, and
    reconstructs JS RegExp objects from these patterns. Это eliminates regex
    duplication между Python и frontend (audit P-05 / Phase 1.1 SSOT).

    Patterns include separator-aware lookbehind/lookahead — JS V8 (WebView2)
    supports ES2018+ regex features, тестируется в classifier-patterns.spec.

    Returns:
        Dict со schema:
        {
            'version': 'v1',
            'kinds': {kind: [pattern_string, ...]},
            'priority': [kind, ...],
            'unit_label_rules': [{'pattern': str, 'label': str}],
        }
    """
    return {
        'version': 'v1',
        'kinds': {
            kind: list(patterns)
            for kind, patterns in _PATTERN_KIND_REGISTRY.items()
        },
        'priority': list(_CLASSIFY_PRIORITY),
        'unit_label_rules': [
            {'pattern': rx.pattern, 'label': label}
            for rx, label in _UNIT_LABEL_RULES
        ],
    }


def detect_available_metrics(
    column_names: List[str],
    channel_name: str,
) -> Dict[str, List[str]]:
    """Найти доступные monetary / physical метрики для конкретного канала.

    Соглашение naming: имя канала - префикс колонки (e.g. 'tv_spend', 'tv_grp').

    Args:
        column_names: все колонки в датасете.
        channel_name: имя канала (e.g. 'tv', 'olv', 'performance').

    Returns:
        Dict с keys 'monetary', 'physical' и lists соответствующих имён колонок.

    Examples:
        >>> cols = ['date', 'tv_spend', 'tv_grp', 'olv_impressions', 'sales_rub']
        >>> detect_available_metrics(cols, 'tv')
        {'monetary': ['tv_spend'], 'physical': ['tv_grp']}
        >>> detect_available_metrics(cols, 'olv')
        {'monetary': [], 'physical': ['olv_impressions']}
    """
    channel_lower = channel_name.lower()
    result: Dict[str, List[str]] = {'monetary': [], 'physical': []}

    for col in column_names:
        col_lower = col.lower()
        # Heuristic: канал - префикс или встречается в начале/средине.
        # Допускаем разделители _, -, пробел.
        # Pattern: channel_name + (_|-| ) + остаток.
        if not (col_lower.startswith(channel_lower) or f'_{channel_lower}' in col_lower):
            continue

        kind = classify_column(col)
        if kind == 'monetary':
            result['monetary'].append(col)
        elif kind == 'physical':
            result['physical'].append(col)

    return result


def has_ambiguous_channels(
    column_names: List[str],
    channels: List[str],
) -> bool:
    """True если хотя бы один канал имеет несколько типов метрик доступных.

    Используется UI: если все каналы have single available metric - PerChannelInputSelector
    скрыт; если хотя бы один ambiguous - показывается selector.

    Args:
        column_names: все колонки.
        channels: список имён каналов проекта.

    Returns:
        True if any channel has both monetary AND physical available.
    """
    for channel in channels:
        available = detect_available_metrics(column_names, channel)
        if available['monetary'] and available['physical']:
            return True
    return False


def suggest_default_input_metric(
    column_names: List[str],
    channels: List[str],
) -> Dict[str, str]:
    """Suggest default input metric per канал.

    Логика:
    - Если у канала есть только monetary → 'monetary'.
    - Если только physical → 'physical'.
    - Если оба - приоритет monetary (более точная по бюджету, обычно).
    - Если ни одного - 'monetary' default (fallback).

    Args:
        column_names: все колонки.
        channels: список имён каналов.

    Returns:
        Dict {channel: 'monetary'|'physical'}.

    Examples:
        >>> cols = ['date', 'tv_spend', 'olv_impressions', 'sales_rub']
        >>> suggest_default_input_metric(cols, ['tv', 'olv'])
        {'tv': 'monetary', 'olv': 'physical'}
    """
    defaults = {}
    for channel in channels:
        available = detect_available_metrics(column_names, channel)
        if available['monetary']:
            defaults[channel] = 'monetary'
        elif available['physical']:
            defaults[channel] = 'physical'
        else:
            defaults[channel] = 'monetary'  # fallback
    return defaults


# ─── NEW v2.0.0: Signed control + holiday detection helpers ────────────────


def detect_signed_controls(column_names: List[str]) -> Dict[str, List[str]]:
    """Найти signed control factors среди колонок.

    Per ADR-019 §4: signed controls — factors с unconstrained sign (competitor,
    price, weather, macro). Bayesian model использует разные priors для них
    (vs media channels с positivity constraint).

    Args:
        column_names: все колонки в датасете.

    Returns:
        Dict с keys 'competitor', 'price', 'weather', 'macro' и lists колонок.

    Examples:
        >>> cols = ['date', 'tv_spend', 'competitor_trp', 'price_avg',
        ...         'cpi', 'temp_avg']
        >>> detect_signed_controls(cols)
        {'competitor': ['competitor_trp'], 'price': ['price_avg'],
         'weather': ['temp_avg'], 'macro': ['cpi']}
    """
    result: Dict[str, List[str]] = {
        'competitor': [],
        'price': [],
        'weather': [],
        'macro': [],
    }
    for col in column_names:
        kind = classify_column(col)
        if kind == 'signed_competitor':
            result['competitor'].append(col)
        elif kind == 'signed_price':
            result['price'].append(col)
        elif kind == 'signed_weather':
            result['weather'].append(col)
        elif kind == 'signed_macro':
            result['macro'].append(col)
    return result


def detect_holiday_columns(column_names: List[str]) -> List[str]:
    """Найти holiday dummy колонки в data (user-supplied или auto-injected).

    Aurora auto-injects 12 РФ holidays через holiday_calendar_ru.py.
    Customer может также supply own holiday columns в data — они тоже
    распознаются и используются.

    Args:
        column_names: все колонки.

    Returns:
        List колонок типа 'holiday'.

    Examples:
        >>> cols = ['date', 'tv_spend', 'holiday_newyear', 'holiday_march8']
        >>> detect_holiday_columns(cols)
        ['holiday_newyear', 'holiday_march8']
    """
    return [col for col in column_names if classify_column(col) == 'holiday']


def detect_target_candidates(
    column_names: List[str],
) -> List[Dict[str, str]]:
    """Найти все возможные target columns с их типом.

    Manager wizard Step 2 использует для disambiguation (если ≥2 candidates).

    Args:
        column_names: все колонки.

    Returns:
        List of {column: name, kind: 'target_monetary'|'target_count'}.

    Examples:
        >>> cols = ['date', 'sales_rub', 'sales_packs', 'tv_spend']
        >>> detect_target_candidates(cols)
        [{'column': 'sales_rub', 'kind': 'target_monetary'},
         {'column': 'sales_packs', 'kind': 'target_count'}]
    """
    candidates = []
    for col in column_names:
        kind = classify_column(col)
        if kind in ('target_monetary', 'target_count'):
            candidates.append({'column': col, 'kind': kind})
    return candidates


def classify_columns_extended(
    column_names: List[str],
) -> Dict[str, Dict[str, str]]:
    """Extended classification: each column → {kind, sub_type} for v2.0.0.

    sub_type adds detail для media (which format) and signed (which factor type).

    Args:
        column_names: все колонки.

    Returns:
        Dict {column: {'kind': ColumnKind, 'sub_type': str | None}}.

    Examples:
        >>> cols = ['date', 'tv_brand_spend', 'olv_views', 'competitor_trp']
        >>> classify_columns_extended(cols)
        {'date': {'kind': 'date', 'sub_type': None},
         'tv_brand_spend': {'kind': 'monetary', 'sub_type': 'tv'},
         'olv_views': {'kind': 'physical', 'sub_type': 'olv'},
         'competitor_trp': {'kind': 'signed_competitor', 'sub_type': None}}
    """
    result: Dict[str, Dict[str, str]] = {}
    for col in column_names:
        kind = classify_column(col)
        sub_type: Optional[str] = None
        if kind in ('monetary', 'physical'):
            # Detect media format (channel category)
            fmt = detect_media_format(col)
            if fmt != 'unknown':
                sub_type = fmt
        result[col] = {'kind': kind, 'sub_type': sub_type}
    return result
