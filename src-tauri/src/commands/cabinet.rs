use serde::{Deserialize, Serialize};

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
            name: "Юрист — Контракты".to_string(),
            description: "Проверка договоров, шаблоны, анализ\u{00a0}контрагентов".to_string(),
            icon: "📋".to_string(),
            color: "#10B981".to_string(), // green
        },
        CabinetInfo {
            id: "lawyer-claims".to_string(),
            name: "Юрист — NDA и претензии".to_string(),
            description: "NDA, претензионная работа, досудебные и судебные споры".to_string(),
            icon: "⚖️".to_string(),
            color: "#F59E0B".to_string(), // amber
        },
        CabinetInfo {
            id: "lawyer-advertising".to_string(),
            name: "Юрист — Реклама".to_string(),
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
        // ── Econometrica cabinets ──
        CabinetInfo {
            id: "data-model".to_string(),
            name: "Данные и Модель".to_string(),
            description: "Загрузка данных, валидация, обучение MMM-модели".to_string(),
            icon: "📊".to_string(),
            color: "#0EA5E9".to_string(), // sky-blue
        },
        CabinetInfo {
            id: "analysis".to_string(),
            name: "Анализ".to_string(),
            description: "Декомпозиция продаж, ROI, оптимизация бюджета, сценарии".to_string(),
            icon: "📐".to_string(),
            color: "#6366F1".to_string(), // indigo
        },
        CabinetInfo {
            id: "reporting".to_string(),
            name: "Отчёты".to_string(),
            description: "Awareness, Executive Summary, отчёт для\u{00a0}руководства".to_string(),
            icon: "📋".to_string(),
            color: "#8B5CF6".to_string(), // purple
        },
    ]
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
            ("/analytics", "Комментарии к слайдам", "Основные"),
            ("/check", "Проверить качество", "Основные"),
            ("/action-title", "Action Title", "Основные"),
            ("/executive-summary", "Executive Summary", "Основные"),
            ("/bridges", "Мосты между блоками", "Основные"),
            ("/batch-analytics", "Пакетная обработка", "Инструменты"),
            ("/data-analysis", "Анализ данных", "Инструменты"),
            ("/benchmark", "Бенчмарки", "Инструменты"),
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
        "econometrist" => vec![
            ("/mmm-full", "Полный цикл MMM", "Основные"),
            ("/mmm-prepare", "Подготовка данных", "Основные"),
            ("/mmm-model", "Обучить модель", "Основные"),
            ("/mmm-decomposition", "Декомпозиция", "Анализ"),
            ("/mmm-optimize", "Оптимизация бюджета", "Анализ"),
            ("/mmm-scenarios", "Сценарии what-if", "Анализ"),
            ("/awareness-forecast", "Прогноз awareness", "Awareness"),
            ("/awareness-to-sales", "Awareness → Продажи", "Awareness"),
            ("/mmm-report", "Полный отчёт", "Отчёты"),
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
        // ── Econometrica cabinets ──
        "data-model" => vec![
            ("/validate", "Валидация данных", "Данные"),
            ("/configure", "Конфигурация модели", "Данные"),
            ("/train", "Обучить модель", "Модель"),
            ("/diagnose", "Диагностика модели", "Модель"),
        ],
        "analysis" => vec![
            ("/decompose", "Декомпозиция продаж", "Анализ"),
            ("/optimize", "Оптимизация бюджета", "Оптимизация"),
            ("/scenario", "Сценарий", "Сценарии"),
            ("/compare", "Сравнить сценарии", "Сценарии"),
        ],
        "reporting" => vec![
            ("/awareness", "Прогноз awareness", "Awareness"),
            ("/funnel", "Воронка media→sales", "Awareness"),
            ("/executive", "Executive Summary", "Отчёт"),
            ("/mmm-export", "Полный отчёт", "Отчёт"),
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

/// Validate that a cabinet_id is one of the known cabinet definitions.
pub fn validate_cabinet_id(cabinet_id: &str) -> Result<&str, String> {
    let valid_ids: [&str; 16] = [
        "social-listening", "media-analyst", "communication-analyst",
        "communication-strategist", "focus-groups", "creative-director",
        "lawyer-contracts", "lawyer-claims", "lawyer-advertising",
        "doc-master", "econometrist",
        "copywriter", "art-director",
        // Econometrica
        "data-model", "analysis", "reporting",
    ];
    if valid_ids.contains(&cabinet_id) {
        Ok(cabinet_id)
    } else {
        Err(format!("Invalid cabinet ID: {}", cabinet_id))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_cabinets_defined() {
        let cabinets = get_cabinet_definitions();
        assert_eq!(cabinets.len(), 16); // 13 original + 3 econometrica
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
            // Econometrica
            "data-model",
            "analysis",
            "reporting",
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
        assert_eq!(get_commands_for_cabinet("media-analyst").len(), 8);
        assert_eq!(get_commands_for_cabinet("communication-analyst").len(), 10);
        assert_eq!(get_commands_for_cabinet("communication-strategist").len(), 8);
        assert_eq!(get_commands_for_cabinet("creative-director").len(), 9);
        assert_eq!(get_commands_for_cabinet("focus-groups").len(), 7);
        assert_eq!(get_commands_for_cabinet("social-listening").len(), 9);
        assert_eq!(get_commands_for_cabinet("lawyer-contracts").len(), 15);
        assert_eq!(get_commands_for_cabinet("lawyer-claims").len(), 10);
        assert_eq!(get_commands_for_cabinet("lawyer-advertising").len(), 14);
        assert_eq!(get_commands_for_cabinet("doc-master").len(), 3);
        assert_eq!(get_commands_for_cabinet("econometrist").len(), 9);
        assert_eq!(get_commands_for_cabinet("copywriter").len(), 7);
        assert_eq!(get_commands_for_cabinet("art-director").len(), 9);
        // Econometrica
        assert_eq!(get_commands_for_cabinet("data-model").len(), 4);
        assert_eq!(get_commands_for_cabinet("analysis").len(), 4);
        assert_eq!(get_commands_for_cabinet("reporting").len(), 4);
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
    fn validate_cabinet_id_rejects_unknown() {
        assert!(validate_cabinet_id("nonexistent").is_err());
        assert!(validate_cabinet_id("../etc/passwd").is_err());
        assert!(validate_cabinet_id("").is_err());
    }
}
