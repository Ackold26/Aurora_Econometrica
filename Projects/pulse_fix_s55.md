# Маячок fix_s55 (правки L-1n, L-3n аудита s55)
Задача: (A) детектор итоговой строки в planning.py должен ловить и хвостовую строку средних («Среднее/Average/Mean»), текст total_rows_message – верный для обоих случаев; зондом подтвердить, что сейчас такая строка уходит в обучение. (B) в builder.py подпись «безубыточность» рисовать только когда есть диаграмма mROAS.
План: зонд L-1n -> правка planning.py -> тесты -> правка builder.py -> тест -> прогон -> мутации -> скан 38 файлов -> отчёт FIX_s55_audit2.md.
СТАРТ 2026-09-28 10:50:44
10:54:35 – ЗОНД L-1n до правки (`%TEMP%\fix_s55\probe_l1n.py`, 20 недель + хвостовая строка средних, xlsx): детектор [] во всех вариантах, проверка данных warning без критических. OLS: чистый файл n_obs=20; «Среднее» в колонке comment при пустой дате – status=ok n_obs=21 (строка средних обучилась как период – ПОДТВЕРЖДЕНО); «Среднее» в колонке даты – OLS ok n_obs=21 (OLS разбирает даты мягко), байесовское обучение – сырое исключение DateParseError «Unknown datetime string format, unable to parse: Среднее» (ПОДТВЕРЖДЕНО). Колонка «Средний чек» + даты: 0 срабатываний.
10:56:07 – правки внесены: planning.py (_TOTAL_WORD_RE + средн/average/avg/mean, текст total_rows_message, docstring), builder.py (if bar_labels: вокруг подписи безубыточности); тесты +8 в test_total_row_s55.py, +2 проверки в test_pptx_nonpositive_mroas.py; прогон двух файлов 34 passed. Далее мутации.
10:56:35 – МУТАЦИЯ M1 L-1n: прежнее слово-признак без средн/average/avg/mean: engines\planning.py:94 (sha до 7f06d66355c2de5f)
   итог: or_dir] [...]
__main__.py: error: unrecognized arguments: -n --dist
  inifile: D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt\pytest.ini
  rootdir: D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt

 | красные: НЕТ
10:56:36 – МУТАЦИЯ ОТКАЧЕНА, sha совпал (7f06d66355c2de5f)
10:56:36 – МУТАЦИЯ M2 L-1n: прежний текст одной строки «похожа на итоговую»: engines\planning.py:226 (sha до 7f06d66355c2de5f)
   итог: or_dir] [...]
__main__.py: error: unrecognized arguments: -n --dist
  inifile: D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt\pytest.ini
  rootdir: D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt

 | красные: НЕТ
10:56:37 – МУТАЦИЯ ОТКАЧЕНА, sha совпал (7f06d66355c2de5f)
10:56:37 – МУТАЦИЯ M3 L-3n: подпись безубыточности без условия (if True): aurora_pptx\builder.py:2147 (sha до ca7d2c1c48bb5be0)
   итог: or_dir] [...]
__main__.py: error: unrecognized arguments: -n --dist
  inifile: D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt\pytest.ini
  rootdir: D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt

 | красные: НЕТ
10:56:38 – МУТАЦИЯ ОТКАЧЕНА, sha совпал (ca7d2c1c48bb5be0)
10:56:47 – прогон мутаций выше НЕДЕЙСТВИТЕЛЕН: pytest не запустился (мой ключ -p no:xdist конфликтует с -n в pytest.ini), откаты сверены. Повторяю без этого ключа.
10:57:40 – МУТАЦИЯ M1 L-1n: прежнее слово-признак без средн/average/avg/mean: engines/planning.py:94 (sha до 7f06d66355c2de5f)
   итог: 6 failed, 28 passed in 11.38s | красные: test_average_row_in_date_column_is_critical_not_raw_crash, test_average_words_detected[Average], test_average_words_detected[Mean], test_average_row_with_label_in_other_column_refused_by_training, test_average_words_detected[AVG], test_average_words_detected[\u0421\u0440\u0435\u0434\u043d\u0438\u0435 \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u044f]
10:57:52 – МУТАЦИЯ ОТКАЧЕНА, sha совпал (7f06d66355c2de5f)
10:57:52 – МУТАЦИЯ M2 L-1n: прежний текст одной строки «похожа на итоговую»: engines/planning.py:226 (sha до 7f06d66355c2de5f)
   итог: 1 failed, 33 passed in 11.12s | красные: test_average_row_with_label_in_other_column_refused_by_training
10:58:05 – МУТАЦИЯ ОТКАЧЕНА, sha совпал (7f06d66355c2de5f)
10:58:05 – МУТАЦИЯ M3 L-3n: подпись безубыточности без условия (if True): aurora_pptx/builder.py:2147 (sha до ca7d2c1c48bb5be0)
   итог: 1 failed, 33 passed in 11.70s | красные: test_all_channels_nonpositive_mroas_builds_with_note
10:58:18 – МУТАЦИЯ ОТКАЧЕНА, sha совпал (ca7d2c1c48bb5be0)
10:58:30 – мутации M1–M3 пойманы (6 / 1 / 1 красных), все откаты сверены по sha. Далее ДЛИННАЯ ТИХАЯ ФАЗА: прогон задетых наборов движка (63 файлов, ~1–2 мин) и скан реальных файлов.
11:01:13 – прогон задетых наборов движка (63 файла): 986 passed, 2 skipped, 0 failed; скан 38 реальных файлов: 0 срабатываний; стресс 30 файлов: 0 ложных на примечании «среднее…», «Среднее» поймано 30/30. Отчёт Projects/FIX_s55_audit2.md.
ГОТОВО 2026-09-28 11:01:13
