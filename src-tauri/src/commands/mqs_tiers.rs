//! Единый источник порогов MQS (Model Quality Score) для Rust-слоя отчётов.
//!
//! Зеркало питоновского канона `sidecar/econometrica/utils/diagnostics.py::_MQS_TIERS`
//! и его JS-зеркала `src/lib/mqs-tiers.js::MQS_TIERS`. Инцидент L16 (2026-04-29):
//! MQS=70 показывал «Хорошее» в одном месте и «приемлемо» в другом, потому что
//! слой представления держал свою копию порогов. HTML/PPTX перевели на
//! `mqs_tier_info()`, интерфейс — на `mqs-tiers.js`; Rust-отчёты (`report.rs`)
//! до 2026-07-27 держали СВОЮ лестницу 80/60 в четырёх местах (grade строки,
//! две рекомендации, глоссарий) — рецидив того же дефекта в третьем языке.
//!
//! Паритетный тест `sidecar/econometrica/tests/test_mqs_tier_rust_single_source.py`
//! сверяет таблицу ниже с питоновским `_MQS_TIERS` порог-в-порог, ярлык-в-ярлык.
//! Правка одной стороны без второй красит тест.

/// Одна ступень канона: нижняя граница (включительно), имя уровня, русский
/// ярлык, цвет. Порядок — от старшего уровня к младшему, как в Python/JS.
pub struct MqsTier {
    pub min: f64,
    pub tier: &'static str,
    pub label: &'static str,
    pub color: &'static str,
}

/// Канон 85/70/55/40 — дословно `_MQS_TIERS` (diagnostics.py).
pub const MQS_TIERS: &[MqsTier] = &[
    MqsTier { min: 85.0, tier: "excellent", label: "Отличное", color: "#22c55e" },
    MqsTier { min: 70.0, tier: "good", label: "Хорошее", color: "#3b82f6" },
    MqsTier { min: 55.0, tier: "acceptable", label: "Приемлемое", color: "#f59e0b" },
    MqsTier { min: 40.0, tier: "weak", label: "Слабое", color: "#f97316" },
    MqsTier { min: 0.0, tier: "poor", label: "Ненадёжное", color: "#ef4444" },
];

/// Ступень канона по посчитанному баллу. Поведение — «нижняя граница
/// включительно»: score==85.0 попадает в `excellent`, а не в `good`.
/// Вызывать только когда балл реально посчитан (не None) - отсутствие
/// метрики обрабатывается вызывающим кодом отдельно (см. `MQS_ABSENT_TEXT`
/// в `report.rs`), а не подстановкой нуля/среднего уровня сюда.
pub fn mqs_tier_for_score(score: f64) -> &'static MqsTier {
    MQS_TIERS
        .iter()
        .find(|t| score >= t.min)
        .unwrap_or_else(|| MQS_TIERS.last().expect("MQS_TIERS не пуст"))
}

/// Русский ярлык уровня по баллу.
pub fn mqs_label_for_score(score: f64) -> &'static str {
    mqs_tier_for_score(score).label
}

/// Проходит ли модель порог, начиная с которого на её выводы можно опираться
/// в планировании. Канон — уровень «Хорошее» и выше (дословно `mqsIsDependable`
/// из `src/lib/mqs-tiers.js`).
pub fn mqs_is_dependable(score: f64) -> bool {
    matches!(mqs_tier_for_score(score).tier, "excellent" | "good")
}

/// Слабый/ненадёжный уровень — дословно `WEAK_TIERS` из
/// `sidecar/econometrica/utils/optimizer_honesty.py`, уже принятый канон для
/// «модель требует внимания» в честности оптимизатора (M2).
pub fn mqs_is_weak(score: f64) -> bool {
    matches!(mqs_tier_for_score(score).tier, "weak" | "poor")
}

/// Средний уровень («Приемлемое») — не слабый и не надёжный: результаты
/// годятся для ориентировки, но не для точных решений. Заведена 2026-07-27
/// (внешний аудит, Medium): блок рекомендаций `report.rs` ветвился только по
/// `mqs_is_weak`/`mqs_is_dependable` — уровень «Приемлемое» не получал НИ
/// ОДНОЙ строки, а молчание в разделе рекомендаций читается как «замечаний
/// нет», то есть отсутствие вердикта работало как положительный вердикт.
/// Три предиката покрывают все пять ступеней канона ровно по одному разу.
pub fn mqs_is_acceptable(score: f64) -> bool {
    matches!(mqs_tier_for_score(score).tier, "acceptable")
}

/// Ярлык, пришедший ИЗВНЕ (например `diagnostics.mqs.tier_label` из payload
/// бэкенда), принадлежит канону? Заведено 2026-07-26 (внешний аудит седьмой
/// волны): слой представления доверял полю как есть — непустой строки было
/// достаточно, и значение ключа `tier` («excellent» вместо «Отличное»)
/// доезжало до клиента по-английски.
pub fn is_canon_label(label: &str) -> bool {
    MQS_TIERS.iter().any(|t| t.label == label)
}

/// Итоговый ярлык уровня: внешний, если он принадлежит канону И совпадает с
/// тем, что канон даёт для ЭТОГО балла, иначе - производный от балла.
/// «Нет числа - нет подписи» (INV-106) эта функция не решает - вызывающий
/// обязан не звать её при `mqs == None` и печатать честное отсутствие
/// (`MQS_ABSENT_TEXT`) вместо неё.
///
/// Находка внешнего аудита (2026-07-27): раньше проверялась только
/// ПРИНАДЛЕЖНОСТЬ ярлыка набору канона, без сверки с баллом -
/// `resolve_mqs_label(42.0, Some("Отличное"))` возвращал «Отличное», хотя
/// канон для 42.0 даёт «Слабое». Достижимо не автоматическим кодом
/// приложения (там score/tier_label всегда пишутся атомарно одним вызовом
/// `mqs_tier_info`), а через `results/model-diagnostics.json` на диске -
/// обычный неподписанный JSON, для которого в этом же репозитории уже есть
/// прецедент внешней точечной правки (`tools/recompute_mqs.py`, миграция
/// вне приложения). Данные первичны: при расхождении уровень считается ИЗ
/// БАЛЛА, а расхождение не проглатывается молча - уходит в лог (диагностика,
/// не клиентский текст). Симметричный фикс на Python-стороне -
/// `utils.diagnostics.resolve_mqs_tier_label` (aurora_html/sections.py).
pub fn resolve_mqs_label(score: f64, external: Option<&str>) -> &'static str {
    let canon_label = mqs_label_for_score(score);
    if let Some(l) = external {
        if is_canon_label(l) {
            if l == canon_label {
                return canon_label;
            }
            log::warn!(
                "MQS: внешний ярлык «{l}» не соответствует канону для балла \
                 {score:.1} (канон: «{canon_label}») - используется ярлык из балла"
            );
        }
    }
    canon_label
}

/// Текст шкалы для глоссария/подсказок — собирается из канона, а не пишется
/// числами руками (иначе поведение и его описание расходятся молча — ровно
/// то, что нашёл внешний аудит седьмой волны в MQSBadge интерфейса).
///
/// Единая форма с JS-зеркалом `src/lib/mqs-tiers.js::mqsScaleText` (находка
/// внешнего аудита 2026-07-27 — здесь была нотация «X ≤ MQS < Y», понятная
/// программисту, а не клиенту-маркетологу, читающему глоссарий отчёта; JS
/// рядом печатал «70–< 85», что само по себе читалось как опечатка).
/// Целочисленные диапазоны без знаков ≤/≥/<: верхняя граница каждого
/// диапазона — целое число ПЕРЕД нижней границей следующего уровня (85 →
/// верхняя граница «Хорошего» = 84), поэтому диапазоны не пересекаются
/// текстуально ни на одном числе, оставаясь в согласии с поведением «нижняя
/// граница включительно» у `mqs_tier_for_score`.
pub fn mqs_scale_text() -> String {
    let mut parts: Vec<String> = Vec::with_capacity(MQS_TIERS.len());
    for (i, t) in MQS_TIERS.iter().enumerate() {
        let upper = if i == 0 { 100.0 } else { MQS_TIERS[i - 1].min - 1.0 };
        parts.push(format!("{:.0}\u{2013}{upper:.0} \u{2013} {}", t.min, t.label));
    }
    parts.join(", ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn boundaries_inclusive_lower_per_canon() {
        assert_eq!(mqs_tier_for_score(85.0).tier, "excellent");
        assert_eq!(mqs_tier_for_score(84.9).tier, "good");
        assert_eq!(mqs_tier_for_score(70.0).tier, "good");
        assert_eq!(mqs_tier_for_score(69.9).tier, "acceptable");
        assert_eq!(mqs_tier_for_score(55.0).tier, "acceptable");
        assert_eq!(mqs_tier_for_score(54.9).tier, "weak");
        assert_eq!(mqs_tier_for_score(40.0).tier, "weak");
        assert_eq!(mqs_tier_for_score(39.9).tier, "poor");
        assert_eq!(mqs_tier_for_score(0.0).tier, "poor");
    }

    #[test]
    fn incident_case_70_is_horoshee_not_priemlemoe() {
        assert_eq!(mqs_label_for_score(70.0), "Хорошее");
    }

    #[test]
    fn incident_case_82_is_horoshee_not_otlichnoe() {
        assert_eq!(mqs_label_for_score(82.0), "Хорошее");
    }

    #[test]
    fn is_dependable_matches_js_mqs_is_dependable() {
        assert!(!mqs_is_dependable(69.9));
        assert!(mqs_is_dependable(70.0));
        assert!(mqs_is_dependable(90.0));
    }

    #[test]
    fn is_weak_matches_optimizer_honesty_weak_tiers() {
        assert!(!mqs_is_weak(55.0));
        assert!(mqs_is_weak(54.9));
        assert!(mqs_is_weak(0.0));
    }

    #[test]
    fn is_acceptable_covers_only_the_middle_tier() {
        assert!(!mqs_is_acceptable(70.0));
        assert!(mqs_is_acceptable(69.9));
        assert!(mqs_is_acceptable(55.0));
        assert!(!mqs_is_acceptable(54.9));
    }

    #[test]
    fn three_verdict_predicates_partition_all_five_tiers_exactly_once() {
        // Регресс-тест на дефект "Приемлемое" без единой рекомендации
        // (2026-07-27): ровно один из трёх предикатов обязан быть true на
        // любом балле - иначе снова возможна немая середина или двойной вердикт.
        for score in [95.0, 85.0, 84.0, 70.0, 69.0, 55.0, 54.0, 40.0, 39.0, 0.0] {
            let flags = [mqs_is_weak(score), mqs_is_acceptable(score), mqs_is_dependable(score)];
            let true_count = flags.iter().filter(|f| **f).count();
            assert_eq!(
                true_count, 1,
                "балл {score}: ожидался ровно один истинный предикат из weak/acceptable/dependable, получено {true_count}"
            );
        }
    }

    #[test]
    fn resolve_label_prefers_valid_external_label() {
        assert_eq!(resolve_mqs_label(70.0, Some("Хорошее")), "Хорошее");
    }

    #[test]
    fn resolve_label_rejects_alien_label_and_derives_from_score() {
        // "Хорошо" - устаревший/чужой ярлык (не "Хорошее" канона), "excellent" -
        // ключ tier вместо label. Оба отбрасываются, уровень считается из балла.
        assert_eq!(resolve_mqs_label(70.0, Some("Хорошо")), "Хорошее");
        assert_eq!(resolve_mqs_label(92.0, Some("excellent")), "Отличное");
        assert_eq!(resolve_mqs_label(70.0, None), "Хорошее");
    }

    #[test]
    fn resolve_label_rejects_canon_label_that_does_not_match_score() {
        // Находка внешнего аудита (2026-07-27): "Отличное" ПРИНАДЛЕЖИТ канону,
        // но для балла 42.0 канон даёт "Слабое" (weak). Раньше членство в
        // наборе было достаточно - функция возвращала чужой ярлык как есть.
        // Данные первичны: при расхождении уровень считается ИЗ БАЛЛА.
        assert_eq!(
            resolve_mqs_label(42.0, Some("Отличное")),
            "Слабое",
            "внешний ярлык из канона, но не для этого балла - обязан быть отброшен"
        );
        // Тот же случай на другой паре границ (обратное направление).
        assert_eq!(resolve_mqs_label(92.0, Some("Слабое")), "Отличное");
        // Согласованный ярлык (совпадает с каноном для балла) - принимается.
        assert_eq!(resolve_mqs_label(70.0, Some("Хорошее")), "Хорошее");
    }

    #[test]
    fn scale_text_covers_all_five_tiers_without_overlap() {
        let s = mqs_scale_text();
        for t in MQS_TIERS {
            assert!(s.contains(t.label), "шкала не упоминает уровень {}", t.label);
        }
        // Целочисленные диапазоны (2026-07-27, единая форма с JS-зеркалом):
        // верхняя граница каждого диапазона - целое ПЕРЕД нижней границей
        // следующего уровня, поэтому ни одно число не встречается дважды.
        assert!(s.contains("85\u{2013}100"));
        assert!(s.contains("70\u{2013}84"));
        assert!(s.contains("55\u{2013}69"));
        assert!(s.contains("40\u{2013}54"));
        assert!(s.contains("0\u{2013}39"));
        assert!(!s.contains('\u{2264}'));
        assert!(!s.contains('\u{2265}'));
        assert!(!s.contains('<'));
        assert!(!s.contains('\u{2014}')); // короткое тире, не em-dash
    }
}
