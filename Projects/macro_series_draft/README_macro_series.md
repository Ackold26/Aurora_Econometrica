# Макропоказатели — черновая выгрузка (заготовка, НЕ поставка)

Окно: 2016-09-13 — 2026-09-13 (10 лет).
Сгенерировано: 2026-09-13 16:53.

🔴 Это черновик на проверку (Projects/macro_series_draft/), не файл поставки.
Укладка в content-packs/ и пере-подпись пакета — следующая ступень.

## Статус источников

### Курс доллара США (ЦБ РФ) (`курс_доллара`, руб. за 1 USD)
- Статус: **ОШИБКА**, нет данных
- Ошибка: GET https://www.cbr.ru/scripts/XML_dynamic.asp?date_req1=13/09/2016&date_req2=13/09/2026&VAL_NM_RQ=R01235 не удался: URLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)'))

### Курс евро (ЦБ РФ) (`курс_евро`, руб. за 1 EUR)
- Статус: **ОШИБКА**, нет данных
- Ошибка: GET https://www.cbr.ru/scripts/XML_dynamic.asp?date_req1=13/09/2016&date_req2=13/09/2026&VAL_NM_RQ=R01239 не удался: URLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)'))

### Курс юаня (ЦБ РФ) (`курс_юаня`, руб. за 1 CNY)
- Статус: **ОШИБКА**, нет данных
- Ошибка: GET https://www.cbr.ru/scripts/XML_dynamic.asp?date_req1=13/09/2016&date_req2=13/09/2026&VAL_NM_RQ=R01375 не удался: URLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)'))

### Ключевая ставка (ЦБ РФ) (`ключевая_ставка`, % годовых)
- Статус: **ОШИБКА**, нет данных
- Ошибка: POST https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx не удался: URLError(TimeoutError('_ssl.c:993: The handshake operation timed out'))

### Индекс потребительских цен (Росстат) (`индекс_потребительских_цен`, индекс, база=100 на начало окна)
- Статус: **OK**, актуально на 2026-08-01
