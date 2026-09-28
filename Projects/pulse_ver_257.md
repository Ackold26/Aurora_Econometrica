# Маячок: поднятие версии 2.5.6 → 2.5.7 + справка-PDF

Задача: поднять номер версии программы Econometrica с 2.5.6 до 2.5.7 по образцу коммита bca44e2f (package.json, Cargo.lock, src-tauri/Cargo.toml, src-tauri/tauri.conf.json, sidecar/econometrica/version_info.txt), проверить остальные вхождения 2.5.6 в дереве (grep), разобраться со справкой-PDF (пересобирать или нет), прогнать проверки консистентности. Параллельно работает fix-s55 (движок planning.py/validator.py/builder.py + тесты) – эти файлы не трогаю, тесты движка не гоняю.

План:
1. Изучить образец bca44e2f
2. Поднять версию в 5 файлах на 2.5.7
3. git grep "2.5.6" по дереву, разделить на «версия программы» и «история/тексты»
4. Разобраться со справкой-PDF (смотреть историю, решить пересобирать или нет)
5. Прогнать check_help_pdf_consistency.py / check_help_consistency.py / check_content_pack_sync.py
6. Отчёт в Projects/VER_s55_257.md

СТАРТ 2026-09-28 10:50:57
2026-09-28 10:56:00 – шаг 1-2 готовы: package.json, src-tauri/Cargo.toml, src-tauri/tauri.conf.json, Cargo.lock (строка 340, точечно), version_info.txt (все 4 места) подняты 2.5.6→2.5.7. Кодировка/переводы строк сверены до и после (без изменений). Diff чистый, только целевые строки.
2026-09-28 11:05:00 – шаг 3 готов: git grep "2\.5\.6" по дереву (кроме Projects/) – одно вхождение, чужой пакет tauri-build в Cargo.lock, не трогала.
2026-09-28 11:12:00 – шаг 4 готов: справка-PDF НЕ пересобирала (доказательства – прошлый релиз 2.5.6 её не трогал, content-packs/help у Econometrica не существует, PDF-линтер сверяет хеш HTML а не номер версии программы, HTML не менялись). Три проверки (check_help_pdf_consistency.py, check_help_consistency.py, check_content_pack_sync.py) – все exit 0.
2026-09-28 11:13:00 – отчёт Projects/VER_s55_257.md написан.
ГОТОВО 2026-09-28 11:13:00
