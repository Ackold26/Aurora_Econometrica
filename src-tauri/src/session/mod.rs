pub mod cleanup;
pub mod history;
pub mod manager;

/// testleak-фикс (2026-07-29): тест-инвариант "SessionManager и cleanup_stale_sessions()
/// резолвят один и тот же каталог" раньше жил в `manager.rs` и вызывал НАСТОЯЩИЙ
/// `SessionManager::new()` — тот резолвит `durable_store::app_state_dir("sessions")`, который в
/// тестовом окружении (`durable_store::init()` тестами не вызывается) уходит в фолбэк по
/// `CARGO_PKG_NAME` — РЕАЛЬНЫЙ каталог профиля разработчика (`%LOCALAPPDATA%\<cargo-pkg-name>\`),
/// а не временный. `create_dir_all` внутри `app_state_dir` создавал там настоящие директории —
/// побочный эффект в живом профиле (найдено при приёмке CPD-30). Хуже: `BASE_DIR` — состояние
/// всего процесса (`OnceLock`); если КОГДА-НИБУДЬ другой тест того же бинарника вызовет
/// `durable_store::init()`, это зафиксирует другую базу для ВСЕХ тестов процесса — тест начал
/// бы проверять другой каталог в зависимости от порядка запуска (мина замедленного действия).
///
/// Здесь — чистая проверка БЕЗ единого обращения к диску профиля: `session/manager.rs` и
/// `session/cleanup.rs` обязаны ссылаться на ОДИН и тот же контракт — константу
/// `durable_store::SESSIONS_SUB`, а не на независимые строковые литералы, которые могли бы
/// незаметно разойтись. Использование общей константы в обоих местах уже даёт равенство
/// резолвнутого пути НА УРОВНЕ КОМПИЛЯТОРА (одна и та же строка не может разойтись сама с
/// собой) — тест ниже ловит регресс, если кто-то вернёт один из двух вызовов на хардкод.
/// Тест размещён здесь, а не в manager.rs/cleanup.rs: чтение файла ИЗНУТРИ него же превратило
/// бы проверку в тавтологию — искомая строка сама попала бы в прочитанный текст.
#[cfg(test)]
mod tests {
    use std::path::Path;

    /// Строки-комментарии отбрасываются перед проверкой.
    ///
    /// Дыра, найденная мутацией приёмщика 2026-07-29: проверка искала подстроку во
    /// ВСЁМ тексте файла, а в manager.rs `durable_store::SESSIONS_SUB` упоминается ещё
    /// и в комментарии. Замена рабочего вызова на собственный литерал `"sessions"`
    /// оставляла сторож ЗЕЛЁНЫМ — он удовлетворялся упоминанием в комментарии, то есть
    /// смотрел не туда. Тот же класс, что сторож проверяет, только уровнем выше.
    fn code_only(src: &str) -> String {
        src.lines()
            .map(str::trim_start)
            .filter(|line| {
                !line.starts_with("//") && !line.starts_with("*") && !line.starts_with("/*")
            })
            .collect::<Vec<_>>()
            .join("\n")
    }

    fn read_src(filename: &str) -> String {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("src")
            .join("session")
            .join(filename);
        std::fs::read_to_string(&path)
            .unwrap_or_else(|e| panic!("не удалось прочитать {:?}: {e}", path))
    }

    #[test]
    fn manager_and_cleanup_reference_the_same_sessions_constant() {
        let manager_src = code_only(&read_src("manager.rs"));
        let cleanup_src = code_only(&read_src("cleanup.rs"));

        assert!(
            manager_src.contains("durable_store::SESSIONS_SUB"),
            "session/manager.rs обязан резолвить каталог сессий через \
             crate::durable_store::SESSIONS_SUB, а не через независимый строковый литерал — \
             иначе он может незаметно разойтись с cleanup.rs"
        );
        assert!(
            cleanup_src.contains("durable_store::SESSIONS_SUB"),
            "session/cleanup.rs обязан резолвить каталог сессий через \
             crate::durable_store::SESSIONS_SUB, а не через независимый строковый литерал — \
             иначе очистка на старте не найдёт то, что создал SessionManager"
        );

        // Вторая половина: мало сослаться на константу где-то в файле — каталог не
        // должен ПАРАЛЛЕЛЬНО собираться собственным литералом. Иначе обе проверки
        // выше остаются зелёными, пока рабочий вызов тихо ушёл на свой путь.
        for (name, src) in [("manager.rs", &manager_src), ("cleanup.rs", &cleanup_src)] {
            assert!(
                !src.contains("app_state_dir(\"sessions\")"),
                "session/{name} собирает каталог сессий литералом app_state_dir(\"sessions\") \
                 вместо общей константы SESSIONS_SUB — так manager и cleanup расходятся молча"
            );
        }
    }
}
