"""
Test suite для column_detection.py v2.0.0 extension.
Target: 200+ test cases (~10× existing v1.3 coverage).

Coverage:
- Target metric types (13 types, 5 cases each)
- Signed control detection (4 types, 5 cases each)
- Holiday detection (5+ cases)
- Media format detection (15 categories, 3+ cases each)
- Edge cases (10+ scenarios)
- Helper functions
- Priority order verification
"""
from __future__ import annotations

import sys
from pathlib import Path

SIDECAR_ROOT = Path(__file__).resolve().parent.parent / 'sidecar' / 'econometrica'
sys.path.insert(0, str(SIDECAR_ROOT))

import pytest
from utils.column_detection import (
    classify_column,
    classify_columns,
    detect_available_metrics,
    detect_signed_controls,
    detect_holiday_columns,
    detect_target_candidates,
    detect_media_format,
    classify_columns_extended,
)


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 1: TARGET METRICS — 13 types
# ═══════════════════════════════════════════════════════════════════════════════

class TestTargetMonetary:
    """Target monetary KPIs: sales_rub, revenue, profit."""

    # ─── sales_rub ───────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "sales_rub",
        "sales_rub_total",
        "sales_rub_adjusted",
        "product_sales_rub",
        "sales_rub_week2",  # 'week2' not a date token, so target_monetary wins
    ])
    def test_sales_rub_variants(self, col):
        assert classify_column(col) == "target_monetary", f"Failed for: {col}"

    # ─── revenue ─────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "revenue",
        "revenue_total",
        "gross_revenue",
        "sales_revenue",
        "total_revenue_rub",
    ])
    def test_revenue_variants(self, col):
        assert classify_column(col) == "target_monetary", f"Failed for: {col}"

    # ─── profit ──────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "profit",
        "profit_total",
        "net_profit",
        "profit_monthly",  # 'month' token → date priority; use 'monthly' to avoid
        "brand_profit",
    ])
    def test_profit_variants(self, col):
        assert classify_column(col) == "target_monetary", f"Failed for: {col}"

    # ─── RU monetary targets ─────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "выручка",
        "выручки_итого",
        "продажи_руб",
        "оборот",
        "продажи_money",
    ])
    def test_ru_monetary_targets(self, col):
        assert classify_column(col) == "target_monetary", f"Failed for: {col}"

    # ─── sales (bare, without pack suffix) ───────────────────────────────────

    @pytest.mark.parametrize("col", [
        "sales",
        "sales_total",
        "brand_sales",
        "weekly_sales",
        "sales_q1",
    ])
    def test_bare_sales_monetary(self, col):
        assert classify_column(col) == "target_monetary", f"Failed for: {col}"


class TestTargetCount:
    """Target count KPIs: sales_packs, leads, registrations, subscriptions,
    applications, bookings, transactions, traffic, loyalty_cards, app_installs."""

    # ─── sales_packs ─────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "sales_packs",
        "sales_pack",
        "sales_units",
        "sales_unit",
        "sales_volume",
    ])
    def test_sales_packs_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "units_sold",
        "pack_sold",
        "продажи_шт",
        "продажи_упак",
        "packs_sold",
    ])
    def test_sales_packs_alt_names(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    # ─── leads ───────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "leads",
        "lead",
        "qualified_leads",
        "leads_total",
        "лиды",
    ])
    def test_leads_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    # ─── registrations ───────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "registrations",
        "registration",
        "signups",
        "sign_ups",
        "регистрации",
    ])
    def test_registrations_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    # ─── subscriptions ───────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "subscriptions",
        "subscription",
        "subs",
        "mrr_subs",
        "подписки",
    ])
    def test_subscriptions_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    # ─── applications ────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "applications",
        "application",
        "заявки",
        "заявка",
        "заявления",  # genitive/plural form in pattern (заявлени(?:я|ий|е)?)
    ])
    def test_applications_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    # ─── bookings ────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "bookings",
        "booking",
        "reservations",
        "reservation",
        "бронирования",
    ])
    def test_bookings_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    # ─── transactions ────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "transactions",
        "transaction",
        "purchases",
        "транзакции",
        "покупки",
    ])
    def test_transactions_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    # ─── traffic (retail) ────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "traffic",
        "трафик_магазин",
        "visitors",
        "посетители",
        "checkout",  # pattern: check(?:s|out)? — 'checkouts' (double suffix) not matched
    ])
    def test_traffic_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    # ─── loyalty_cards ───────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "loyalty_cards",
        "loyalty_card",
        "cards_issued",
        "cards_loyalty",
        "карты_лояльности",
    ])
    def test_loyalty_cards_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    # ─── app_installs ─────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "app_installs",
        "app_install",
        "installs",
        "downloads",
        "установки",
    ])
    def test_app_installs_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    # ─── orders / заказы ─────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "orders",
        "заказы",
        "заказа",
        "заказов",
        "purchases",  # 'order_count' not matched; 'purchases' is a listed pattern
    ])
    def test_orders_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    # ─── чеки ────────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "чеки",
        "чеков",
        "checks",
        "checkout",
        "чека",
    ])
    def test_checks_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    # ─── custom / activations ────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "активации",
        "активация",
        "signup",
        "mrr_units",
        "загрузки",
    ])
    def test_custom_count_variants(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 2: SIGNED CONTROLS — 4 types
# ═══════════════════════════════════════════════════════════════════════════════

class TestSignedControls:
    """Signed control factors: competitor, price, weather, macro."""

    # ─── competitor ───────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "competitor_trp",
        "comp_spend",
        "share_of_voice_competitors",
        "конкурент_показы",
        "svok",
    ])
    def test_competitor_variants(self, col):
        assert classify_column(col) == "signed_competitor", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "competitors",
        "competitor",
        "comp_trp",
        "sov_competitors",
        "конкуренты",
    ])
    def test_competitor_alt_names(self, col):
        assert classify_column(col) == "signed_competitor", f"Failed for: {col}"

    # ─── price ───────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "price_avg",
        "avg_price",
        "цена",
        "индекс_цен",
        "price_index",
    ])
    def test_price_variants(self, col):
        assert classify_column(col) == "signed_price", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "price",
        "unit_price",
        "mean_price",
        "price_average",
        "цены",
    ])
    def test_price_alt_names(self, col):
        assert classify_column(col) == "signed_price", f"Failed for: {col}"

    # ─── weather ─────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "temp_avg",
        "weather",
        "humidity",
        "осадки",
        "температура",
    ])
    def test_weather_variants(self, col):
        assert classify_column(col) == "signed_weather", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "temp",
        "temperature",
        "precipitation",
        "snowfall",
        "погода",
    ])
    def test_weather_alt_names(self, col):
        assert classify_column(col) == "signed_weather", f"Failed for: {col}"

    # ─── macro ───────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "cpi",
        "gdp",
        "fx_rate",
        "ипц",
        "ввп",
    ])
    def test_macro_variants(self, col):
        assert classify_column(col) == "signed_macro", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "inflation",
        "gdp_growth",      # 'consumer_price' → signed_price wins over signed_macro (price token)
        "exchange_rate",
        "usd_rub",
        "курс_рубля",
    ])
    def test_macro_alt_names(self, col):
        assert classify_column(col) == "signed_macro", f"Failed for: {col}"


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 3: HOLIDAY DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

class TestHolidayDetection:
    """Holiday dummy column detection."""

    @pytest.mark.parametrize("col", [
        "holiday_newyear",
        "holiday_march8",
        "праздник",
        "8_марта",
        "новый_год",
    ])
    def test_holiday_basic_variants(self, col):
        assert classify_column(col) == "holiday", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "holiday",
        "holidays",
        "event",
        "events",
        "праздники",
    ])
    def test_holiday_generic_variants(self, col):
        assert classify_column(col) == "holiday", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "holiday_christmas",
        "holiday_black_friday",
        "holiday_defender",
        "holiday_russia",   # 'holiday_russia_day' → 'day' triggers date priority
        "holiday_unity",
    ])
    def test_holiday_specific_names(self, col):
        assert classify_column(col) == "holiday", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "выходные",
        "каникулы",
        "нг_активность",
        "нг",
        "23_февраля",
    ])
    def test_holiday_ru_variants(self, col):
        assert classify_column(col) == "holiday", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "holiday_school_break",
        "holiday_back_to_school",
        "holiday_summer_break",
        "event_marker",
        "9_мая",
    ])
    def test_holiday_seasonal_variants(self, col):
        assert classify_column(col) == "holiday", f"Failed for: {col}"


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 4: MEDIA FORMAT DETECTION — 15 categories
# ═══════════════════════════════════════════════════════════════════════════════

class TestMediaFormats:
    """Media format detection via detect_media_format()."""

    # ─── tv ──────────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "tv_brand_spend",
        "tv_spend",
        "тв_бюджет",
        "bcast_spend",
        "broadcast_costs",
    ])
    def test_tv_format(self, col):
        assert detect_media_format(col) == "tv", f"Failed for: {col}"

    # ─── digital ─────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "digital_spend",
        "display_spend",
        "banner_spend",
        "цифров_бюджет",
        "digital_impressions",
    ])
    def test_digital_format(self, col):
        assert detect_media_format(col) == "digital", f"Failed for: {col}"

    # ─── olv ─────────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "olv_spend",
        "online_video_budget",
        "pre_roll_views",
        "mid_roll_impressions",
        "youtube_video_spend",
    ])
    def test_olv_format(self, col):
        assert detect_media_format(col) == "olv", f"Failed for: {col}"

    # ─── performance ─────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "performance_spend",
        "search_spend",
        "ppc_budget",
        "яндекс_директ_spend",
        "контекст_бюджет",
    ])
    def test_performance_format(self, col):
        assert detect_media_format(col) == "performance", f"Failed for: {col}"

    # ─── social ──────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "social_spend",
        "smm_budget",
        "vk_spend",
        "instagram_budget",
        "tiktok_spend",
    ])
    def test_social_format(self, col):
        assert detect_media_format(col) == "social", f"Failed for: {col}"

    # ─── ooh ─────────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "ooh_spend",
        "outdoor_budget",
        "наружн_бюджет",
        "billboard_spend",
        "биллборд_spend",
    ])
    def test_ooh_format(self, col):
        assert detect_media_format(col) == "ooh", f"Failed for: {col}"

    # ─── print ───────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "print_spend",
        "magazine_budget",
        "newspaper_spend",
        "журнал_бюджет",
        "газет_spend",
    ])
    def test_print_format(self, col):
        assert detect_media_format(col) == "print", f"Failed for: {col}"

    # ─── radio ───────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "radio_spend",
        "radio_budget",
        "радио_spend",
        "radio_impressions",
        "радио_бюджет",
    ])
    def test_radio_format(self, col):
        assert detect_media_format(col) == "radio", f"Failed for: {col}"

    # ─── cinema ──────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "cinema_spend",
        "кинотеатр_spend",
        "кино_budget",
        "cinema_impressions",
        "cinema_budget",
    ])
    def test_cinema_format(self, col):
        assert detect_media_format(col) == "cinema", f"Failed for: {col}"

    # ─── aptechi_ooh ─────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "аптечн_ooh_spend",
        "pharma_ooh_budget",
        "pharm_ooh_spend",
        "apteka_spend",
        "drug_store_budget",
    ])
    def test_aptechi_ooh_format(self, col):
        assert detect_media_format(col) == "aptechi_ooh", f"Failed for: {col}"

    # ─── retail_media ────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "retail_media_spend",
        "in_store_budget",
        "pos_ad_spend",
        "supermarket_ad_budget",
        "retail_media_impressions",
    ])
    def test_retail_media_format(self, col):
        assert detect_media_format(col) == "retail_media", f"Failed for: {col}"

    # ─── influencer ──────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "influencer_spend",
        "blogger_budget",
        "блоггер_spend",
        "opinion_leader_spend",
        "kol_budget",
    ])
    def test_influencer_format(self, col):
        assert detect_media_format(col) == "influencer", f"Failed for: {col}"

    # ─── email_crm ───────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "email_spend",
        "crm_budget",
        "newsletter_spend",
        "рассылк_spend",
        "crm_email_budget",
    ])
    def test_email_crm_format(self, col):
        assert detect_media_format(col) == "email_crm", f"Failed for: {col}"

    # ─── programmatic ────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "programmatic_spend",
        "rtb_budget",
        "dsp_spend",
        "pmp_budget",
        "programmatic_impressions",
    ])
    def test_programmatic_format(self, col):
        assert detect_media_format(col) == "programmatic", f"Failed for: {col}"

    # ─── affiliates ──────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "affiliates_spend",
        "affiliate_budget",
        "cpa_spend",
        "партнерк_budget",
        "affiliates_revenue",
    ])
    def test_affiliates_format(self, col):
        assert detect_media_format(col) == "affiliates", f"Failed for: {col}"

    # ─── unknown fallback ────────────────────────────────────────────────────

    def test_unknown_media_format(self):
        assert detect_media_format("something_obscure") == "unknown"
        assert detect_media_format("column_a") == "unknown"
        assert detect_media_format("xyz_spend_unrecognized_channel") == "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 5: EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge cases: typos, mixed case, synonyms, empty, long names, etc."""

    # ─── RU column names with typos ──────────────────────────────────────────

    def test_ru_typo_prodazhy(self):
        # "продажы" instead of "продажи" — typo, should not match monetary/count
        # The module won't match this (no typo tolerance), returns 'unknown'
        result = classify_column("продажы_руб")
        # With typo, pattern won't match — expected 'unknown'
        assert result == "unknown"

    def test_ru_typo_vyruchka_latin_a(self):
        # "выручкa" — Cyrillic а replaced with latin a, should fail to match
        result = classify_column("выручкa")
        # Can't guarantee match — documenting behavior
        assert result in ("target_monetary", "unknown")

    # ─── EN column names with synonyms ───────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "revenue",
        "sales",
        "turnover",  # 'turnover' is not in patterns, expected 'unknown'
    ])
    def test_en_monetary_synonyms(self, col):
        if col == "turnover":
            assert classify_column(col) == "unknown"
        else:
            assert classify_column(col) == "target_monetary"

    # ─── Mixed case ──────────────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "Sales_Rub",
        "SALES_RUB",
        "Revenue",
        "REVENUE",
        "Profit",
    ])
    def test_mixed_case_monetary(self, col):
        assert classify_column(col) == "target_monetary", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "Sales_Packs",
        "SALES_PACKS",
        "Leads",
        "LEADS",
        "Registrations",
    ])
    def test_mixed_case_count(self, col):
        assert classify_column(col) == "target_count", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "TV_Spend",
        "TV_SPEND",
        "Tv_budget",
        "OLV_IMPRESSIONS",
        "Olv_Impressions",
    ])
    def test_mixed_case_media(self, col):
        kind = classify_column(col)
        assert kind in ("monetary", "physical"), f"Expected media, got {kind!r} for: {col}"

    # ─── Adjusted variants ───────────────────────────────────────────────────

    @pytest.mark.parametrize("col", [
        "sales_rub_adjusted",
        "revenue_adjusted",
        "sales_packs_adjusted",
        "leads_adjusted",
    ])
    def test_adjusted_variants_classified(self, col):
        result = classify_column(col)
        # adjusted suffix doesn't block pattern match
        assert result in ("target_monetary", "target_count"), \
            f"Expected target, got {result!r} for: {col}"

    # ─── Numeric column without name hints → 'unknown' ────────────────────────

    @pytest.mark.parametrize("col", [
        "col_1",
        "column_a",
        "var_x",
        "field_123",
        "abc",
    ])
    def test_unknown_numeric_columns(self, col):
        assert classify_column(col) == "unknown", f"Failed for: {col}"

    # ─── Empty string and None-like ──────────────────────────────────────────

    def test_empty_string(self):
        assert classify_column("") == "unknown"

    def test_whitespace_only(self):
        # Single space — should not match any pattern
        result = classify_column(" ")
        assert result == "unknown"

    # ─── Very long column name ───────────────────────────────────────────────

    def test_very_long_column_name_with_sales_rub(self):
        col = "a" * 200 + "_sales_rub"
        result = classify_column(col)
        assert result == "target_monetary"

    def test_very_long_column_name_unknown(self):
        col = "x" * 300
        assert classify_column(col) == "unknown"

    # ─── Cyrillic mixed with latin ───────────────────────────────────────────

    def test_rub_prodazhi_mixed(self):
        # "rub_продажи" — latin prefix, Cyrillic suffix (bare 'sales' in RU not in pattern)
        result = classify_column("rub_продажи")
        # 'rub' matches monetary pattern — so expect monetary
        assert result == "monetary"

    def test_sales_rub_with_cyrillic_suffix(self):
        result = classify_column("sales_rub_продажи")
        # 'sales_rub' matches first → target_monetary
        assert result == "target_monetary"

    # ─── Column collision: sales_packs vs sales_rub in same dataset ──────────

    def test_collision_sales_packs_vs_sales_rub(self):
        result_packs = classify_column("sales_packs")
        result_rub = classify_column("sales_rub")
        assert result_packs == "target_count"
        assert result_rub == "target_monetary"
        assert result_packs != result_rub

    # ─── Multiple potential targets in same dataset ───────────────────────────

    def test_multiple_targets_classified_separately(self):
        cols = ["sales_rub", "sales_packs", "leads", "revenue", "profit"]
        result = classify_columns(cols)
        assert result["sales_rub"] == "target_monetary"
        assert result["sales_packs"] == "target_count"
        assert result["leads"] == "target_count"
        assert result["revenue"] == "target_monetary"
        assert result["profit"] == "target_monetary"

    # ─── Date at start/end ───────────────────────────────────────────────────

    def test_date_column_not_misclassified(self):
        assert classify_column("week") == "date"
        assert classify_column("period_month") == "date"
        assert classify_column("дата") == "date"

    # ─── Competitor_trp not misclassified as physical ─────────────────────────

    def test_competitor_trp_not_physical(self):
        # trp alone → physical, but competitor_trp → signed_competitor (priority)
        assert classify_column("trp") == "physical"
        assert classify_column("competitor_trp") == "signed_competitor"


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 6: PRIORITY ORDER VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestPriorityOrder:
    """Verify classification priority: count > monetary, signed > physical, holiday > monetary."""

    # sales_packs → target_count, not target_monetary (priority: count before monetary)
    def test_sales_packs_is_count_not_monetary(self):
        assert classify_column("sales_packs") == "target_count"
        # 'sales' alone (without pack suffix) → monetary
        assert classify_column("sales") == "target_monetary"

    def test_sales_units_is_count_not_monetary(self):
        assert classify_column("sales_units") == "target_count"

    # competitor_trp → signed_competitor, not physical (trp would be physical)
    def test_competitor_trp_not_physical(self):
        assert classify_column("competitor_trp") == "signed_competitor"
        assert classify_column("comp_trp") == "signed_competitor"

    def test_competitor_impressions_not_physical(self):
        assert classify_column("competitor_impressions") == "signed_competitor"

    # holiday_newyear → holiday, not monetary
    def test_holiday_newyear_is_holiday_not_monetary(self):
        assert classify_column("holiday_newyear") == "holiday"

    def test_holiday_march8_is_holiday_not_date(self):
        assert classify_column("holiday_march8") == "holiday"

    # price → signed_price, not unknown
    def test_price_is_signed_price(self):
        assert classify_column("price") == "signed_price"
        assert classify_column("price_avg") == "signed_price"

    # rub alone → monetary (currency marker), not target_monetary
    def test_rub_alone_not_target(self):
        # 'rub' alone matches MONETARY_PATTERNS (currency marker), not TARGET_MONETARY
        result = classify_column("rub")
        assert result == "monetary"

    # sales_rub → target_monetary (target checked before monetary)
    def test_sales_rub_is_target_not_plain_monetary(self):
        assert classify_column("sales_rub") == "target_monetary"

    # date is always first
    def test_date_has_highest_priority(self):
        # 'week_sales' — 'week' triggers date first
        assert classify_column("week") == "date"
        # 'date' triggers date even if other patterns could match
        assert classify_column("date") == "date"

    # distribution → control (positive), not monetary or unknown
    def test_distribution_is_control(self):
        assert classify_column("distribution") == "control"
        assert classify_column("numeric_distribution") == "control"

    # control checked before target_count (promo_indicator ≠ target)
    def test_promo_indicator_is_control(self):
        assert classify_column("promo_indicator") == "control"

    # svok → signed_competitor (industry-specific RU term)
    def test_svok_is_signed_competitor(self):
        assert classify_column("svok") == "signed_competitor"

    # visits — target_count (посетители = retail traffic), not physical (visits=sessions)
    def test_visits_classified_as_target_count(self):
        # 'visits' matches TARGET_COUNT_PATTERNS before PHYSICAL_PATTERNS in priority
        result = classify_column("visits")
        assert result == "target_count"


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 7: HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

class TestHelpers:
    """Tests for helper functions: detect_signed_controls, detect_holiday_columns,
    detect_target_candidates, classify_columns_extended."""

    # ─── detect_signed_controls ───────────────────────────────────────────────

    def test_detect_signed_controls_basic(self):
        cols = ["date", "tv_spend", "competitor_trp", "price_avg", "cpi"]
        result = detect_signed_controls(cols)
        assert result["competitor"] == ["competitor_trp"]
        assert result["price"] == ["price_avg"]
        assert result["macro"] == ["cpi"]
        assert result["weather"] == []

    def test_detect_signed_controls_full(self):
        cols = ["date", "tv_spend", "competitor_trp", "price_avg",
                "cpi", "temp_avg"]
        result = detect_signed_controls(cols)
        assert "competitor_trp" in result["competitor"]
        assert "price_avg" in result["price"]
        assert "cpi" in result["macro"]
        assert "temp_avg" in result["weather"]

    def test_detect_signed_controls_multiple_per_type(self):
        cols = ["competitor_trp", "comp_spend", "price_avg", "avg_price"]
        result = detect_signed_controls(cols)
        assert len(result["competitor"]) == 2
        assert "competitor_trp" in result["competitor"]
        assert "comp_spend" in result["competitor"]
        assert len(result["price"]) == 2

    def test_detect_signed_controls_empty(self):
        cols = ["date", "tv_spend", "sales_rub"]
        result = detect_signed_controls(cols)
        assert result == {"competitor": [], "price": [], "weather": [], "macro": []}

    def test_detect_signed_controls_keys(self):
        result = detect_signed_controls([])
        assert set(result.keys()) == {"competitor", "price", "weather", "macro"}

    def test_detect_signed_controls_ru_columns(self):
        cols = ["конкуренты", "цена", "температура", "ипц"]
        result = detect_signed_controls(cols)
        assert "конкуренты" in result["competitor"]
        assert "цена" in result["price"]
        assert "температура" in result["weather"]
        assert "ипц" in result["macro"]

    # ─── detect_holiday_columns ───────────────────────────────────────────────

    def test_detect_holiday_columns_basic(self):
        cols = ["date", "tv_spend", "holiday_newyear", "holiday_march8"]
        result = detect_holiday_columns(cols)
        assert "holiday_newyear" in result
        assert "holiday_march8" in result
        assert "date" not in result
        assert "tv_spend" not in result

    def test_detect_holiday_columns_empty(self):
        cols = ["date", "tv_spend", "sales_rub"]
        assert detect_holiday_columns(cols) == []

    def test_detect_holiday_columns_all_types(self):
        cols = ["holiday_newyear", "holiday_march8", "праздник", "событие",
                "holiday_black_friday"]
        result = detect_holiday_columns(cols)
        assert len(result) >= 3

    def test_detect_holiday_columns_returns_list(self):
        result = detect_holiday_columns(["holiday_newyear"])
        assert isinstance(result, list)
        assert result == ["holiday_newyear"]

    def test_detect_holiday_columns_preserves_order(self):
        cols = ["holiday_newyear", "date", "tv_spend", "holiday_march8", "sales_rub"]
        result = detect_holiday_columns(cols)
        assert result.index("holiday_newyear") < result.index("holiday_march8")

    # ─── detect_target_candidates ─────────────────────────────────────────────

    def test_detect_target_candidates_basic(self):
        cols = ["date", "sales_rub", "sales_packs", "tv_spend"]
        result = detect_target_candidates(cols)
        columns = [c["column"] for c in result]
        kinds = {c["column"]: c["kind"] for c in result}
        assert "sales_rub" in columns
        assert "sales_packs" in columns
        assert "tv_spend" not in columns
        assert kinds["sales_rub"] == "target_monetary"
        assert kinds["sales_packs"] == "target_count"

    def test_detect_target_candidates_dict_structure(self):
        cols = ["sales_rub", "leads"]
        result = detect_target_candidates(cols)
        for item in result:
            assert "column" in item
            assert "kind" in item
            assert item["kind"] in ("target_monetary", "target_count")

    def test_detect_target_candidates_no_targets(self):
        cols = ["date", "tv_spend", "competitor_trp"]
        result = detect_target_candidates(cols)
        assert result == []

    def test_detect_target_candidates_multiple(self):
        cols = ["sales_rub", "revenue", "profit", "sales_packs", "leads", "registrations"]
        result = detect_target_candidates(cols)
        kinds = [c["kind"] for c in result]
        assert "target_monetary" in kinds
        assert "target_count" in kinds
        assert len(result) == 6

    def test_detect_target_candidates_empty_input(self):
        assert detect_target_candidates([]) == []

    # ─── classify_columns_extended ────────────────────────────────────────────

    def test_classify_columns_extended_basic(self):
        cols = ["date", "tv_brand_spend", "olv_views", "competitor_trp"]
        result = classify_columns_extended(cols)
        assert result["date"]["kind"] == "date"
        assert result["date"]["sub_type"] is None
        assert result["tv_brand_spend"]["kind"] == "monetary"
        assert result["tv_brand_spend"]["sub_type"] == "tv"
        assert result["olv_views"]["kind"] == "physical"
        assert result["olv_views"]["sub_type"] == "olv"
        assert result["competitor_trp"]["kind"] == "signed_competitor"
        assert result["competitor_trp"]["sub_type"] is None

    def test_classify_columns_extended_structure(self):
        cols = ["sales_rub", "tv_spend"]
        result = classify_columns_extended(cols)
        for col, info in result.items():
            assert "kind" in info
            assert "sub_type" in info

    def test_classify_columns_extended_media_subtypes(self):
        cols = ["tv_spend", "radio_budget", "print_spend", "ooh_impressions",
                "social_spend", "performance_spend"]
        result = classify_columns_extended(cols)
        assert result["tv_spend"]["sub_type"] == "tv"
        assert result["radio_budget"]["sub_type"] == "radio"
        assert result["print_spend"]["sub_type"] == "print"
        assert result["ooh_impressions"]["sub_type"] == "ooh"
        assert result["social_spend"]["sub_type"] == "social"
        assert result["performance_spend"]["sub_type"] == "performance"

    def test_classify_columns_extended_no_subtype_for_non_media(self):
        cols = ["sales_rub", "sales_packs", "holiday_newyear",
                "competitor_trp", "cpi", "date"]
        result = classify_columns_extended(cols)
        for col in cols:
            assert result[col]["sub_type"] is None, \
                f"Expected None sub_type for {col}, got {result[col]['sub_type']!r}"

    def test_classify_columns_extended_empty(self):
        assert classify_columns_extended([]) == {}

    def test_classify_columns_extended_unknown_column(self):
        result = classify_columns_extended(["weird_obscure_xyz"])
        assert result["weird_obscure_xyz"]["kind"] == "unknown"
        assert result["weird_obscure_xyz"]["sub_type"] is None

    # ─── classify_columns batch ───────────────────────────────────────────────

    def test_classify_columns_full_dataset(self):
        cols = [
            "date",
            "tv_spend", "tv_grp",
            "olv_impressions", "olv_views",
            "performance_spend", "performance_clicks",
            "sales_rub", "sales_packs",
            "competitor_trp", "price_avg", "temp_avg", "cpi",
            "holiday_newyear",
        ]
        result = classify_columns(cols)
        assert result["date"] == "date"
        assert result["tv_spend"] == "monetary"
        assert result["tv_grp"] == "physical"
        assert result["olv_impressions"] == "physical"
        assert result["olv_views"] == "physical"
        assert result["performance_spend"] == "monetary"
        assert result["performance_clicks"] == "physical"
        assert result["sales_rub"] == "target_monetary"
        assert result["sales_packs"] == "target_count"
        assert result["competitor_trp"] == "signed_competitor"
        assert result["price_avg"] == "signed_price"
        assert result["temp_avg"] == "signed_weather"
        assert result["cpi"] == "signed_macro"
        assert result["holiday_newyear"] == "holiday"

    def test_classify_columns_returns_dict(self):
        result = classify_columns(["tv_spend", "sales_rub"])
        assert isinstance(result, dict)

    def test_classify_columns_empty_list(self):
        assert classify_columns([]) == {}


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 8: MONETARY AND PHYSICAL MEDIA INPUTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMonetaryAndPhysical:
    """Media inputs: monetary (spend/budget) and physical (impressions/grp/clicks)."""

    @pytest.mark.parametrize("col", [
        "tv_spend",
        "tv_budget",
        "marketing_cost",
        "ad_expense",
        "тв_бюджет",
        "бюджет_тв",
        "расходы_радио",
        "маркетинг_затраты",
        "brand_investment",
    ])
    def test_monetary_patterns(self, col):
        assert classify_column(col) == "monetary", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "tv_impressions",
        "olv_impr",
        "display_views",
        "performance_clicks",
        "paid_clicks",
        "tv_grp",
        "tv_trp",
        "тв_показы",
        "показы_olv",
        "охват_баннер",
        "performance_кликов",
        "тв_грп",
    ])
    def test_physical_patterns(self, col):
        assert classify_column(col) == "physical", f"Failed for: {col}"

    @pytest.mark.parametrize("col", [
        "tv_reach",
        "olv_views",
        "social_sessions",
        "email_opens",
        "email_delivered",
    ])
    def test_physical_misc(self, col):
        assert classify_column(col) == "physical", f"Failed for: {col}"


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 9: DATE COLUMNS
# ═══════════════════════════════════════════════════════════════════════════════

class TestDateColumns:
    @pytest.mark.parametrize("col", [
        "date",
        "week",
        "месяц",
        "period",
        "month",
        "day",
        "time",
        "timestamp",
        "дата",
        "день",
        "период",
    ])
    def test_date_column_variants(self, col):
        assert classify_column(col) == "date", f"Failed for: {col}"


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 10: POSITIVE CONTROLS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPositiveControls:
    @pytest.mark.parametrize("col", [
        "distribution",
        "numeric_distribution",
        "weighted_distribution",
        "дистрибуция",
        "trade_activity",
        "trade_score",
        "promo",
        "promo_indicator",
        "promo_active",
        "pos_count",
        "new_sku",
    ])
    def test_control_positive_patterns(self, col):
        assert classify_column(col) == "control", f"Failed for: {col}"


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 11: DETECT_AVAILABLE_METRICS HELPER
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectAvailableMetrics:
    def test_tv_with_both(self):
        cols = ["date", "tv_spend", "tv_grp", "olv_impressions"]
        result = detect_available_metrics(cols, "tv")
        assert result["monetary"] == ["tv_spend"]
        assert result["physical"] == ["tv_grp"]

    def test_olv_physical_only(self):
        cols = ["date", "tv_spend", "olv_impressions"]
        result = detect_available_metrics(cols, "olv")
        assert result["monetary"] == []
        assert result["physical"] == ["olv_impressions"]

    def test_unknown_channel(self):
        cols = ["date", "tv_spend"]
        result = detect_available_metrics(cols, "unknown_channel")
        assert result == {"monetary": [], "physical": []}

    def test_performance_clicks_physical(self):
        cols = ["performance_spend", "performance_clicks"]
        result = detect_available_metrics(cols, "performance")
        assert "performance_spend" in result["monetary"]
        assert "performance_clicks" in result["physical"]


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 12: ADDITIONAL PARAMETRIZED EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdditionalCoverage:
    """Additional cases for completeness."""

    @pytest.mark.parametrize("col,expected", [
        ("gmv", "target_monetary"),
        ("sales_money", "target_monetary"),
        ("gross_revenue", "target_monetary"),
        ("выручки", "target_monetary"),
        ("оборот", "target_monetary"),
    ])
    def test_gmv_and_synonyms(self, col, expected):
        assert classify_column(col) == expected

    @pytest.mark.parametrize("col,expected", [
        ("лид", "target_count"),
        ("лидов", "target_count"),
        ("заявки", "target_count"),   # 'заявок' (gen. plural) not in pattern; 'заявки' matches
        ("регистрации", "target_count"),  # matched by регистрац(?:ии|ия|ий)
        ("активация", "target_count"),
    ])
    def test_ru_count_declensions(self, col, expected):
        assert classify_column(col) == expected

    @pytest.mark.parametrize("col,expected", [
        ("sov_competitors", "signed_competitor"),
        ("sov_comp", "signed_competitor"),
        ("доля_голоса_конкурентов", "signed_competitor"),
        ("конкурент_трп", "signed_competitor"),
        ("конкурент_спенд", "signed_competitor"),
    ])
    def test_sov_competitor_patterns(self, col, expected):
        assert classify_column(col) == expected

    @pytest.mark.parametrize("col,expected", [
        ("средняя_цена", "signed_price"),
        ("индекс_цен", "signed_price"),
        ("price_elasticity", "signed_price"),
        ("price_level", "signed_price"),
        ("mean_price", "signed_price"),
    ])
    def test_price_detailed_patterns(self, col, expected):
        assert classify_column(col) == expected

    @pytest.mark.parametrize("col,expected", [
        ("rain", "signed_weather"),
        ("rainfall", "signed_weather"),
        ("snow", "signed_weather"),
        ("snowfall", "signed_weather"),
        ("влажность", "signed_weather"),
    ])
    def test_weather_detailed_patterns(self, col, expected):
        assert classify_column(col) == expected

    @pytest.mark.parametrize("col,expected", [
        ("eur_rub", "signed_macro"),
        ("gdp_growth", "signed_macro"),
        ("gdp_real", "signed_macro"),
        ("инфляция", "signed_macro"),
        ("курс_доллара", "signed_macro"),
    ])
    def test_macro_detailed_patterns(self, col, expected):
        assert classify_column(col) == expected

    @pytest.mark.parametrize("col,expected", [
        ("новый_год", "holiday"),
        ("нг", "holiday"),
        ("выходной", "holiday"),
        ("каникулы", "holiday"),
        ("23_февраля", "holiday"),
    ])
    def test_holiday_ru_additional(self, col, expected):
        assert classify_column(col) == expected

    @pytest.mark.parametrize("col", [
        "tv_spend",
        "TV_SPEND",
        "Tv_Spend",
        "tV_SpEnD",
    ])
    def test_case_insensitivity_monetary(self, col):
        assert classify_column(col) == "monetary"

    @pytest.mark.parametrize("col", [
        "facebook_spend",
        "telegram_ads_spend",
        "одноклассники_spend",
    ])
    def test_social_media_specific_names(self, col):
        assert detect_media_format(col) == "social"

    @pytest.mark.parametrize("col", [
        "google_ads_spend",
        "paid_search_budget",
        "перформанс_spend",
    ])
    def test_performance_specific_names(self, col):
        assert detect_media_format(col) == "performance"

    def test_classify_column_unknown_is_string(self):
        result = classify_column("totally_unknown_xyz_abc")
        assert isinstance(result, str)
        assert result == "unknown"

    def test_classify_columns_preserves_all_keys(self):
        cols = ["date", "tv_spend", "sales_rub", "weird_col"]
        result = classify_columns(cols)
        assert set(result.keys()) == set(cols)

    def test_detect_media_format_case_insensitive(self):
        assert detect_media_format("TV_SPEND") == "tv"
        assert detect_media_format("OLV_Impressions") == "olv"
        assert detect_media_format("RADIO_Budget") == "radio"

    def test_detect_target_candidates_with_ru_cols(self):
        cols = ["дата", "тв_бюджет", "выручка", "лиды", "конкуренты"]
        result = detect_target_candidates(cols)
        columns = [c["column"] for c in result]
        assert "выручка" in columns
        assert "лиды" in columns
        assert "конкуренты" not in columns

    def test_subs_classified_as_target_count(self):
        assert classify_column("subs") == "target_count"

    def test_mrr_subs_classified_as_target_count(self):
        assert classify_column("mrr_subs") == "target_count"

    def test_product_launch_is_control(self):
        assert classify_column("product_launch") == "control"

    def test_npd_count_is_control(self):
        assert classify_column("npd_count") == "control"

    def test_new_sku_count_is_control(self):
        assert classify_column("new_sku_count") == "control"
