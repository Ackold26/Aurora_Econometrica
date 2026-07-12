use log::{info, warn};
use serde::{Deserialize, Serialize};
use std::path::Path;

/// Cabinet metadata for the GUI.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CabinetInfo {
    pub id: String,
    pub name: String,
    pub description: String,
    pub icon: String,
    pub color: String,
}

/// Hardcoded cabinet definitions matching the New_AI_Agency structure.
pub fn get_cabinet_definitions() -> Vec<CabinetInfo> {
    vec![
        CabinetInfo {
            id: "social-listening".to_string(),
            name: "Social Listening".to_string(),
            description: "Мониторинг отзывов, комментариев на маркетплейсах и\u{00a0}площадках".to_string(),
            icon: "👁️".to_string(),
            color: "#06B6D4".to_string(), // cyan
        },
        CabinetInfo {
            id: "media-analyst".to_string(),
            name: "Медиа-аналитик".to_string(),
            description: "Аналитика медиа, комментарии к слайдам, выводы по данным".to_string(),
            icon: "📈".to_string(),
            color: "#3B82F6".to_string(), // blue
        },
        CabinetInfo {
            id: "communication-analyst".to_string(),
            name: "Коммуникационный аналитик".to_string(),
            description: "Анализ коммуникаций, мониторинг медиаполя, оценка эффективности".to_string(),
            icon: "📊".to_string(),
            color: "#3B82F6".to_string(), // blue
        },
        CabinetInfo {
            id: "communication-strategist".to_string(),
            name: "Коммуникационный стратег".to_string(),
            description: "Коммуникационная стратегия, позиционирование, ключевые сообщения".to_string(),
            icon: "🧭".to_string(),
            color: "#8B5CF6".to_string(), // purple
        },
        CabinetInfo {
            id: "focus-groups".to_string(),
            name: "Синтетические фокус-группы".to_string(),
            description: "ИИ-фокус-группы для тестирования стратегий и креативных концепций".to_string(),
            icon: "🎯".to_string(),
            color: "#F97316".to_string(), // orange
        },
        CabinetInfo {
            id: "creative-director".to_string(),
            name: "Креативный директор".to_string(),
            description: "Креативные концепции, бренд-стратегия, визуальные решения".to_string(),
            icon: "🎨".to_string(),
            color: "#EC4899".to_string(), // pink
        },
        CabinetInfo {
            id: "lawyer-contracts".to_string(),
            name: "Юрист - Контракты".to_string(),
            description: "Проверка договоров, шаблоны, анализ\u{00a0}контрагентов".to_string(),
            icon: "📋".to_string(),
            color: "#10B981".to_string(), // green
        },
        CabinetInfo {
            id: "lawyer-claims".to_string(),
            name: "Юрист - NDA и претензии".to_string(),
            description: "NDA, претензионная работа, досудебные и судебные споры".to_string(),
            icon: "⚖️".to_string(),
            color: "#F59E0B".to_string(), // amber
        },
        CabinetInfo {
            id: "lawyer-advertising".to_string(),
            name: "Юрист - Реклама".to_string(),
            description: "Проверка рекламы на соответствие закону, комплаенс".to_string(),
            icon: "🛡️".to_string(),
            color: "#EF4444".to_string(), // red
        },
        CabinetInfo {
            id: "doc-master".to_string(),
            name: "Доку-мастер".to_string(),
            description: "Генерация документов из медиапланов и\u{00a0}шаблонов".to_string(),
            icon: "📄".to_string(),
            color: "#6366F1".to_string(), // indigo
        },
        CabinetInfo {
            id: "econometrist".to_string(),
            name: "Эконометрист".to_string(),
            description: "Моделирование вклада медиаканалов, декомпозиция продаж, оптимизация бюджета".to_string(),
            icon: "📐".to_string(),
            color: "#0EA5E9".to_string(), // sky-blue
        },
        CabinetInfo {
            id: "copywriter".to_string(),
            name: "Копирайтер".to_string(),
            description: "Генерация и адаптация текстов голосом\u{00a0}бренда".to_string(),
            icon: "✍️".to_string(),
            color: "#14B8A6".to_string(), // teal (unique, not conflicting with social-listening cyan)
        },
        CabinetInfo {
            id: "art-director".to_string(),
            name: "Арт-директор".to_string(),
            description: "Генерация визуалов, макетов, адаптация под\u{00a0}форматы".to_string(),
            icon: "🎬".to_string(),
            color: "#7C3AED".to_string(), // violet
        },
    ]
}

/// Filter cabinet list by product type.
/// Agency/creative-hub → all cabinets; other products → specific subset.
pub fn filter_by_product(product: &str, cabinets: Vec<CabinetInfo>) -> Vec<CabinetInfo> {
    let allowed: Option<&[&str]> = match product {
        "agency" | "creative-hub" => None, // all cabinets
        "analytics-hub" => Some(&["media-analyst"]),
        // Облачная редакция: кабинет-советник econometrist (Claude). Локальная редакция
        // (152-ФЗ, сборка без feature cloud_advisors): только MMM-пайплайн, без cloud-кабинетов.
        #[cfg(feature = "cloud_advisors")]
        "econometrica" => Some(&["econometrist"]),
        #[cfg(not(feature = "cloud_advisors"))]
        "econometrica" => Some(&[]),
        "marketing" => Some(&["media-analyst", "communication-analyst"]),
        "legal" => Some(&["lawyer-contracts", "lawyer-claims", "lawyer-advertising"]),
        "creative" => Some(&["creative-director", "communication-strategist", "focus-groups", "copywriter", "art-director"]),
        "docmaster" => Some(&["doc-master"]),
        "prmaster" => Some(&["communication-analyst", "social-listening", "copywriter"]),
        _ => None,
    };
    match allowed {
        Some(ids) => cabinets.into_iter().filter(|c| ids.contains(&c.id.as_str())).collect(),
        None => cabinets,
    }
}

/// Command button for a cabinet.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CabinetCommand {
    pub command: String,
    pub label: String,
    pub group: String,
}

/// Return commands available for a given cabinet.
pub fn get_commands_for_cabinet(cabinet_id: &str) -> Vec<CabinetCommand> {
    let cmds: Vec<(&str, &str, &str)> = match cabinet_id {
        "lawyer-contracts" => vec![
            ("/contract", "Проверить договор", "Основные"),
            ("/contract-batch", "Проверить все", "Основные"),
            ("/contract-риски", "Только риски", "Основные"),
            ("/contract-counter-docx", "Редлайн Word", "Редактирование"),
            ("/contract-counter", "Протокол разногласий", "Редактирование"),
            ("/contract-сравнить", "Сравнить версии", "Редактирование"),
            ("/contract-template", "Шаблон договора", "Инструменты"),
            ("/contract-deadlines", "Дедлайны", "Инструменты"),
            ("/contract-add-notes", "Заметки", "Инструменты"),
            ("/contract-checklist", "Экспресс чек-лист", "Инструменты"),
            ("/contract-агентский", "Агентский", "Спец. режимы"),
            ("/contract-услуги", "Услуги", "Спец. режимы"),
            ("/contract-подрядчик", "Подряд", "Спец. режимы"),
            ("/contract-renewal-check", "Проверка пролонгации", "Инструменты"),
            ("/contract-international", "Международный контракт", "Инструменты"),
        ],
        "lawyer-advertising" => vec![
            ("/qa", "Проверить рекламу", "Основные"),
            ("/qa-batch", "Проверить все", "Основные"),
            ("/qa-fix-docx", "Правки Word", "Редактирование"),
            ("/qa-fix", "Верификация правок", "Редактирование"),
            ("/qa-stats", "Статистика", "Инструменты"),
            ("/qa-фарма", "Фарма", "Спец. режимы"),
            ("/qa-fmcg", "FMCG", "Спец. режимы"),
            ("/qa-финансы", "Финансы", "Спец. режимы"),
            ("/qa-b2b", "B2B", "Спец. режимы"),
            ("/qa-манифест", "Манифест", "Спец. режимы"),
            ("/qa-template", "Шаблоны формулировок", "Инструменты"),
            ("/qa-ord", "Проверка ОРД", "Комплаенс"),
            ("/qa-platform", "Правила площадки", "Комплаенс"),
            ("/qa-visual-brief", "Визуальный чек-лист", "Комплаенс"),
        ],
        "media-analyst" => vec![
            ("/analytics", "TOTAL ANALYTICS", "Команды"),
            ("/check", "Анализ выводов", "Инструменты"),
            ("/action-title", "Мастер заголовков", "Команды"),
            ("/executive-summary", "Ключевые выводы", "Команды"),
            ("/bridges", "Связующие выводы", "Команды"),
            ("/batch-analytics", "Пакетная обработка", "Инструменты"),
            ("/data-analysis", "Анализ данных", "Инструменты"),
            ("/benchmark", "Бенчмарки", "Инструменты"),
            ("/aurora-index", "Быстрый анализ", "Инструменты"),
        ],
        "communication-analyst" => vec![
            ("/media-monitor", "Мониторинг медиаполя", "Основные"),
            ("/sentiment", "Тональность", "Основные"),
            ("/effectiveness", "Отчёт по эффективности", "Основные"),
            ("/competitors", "Анализ конкурентов", "Аналитика"),
            ("/key-messages", "Ключевые сообщения", "Аналитика"),
            ("/crisis-analysis", "Кризисный анализ", "Аналитика"),
            ("/narrative-tracking", "Нарративный анализ", "Аналитика"),
            ("/influencer-impact", "Анализ лидеров мнений", "Аналитика"),
            ("/pr-attribution", "PR-атрибуция", "Аналитика"),
            ("/batch-analysis", "Мета-анализ блоков", "Аналитика"),
        ],
        "communication-strategist" => vec![
            ("/strategy", "Полный цикл стратегии", "Основные"),
            ("/positioning", "Позиционирование", "Основные"),
            ("/brief", "Креативный бриф", "Основные"),
            ("/messages", "Messaging framework", "Основные"),
            ("/comm-audit", "Коммуникационный аудит", "Аналитика"),
            ("/quick-diagnostics", "Экспресс-диагностика", "Инструменты"),
            ("/cep-audit", "Аудит CEP", "Инструменты"),
            ("/crisis-strategy", "Антикризисная стратегия", "Инструменты"),
        ],
        "creative-director" => vec![
            ("/cycle", "Полный цикл", "Основные"),
            ("/creative-audit", "Аудит креатива", "Аналитика"),
            ("/brand-memory", "ДНК бренда", "Аналитика"),
            ("/creative-strategy", "Креативная стратегия", "Аналитика"),
            ("/creative", "Креативные концепции", "Креатив"),
            ("/ad-variants", "Варианты объявлений", "Креатив"),
            ("/format-creative", "Креатив по форматам", "Креатив"),
            ("/competitive-creative", "Деконструкция конкурента", "Аналитика"),
            ("/reference-library", "Библиотека кейсов", "Инструменты"),
        ],
        "focus-groups" => vec![
            ("/strategy-fg", "Стратегическая ФГ", "Фокус-группы"),
            ("/creative-fg", "Креативная ФГ", "Фокус-группы"),
            ("/concept-test", "Тест концепций", "Тестирование"),
            ("/packaging-test", "Тест упаковки", "Тестирование"),
            ("/name-test", "Тест названий", "Тестирование"),
            ("/ux-journey", "Тест UX", "Тестирование"),
            ("/message-prioritization", "Приоритизация сообщений", "Тестирование"),
        ],
        "social-listening" => vec![
            ("/search-reviews", "Поиск отзывов", "Основные"),
            ("/analyze-sentiment", "Анализ тональности", "Основные"),
            ("/report", "Сводный отчёт", "Основные"),
            ("/track-mentions", "Отслеживание упоминаний", "Мониторинг"),
            ("/competitors-buzz", "Конкуренты", "Мониторинг"),
            ("/crisis-alert", "Кризисный сигнал", "Мониторинг"),
            ("/jtbd-extraction", "Извлечение JTBD", "Аналитика"),
            ("/trend-detection", "Детекция трендов", "Мониторинг"),
            ("/batch-analysis", "Мета-анализ блоков", "Аналитика"),
        ],
        "lawyer-claims" => vec![
            ("/pretension-write", "Написать претензию", "Претензии"),
            ("/pretension-reply", "Ответить на претензию", "Претензии"),
            ("/pretension-analyze", "Анализ претензии", "Претензии"),
            ("/pretension-timeline", "Хронология", "Претензии"),
            ("/nda-draft", "Составить NDA", "NDA"),
            ("/nda-analyze", "Анализ NDA", "NDA"),
            ("/nda-counter", "Протокол по NDA", "NDA"),
            ("/nda-counter-docx", "Редлайн NDA", "NDA"),
            ("/settlement-plan", "План урегулирования", "Претензии"),
            ("/nda-breach-response", "Утечка NDA", "NDA"),
        ],
        "doc-master" => vec![
            ("/plan-to-doc", "Медиаплан → Приложение", "Основные"),
            ("/doc-batch", "Комплекты документов", "Основные"),
            ("/plan-check", "Проверить медиаплан", "Инструменты"),
        ],
        // Econometrist - консультант ПОВЕРХ pipeline.
        // Pipeline делает MMM (валидация, MCMC, оптимизация, PPTX). Кабинет осмысляет и
        // расширяет результат - не дублирует расчёты, а отвечает на вопросы «что значит»,
        // «что делать дальше», «что собрать». Старые 9 MMM-команд (/mmm-prepare, /mmm-model,
        // /mmm-decomposition, /mmm-optimize, /mmm-scenarios, /mmm-report, /mmm-full,
        // /mmm-to-doc, /mmm-to-slides) СКРЫТЫ из UI, но промпты в .claude/commands/
        // остаются - ручной ввод в поле всё ещё работает (backward compat).
        "econometrist" => vec![
            ("/interpret-model", "Объяснить результаты", "Смысл"),
            ("/why-channel", "Почему у канала такой ROI", "Смысл"),
            ("/explain-ratio", "Разбор Ratio данных", "Смысл"),
            ("/pilot-design", "План пилота 4–6 недель", "Стратегия"),
            ("/next-quarter-plan", "План следующего квартала", "Стратегия"),
            ("/data-gaps", "Чего не хватает в данных", "Стратегия"),
            ("/awareness-forecast", "Прогноз awareness", "Awareness"),
            ("/awareness-to-sales", "Awareness → Продажи", "Awareness"),
        ],
        "copywriter" => vec![
            ("/write", "Написать текст", "Основные"),
            ("/adapt", "Адаптировать текст", "Основные"),
            ("/audit", "Проверить текст", "Основные"),
            ("/pack", "Мультиформатный пакет", "Основные"),
            ("/mine", "Message Mining", "Бренд"),
            ("/brand-setup", "Настройка бренда", "Бренд"),
            ("/format-add", "Добавить формат", "Настройки"),
        ],
        "art-director" => vec![
            ("/visual", "Создать визуал", "Основные"),
            ("/adapt", "Адаптировать формат", "Основные"),
            ("/pack", "Мультиформатный пакет", "Основные"),
            ("/edit", "Редактировать", "Основные"),
            ("/logo", "Логотип", "Айдентика"),
            ("/identity", "Полная айдентика", "Айдентика"),
            ("/packaging", "Дизайн упаковки", "Айдентика"),
            ("/brand-visual", "Визуальный DNA", "Бренд"),
            ("/storyboard", "Раскадровка", "Видео"),
        ],
        _ => vec![],
    };

    cmds.into_iter()
        .map(|(command, label, group)| CabinetCommand {
            command: command.to_string(),
            label: label.to_string(),
            group: group.to_string(),
        })
        .collect()
}

/// Map cabinet_id to its folder name. Folder name == id (all Latin, no spaces).
pub fn cabinet_folder_name(cabinet_id: &str) -> &str {
    cabinet_id
}

// ── Dynamic loaders (content pack with hardcoded fallback) ────────────────────

/// Cabinet info extended with commands - used for cabinets.json deserialization.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct CabinetInfoExtended {
    #[serde(flatten)]
    info: CabinetInfo,
    commands: Vec<CabinetCommand>,
}

#[derive(Debug, Deserialize)]
struct CabinetsPack {
    cabinets: Vec<CabinetInfoExtended>,
}

/// Load cabinet definitions from content pack with hardcoded fallback.
pub fn get_cabinet_definitions_dynamic(app_local_data_dir: &Path) -> Vec<CabinetInfo> {
    if let Ok(json_str) = super::content_pack::load_pack_file(app_local_data_dir, "cabinets.json") { match serde_json::from_str::<CabinetsPack>(&json_str) {
        Ok(pack) => {
            info!("Loaded {} cabinets from content pack", pack.cabinets.len());
            return pack.cabinets.into_iter().map(|c| c.info).collect();
        }
        Err(e) => warn!("Failed to parse cabinets.json: {e}, using hardcoded fallback"),
    } }
    get_cabinet_definitions()
}

/// Load commands for a cabinet from content pack with hardcoded fallback.
pub fn get_commands_dynamic(app_local_data_dir: &Path, cabinet_id: &str) -> Vec<CabinetCommand> {
    if let Ok(json_str) = super::content_pack::load_pack_file(app_local_data_dir, "cabinets.json") {
        if let Ok(pack) = serde_json::from_str::<CabinetsPack>(&json_str) {
            if let Some(cab) = pack.cabinets.iter().find(|c| c.info.id == cabinet_id) {
                return cab.commands.clone();
            }
        }
    }
    get_commands_for_cabinet(cabinet_id)
}

/// Validate cabinet_id format for path-traversal protection.
///
/// Accepts any non-empty string containing only ASCII alphanumeric chars, dashes, and underscores.
/// This allows dynamically added cabinets (via cabinets.json) while preventing path traversal.
pub fn validate_cabinet_id(cabinet_id: &str) -> Result<&str, String> {
    if cabinet_id.is_empty() {
        return Err("Cabinet ID cannot be empty".to_string());
    }
    if cabinet_id.len() > 64 {
        return Err(format!("Cabinet ID too long: {}", cabinet_id));
    }
    if cabinet_id
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        Ok(cabinet_id)
    } else {
        Err(format!("Invalid cabinet ID: {}", cabinet_id))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_thirteen_cabinets_defined() {
        let cabinets = get_cabinet_definitions();
        assert_eq!(cabinets.len(), 13);
    }

    #[test]
    fn cabinet_ids_are_valid() {
        let cabinets = get_cabinet_definitions();
        let expected_ids = [
            "media-analyst",
            "communication-analyst",
            "communication-strategist",
            "creative-director",
            "focus-groups",
            "social-listening",
            "lawyer-contracts",
            "lawyer-claims",
            "lawyer-advertising",
            "doc-master",
            "econometrist",
            "copywriter",
            "art-director",
        ];
        let ids: Vec<&str> = cabinets.iter().map(|c| c.id.as_str()).collect();
        for expected in &expected_ids {
            assert!(ids.contains(expected), "Missing cabinet: {}", expected);
        }
    }

    #[test]
    fn every_cabinet_has_commands() {
        let cabinets = get_cabinet_definitions();
        for cab in &cabinets {
            let cmds = get_commands_for_cabinet(&cab.id);
            assert!(!cmds.is_empty(), "No commands for cabinet: {}", cab.id);
        }
    }

    #[test]
    fn command_counts_per_cabinet() {
        assert_eq!(get_commands_for_cabinet("media-analyst").len(), 9);
        assert_eq!(get_commands_for_cabinet("communication-analyst").len(), 10);
        assert_eq!(get_commands_for_cabinet("communication-strategist").len(), 8);
        assert_eq!(get_commands_for_cabinet("creative-director").len(), 9);
        assert_eq!(get_commands_for_cabinet("focus-groups").len(), 7);
        assert_eq!(get_commands_for_cabinet("social-listening").len(), 9);
        assert_eq!(get_commands_for_cabinet("lawyer-contracts").len(), 15);
        assert_eq!(get_commands_for_cabinet("lawyer-claims").len(), 10);
        assert_eq!(get_commands_for_cabinet("lawyer-advertising").len(), 14);
        assert_eq!(get_commands_for_cabinet("doc-master").len(), 3);
        assert_eq!(get_commands_for_cabinet("econometrist").len(), 8);
        assert_eq!(get_commands_for_cabinet("copywriter").len(), 7);
        assert_eq!(get_commands_for_cabinet("art-director").len(), 9);
    }

    #[test]
    fn unknown_cabinet_returns_no_commands() {
        let cmds = get_commands_for_cabinet("nonexistent");
        assert!(cmds.is_empty());
    }

    #[test]
    fn all_commands_start_with_slash() {
        let cabinets = get_cabinet_definitions();
        for cab in &cabinets {
            for cmd in get_commands_for_cabinet(&cab.id) {
                assert!(
                    cmd.command.starts_with('/'),
                    "Command '{}' in cabinet '{}' must start with /",
                    cmd.command,
                    cab.id
                );
            }
        }
    }

    #[test]
    fn cabinet_folder_name_is_identity() {
        assert_eq!(cabinet_folder_name("lawyer-contracts"), "lawyer-contracts");
        assert_eq!(cabinet_folder_name("creative-director"), "creative-director");
    }

    #[test]
    fn all_cabinets_have_color() {
        for cab in get_cabinet_definitions() {
            assert!(cab.color.starts_with('#'), "Cabinet {} missing color", cab.id);
            assert_eq!(cab.color.len(), 7, "Cabinet {} color not hex", cab.id);
        }
    }

    #[test]
    fn validate_cabinet_id_accepts_known() {
        for cab in get_cabinet_definitions() {
            assert!(validate_cabinet_id(&cab.id).is_ok(), "Should accept: {}", cab.id);
        }
    }

    #[test]
    fn validate_cabinet_id_accepts_dynamic() {
        // New cabinets added via cabinets.json must pass format validation
        assert!(validate_cabinet_id("pr-master").is_ok());
        assert!(validate_cabinet_id("marketing-analytics").is_ok());
        assert!(validate_cabinet_id("new_cabinet_123").is_ok());
    }

    #[test]
    fn validate_cabinet_id_rejects_invalid() {
        assert!(validate_cabinet_id("../etc/passwd").is_err());
        assert!(validate_cabinet_id("").is_err());
        assert!(validate_cabinet_id("foo/bar").is_err());
        assert!(validate_cabinet_id("foo\\bar").is_err());
        assert!(validate_cabinet_id("кириллица").is_err());
        assert!(validate_cabinet_id("a".repeat(65).as_str()).is_err());
    }

    // ── Dynamic loader tests ──────────────────────────────────────────────────

    #[test]
    fn dynamic_cabinets_fallback_when_no_pack() {
        let dir = tempfile::TempDir::new().unwrap();
        // No content-packs directory at all → hardcoded fallback
        let cabinets = get_cabinet_definitions_dynamic(dir.path());
        assert_eq!(cabinets.len(), 13, "Fallback must return exactly 13 hardcoded cabinets");
    }

    #[test]
    fn dynamic_cabinets_fallback_on_invalid_json() {
        let dir = tempfile::TempDir::new().unwrap();
        let packs_dir = dir.path().join("content-packs");
        std::fs::create_dir_all(&packs_dir).unwrap();
        std::fs::write(packs_dir.join("cabinets.json"), b"not valid json {{{{").unwrap();
        // Invalid JSON → graceful fallback to hardcoded
        let cabinets = get_cabinet_definitions_dynamic(dir.path());
        assert_eq!(cabinets.len(), 13);
    }

    #[test]
    fn dynamic_cabinets_loaded_from_pack() {
        let dir = tempfile::TempDir::new().unwrap();
        let packs_dir = dir.path().join("content-packs");
        std::fs::create_dir_all(&packs_dir).unwrap();
        let json = r##"{
            "cabinets": [
                {"id":"pack-cab-1","name":"Pack Cabinet 1","description":"Desc 1","icon":"X","color":"#FF0000","commands":[{"command":"/cmd1","label":"Cmd 1","group":"Main"}]},
                {"id":"pack-cab-2","name":"Pack Cabinet 2","description":"Desc 2","icon":"Y","color":"#00FF00","commands":[]}
            ]
        }"##;
        std::fs::write(packs_dir.join("cabinets.json"), json).unwrap();

        let cabinets = get_cabinet_definitions_dynamic(dir.path());
        assert_eq!(cabinets.len(), 2);
        assert_eq!(cabinets[0].id, "pack-cab-1");
        assert_eq!(cabinets[1].id, "pack-cab-2");
        assert_eq!(cabinets[0].color, "#FF0000");
    }

    #[test]
    fn dynamic_cabinets_pack_overrides_hardcoded_count() {
        let dir = tempfile::TempDir::new().unwrap();
        let packs_dir = dir.path().join("content-packs");
        std::fs::create_dir_all(&packs_dir).unwrap();
        // Pack with a single cabinet - should replace all 13 hardcoded ones
        let json = r##"{"cabinets":[{"id":"only-one","name":"Only","description":"","icon":"O","color":"#123456","commands":[]}]}"##;
        std::fs::write(packs_dir.join("cabinets.json"), json).unwrap();

        let cabinets = get_cabinet_definitions_dynamic(dir.path());
        assert_eq!(cabinets.len(), 1);
        assert_eq!(cabinets[0].id, "only-one");
    }

    #[test]
    fn dynamic_commands_fallback_when_no_pack() {
        let dir = tempfile::TempDir::new().unwrap();
        // No pack → falls through to hardcoded get_commands_for_cabinet
        let cmds = get_commands_dynamic(dir.path(), "media-analyst");
        assert_eq!(cmds.len(), 9, "media-analyst hardcoded command count");
        assert!(cmds[0].command.starts_with('/'));
    }

    #[test]
    fn dynamic_commands_loaded_from_pack() {
        let dir = tempfile::TempDir::new().unwrap();
        let packs_dir = dir.path().join("content-packs");
        std::fs::create_dir_all(&packs_dir).unwrap();
        let json = r##"{
            "cabinets": [{
                "id": "test-cab",
                "name": "Test", "description": "", "icon": "X", "color": "#000000",
                "commands": [
                    {"command": "/alpha", "label": "Alpha", "group": "Main"},
                    {"command": "/beta",  "label": "Beta",  "group": "Tools"},
                    {"command": "/gamma", "label": "Gamma", "group": "Main"}
                ]
            }]
        }"##;
        std::fs::write(packs_dir.join("cabinets.json"), json).unwrap();

        let cmds = get_commands_dynamic(dir.path(), "test-cab");
        assert_eq!(cmds.len(), 3);
        assert_eq!(cmds[0].command, "/alpha");
        assert_eq!(cmds[1].group, "Tools");
    }

    #[test]
    fn dynamic_commands_unknown_cabinet_falls_back_to_empty() {
        let dir = tempfile::TempDir::new().unwrap();
        let packs_dir = dir.path().join("content-packs");
        std::fs::create_dir_all(&packs_dir).unwrap();
        let json = r##"{"cabinets":[{"id":"known","name":"K","description":"","icon":"K","color":"#000000","commands":[{"command":"/x","label":"X","group":"G"}]}]}"##;
        std::fs::write(packs_dir.join("cabinets.json"), json).unwrap();

        // Cabinet not in pack, not in hardcoded → empty
        let cmds = get_commands_dynamic(dir.path(), "unknown-cabinet-xyz");
        assert!(cmds.is_empty());
    }

    #[test]
    fn dynamic_commands_pack_cabinet_not_found_uses_hardcoded() {
        let dir = tempfile::TempDir::new().unwrap();
        let packs_dir = dir.path().join("content-packs");
        std::fs::create_dir_all(&packs_dir).unwrap();
        // Pack exists but doesn't contain "media-analyst" → falls back to hardcoded
        let json = r##"{"cabinets":[{"id":"other","name":"Other","description":"","icon":"O","color":"#000000","commands":[]}]}"##;
        std::fs::write(packs_dir.join("cabinets.json"), json).unwrap();

        let cmds = get_commands_dynamic(dir.path(), "media-analyst");
        assert_eq!(cmds.len(), 9);
    }

    // ── M1 edition gating: локальная (152-ФЗ) vs облачная редакция ────────────
    #[cfg(feature = "cloud_advisors")]
    #[test]
    fn cloud_edition_exposes_econometrist_advisor() {
        let visible = filter_by_product("econometrica", get_cabinet_definitions());
        let ids: Vec<&str> = visible.iter().map(|c| c.id.as_str()).collect();
        assert_eq!(ids, vec!["econometrist"], "Облачная редакция показывает кабинет-советник econometrist");
    }

    #[cfg(not(feature = "cloud_advisors"))]
    #[test]
    fn local_edition_hides_all_advisor_cabinets() {
        // Локальная редакция = только MMM-пайплайн, ноль cloud-кабинетов (нет точки входа к Claude).
        let visible = filter_by_product("econometrica", get_cabinet_definitions());
        assert!(visible.is_empty(), "Локальная редакция не должна показывать ни одного advisor-кабинета");
    }

    #[test]
    fn cloud_advisors_const_matches_build_feature() {
        // Egress-флаг claude.rs должен совпадать с feature-конфигурацией сборки.
        assert_eq!(
            crate::commands::claude::CLOUD_ADVISORS_ENABLED,
            cfg!(feature = "cloud_advisors")
        );
    }
}
// force rebuild
