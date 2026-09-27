# PULSE — чистка текста справки (s47)

Задача: привести в порядок ТЕКСТ встроенной справки Econometrica (24 файла в src-tauri/help-econometrica/) перед передачей покупателю. Две части:
1) версионные пометки — снять враньё о возрасте продукта («Что нового в v1.0.16» и т.п.), оставить где реально нужно;
2) англицизмы в клиентском тексте (Visual Pipeline, Action Labels и др.) — перевести, аккуратно с якорями/ссылками/id.
После — прогнать оба сторожа + пересобрать PDF + доказать свежесть по содержимому (PyMuPDF).
Верстку (шрифты/заголовки), которую поправил тимлид, не трогаю.

[старт] 2026-09-14 — начинаю: обзор всех 24 файлов на упоминания версий и англицизмы.

[+35 мин] Задача 1 (версии) и задача 2 (англицизмы) прогнаны по econometrica.html, pipeline.html, user-guide.html, about.html, methodology.html, faq.html, features.html, whats-new.html, index.html, econ-nav.js. check_help_consistency.py = OK, sync_help_lists.py --check = OK (авто-блок Trust Level 3 не задет). check_help_pdf_consistency.py: 0 FAIL по версиям/копирайту/ссылкам, есть 10 WARN "PDF устарел" (ожидаемо, пересоберу PDF последним шагом). Дальше — добить оставшиеся файлы (glossary, interpretation, data-preparation, step-*, install, system-requirements, error-codes, kpi-passports) и пересобрать PDF.

[+55 мин] Добила остаточные англицизмы (long-term, response curve, marketing/control variables, whitelisting, pipeline как голое слово) по всем 24 файлам. Полный повторный skan mixed-language не выявил новых существенных находок (остались только принятые термины: Ratio, MCMC, R-hat, ROAS/ROI, Aurora, Excel/Windows/Python, adstock, Bayesian, priors, WCAG, ECharts и т.п. — они логичны и не должны переводиться, согласно правилу задачи).
Дальше: тихая фаза 3-5 минут — пересборка PDF через headless Edge (tools/build_help_pdf.py), затем оба сторожа + проверка свежести PDF по содержимому.

[завершено] PDF пересобран, оба сторожа зелёные (0 FAIL), свежесть подтверждена по содержимому через PyMuPDF (новые формулировки найдены в тексте PDF, старые "Visual Pipeline"/"v1.0.16"/"Trust Levels"/"Что нового в 2.4" — отсутствуют). Обнаружила и зафиксировала для отчёта: econometrica.html/methodology.html/pipeline.html/data-preparation.html/interpretation.html — это UNLINKED_PAGES (донор-файлы после реструктуризации 2026-09-13, вне навигации и вне PDF), но я всё равно почистила и их текст, раз они остались на диске. Задача закрыта, пишу итоговый отчёт.

[01:01] Статус: задача полностью завершена (см. запись [завершено] выше) — итоговый отчёт с таблицей правок, выводом сторожей и доказательством свежести PDF уже отправлен team-lead сообщением. Не жду ничего, не застряла — просто не поставила финальную отметку вовремя, извини. Готова к новой задаче или правкам по замечаниям.
