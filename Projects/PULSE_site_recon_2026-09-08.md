# PULSE — разведка сайта mmm-optimizer.pro (2026-09-08)

## Задача (своими словами)
Нужна разведка (только чтение, ничего не публикуем и не меняем) для домена mmm-optimizer.pro
продукта Econometrica (MMM Optimizer). Владелец хочет заглушку к четвергу 10.09 (демо покупателю),
по образцу уже работающего сайта synthetic-research.pro. Нужно выяснить: как устроен образец
(сборка/выкладка/сторожа), что с самим доменом (резолвится ли, куда указывает), какие готовые
материалы про продукт можно использовать для текста заглушки, и что юридически обязательно
скопировать в подвал.

## План
1. Образец synthetic-research.pro — дерево, стек, скрипты выкладки, сторожа, NEXT_SESSION_PROMPT.
2. Состояние домена mmm-optimizer.pro — nslookup, curl -I, сравнение с synthetic-research.pro.
3. Grep упоминаний mmm-optimizer в деревьях Aurora_Ai.
4. Готовые материалы про продукт (ванпейджер, отличия, PORTFOLIO.md) — что годится в заглушку.
5. Юридический минимум в подвале synthetic-research.pro.
6. Собрать отчёт Projects\SITE_RECON_mmm_optimizer_2026-09-08.md.

## Ход работы
- 00:59 старт.
- 01:00 – образец synthetic-research.pro осмотрен: стек Astro 7 (pnpm-монорепо, НЕ под git), выкладка через deploy/deploy.sh (атомарный симлинк releases/<метка>), сторожа — 20 файлов vitest в packages/guards. DECISIONS_SITE_SR.md: строка 13 — «второй сайт стартует только после трёх измерений на первом» (заявки/цена заявки/поиск) — важное ограничение для варианта (б).
- 01:03 – домен: nslookup mmm-optimizer.pro резолвится (178.210.92.188, NS ещё nic.ru, НЕ Cloudflare), curl http → 404 openresty/Kong с телом-заглушкой nic.ru («Server Error 404», брендинг nic.ru) — это парковочная страница регистратора, не наш узел. HTTPS не отвечает (TLS handshake fails). Для сравнения synthetic-research.pro → 176.123.160.222, NS Cloudflare (мигрирован).
- 01:04 – грепнула упоминания mmm-optimizer в KB/aurora-meta/Dev — основная находка: готовый honest-copy контент уже есть в aurora-platform-web (content/products/optimizer.ru.mdx, status: shipped) и в Projects/onepagers/mmm-optimizer.md там же (устаревший, с internal notes в хвосте — уже отмечено в PULSE_site_claims_2026-08-16.md).
- 01:05 – прочитан свежий ванпейджер (docx, правлен 23:53 сегодня) и «Чем отличается MMM Optimizer.md» (v2.5.0, сентябрь 2026, факт-чек по коду) — оба на Desktop\Демо-показ Эконометрики\. Footer.astro synthetic-research осмотрен — юридический минимум: name/ИНН/ОГРН/город (site-config.ts legalEntity), без формы (canShowForm=false, приватность/согласие не опубликованы).
- 01:06 – пишу отчёт SITE_RECON_mmm_optimizer_2026-09-08.md.
- 01:12 - отчёт написан: Projects\SITE_RECON_mmm_optimizer_2026-09-08.md. Финиш.
