# Маячок: внешний аудит cd6112e0 (L-1n / L-3n)
Предмет: расширение _TOTAL_WORD_RE словами средн*/average/avg/mean + новый текст total_rows_message (planning.py); подпись безубыточности только при bar_labels (builder.py); два набора тестов.
План: 1) дифф+отчёт FIX_s55_audit2 2) grep вызовов _TOTAL_WORD_RE/_row_is_total/find_trailing_total_rows 3) grep старого текста в src/ src-tauri/ tests 4) builder.py область видимости 5) зонды ложных срабатываний (mean в хвосте) 6) pytest.
СТАРТ 2026-09-28 11:19:06
- 11:20 шаг1-2: дифф+отчёт прочитаны; вызовы детектора: validator.py:550 (date_col=None!), modeler.py:356, ols_modeler.py:93; старый текст нигде больше не сверяется
- 11:22 шаг3-4: старый текст нигде не сверяется (src/, src-tauri, тесты – чисто); builder: breakeven_note используется только внутри if
- 11:20:57 шаг5: зонды ложных срабатываний – 9 случаев, новых классов нет (Mean/Средне-Волжский в хвосте без даты = известный Low; сноска с числом = L-2n); склейки MeanTime/avg_price/meaning/averages – нет срабатывания
- 11:21:30 шаг6: pytest 38 passed; находки записаны в Projects/audit_cd611.txt
ГОТОВО 2026-09-28 11:21:30
