pub mod brand;
pub mod cabinet;
pub mod campaign;
pub mod content_pack;
pub mod claude;
pub mod diagnostics;
pub mod data_migration;
pub mod content_updater;
pub mod econometrica;
/// Выбор режима исполнения советника во время работы (ADR-049): свой Claude Code
/// клиента или шлюз Авроры. Собирается ВСЕГДА — в сборке без облачного пути модуль
/// честно отвечает, что облачного режима нет, вместо того чтобы исчезнуть и заставить
/// вызывающий код снова ветвиться условной компиляцией.
pub mod execution_mode;
pub mod feedback;
#[cfg(feature = "thin")]
pub mod gateway_executor;
pub mod license;
pub mod mqs_tiers;
pub mod online_auth;
pub mod parser;
pub mod pptx_processor;
pub mod project;
pub mod rag_client;
pub mod report;
pub mod updater;
pub mod user_config;
pub mod vault;
