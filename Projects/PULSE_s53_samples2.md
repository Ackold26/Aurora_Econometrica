# PULSE s53 samples2 – образцы для покупателя движком 2.5.6 (свежий исполнитель)

## Задача (своими словами)
Пересобрать с нуля образцы HTML-отчёта и презентации PPTX Optimizer MMM установленным движком 2.5.6 (порт 8799) на демо-данных synth_fmcg, полным конвейером validate→…→backtest→export, в Projects/_demo_samples_s53/.
Прогнать 8 проверок (формат суммы, PNG из HTML, следы клиента, язык, честность чисел, состав против s51 с объяснением по git, доля канала, переполнение) и записать SAMPLES_s53.md. Код не менять, не коммитить.

## План
1. Прочитать SAMPLES_s49.md, скрипты s51
2. Создать _demo_samples_s53/_scripts (копии с новыми путями), _project/
3. Проверить exe 2.5.6, порт 8799 свободен, запустить движок, /health
4. Конвейер шаги 1–7 (обучение – долго)
5. Бэктест (долго) + экспорт HTML/PPTX
6. checks_s53.py – 8 проверок + контроли падения
7. Состав против s51 – git log
8. Остановить свой движок, порт свободен
9. SAMPLES_s53.md

## Журнал
19:32:17 – старт, маячок создан
19:34:20 – шаг 1 – прочитаны SAMPLES_s49.md и скрипты s51; скрипты скопированы в _demo_samples_s53/_scripts (run_full_s53.py, run_continue_s53.py), промежуточные JSON – в _json/
19:34:20 – шаг 2 – движок: %LOCALAPPDATA%\Optimizer MMM\_up_\sidecar\econometrica\econometrica-sidecar.exe, ProductVersion 2.5.6.0, SHA256 2BAFB51A…255EC0; порт 8799 был свободен, других процессов движка нет
19:34:20 – шаг 3 – движок запущен PID 36224 (окружение как у программы: AURORA_PRODUCT_ID, AURORA_PRODUCT_VERSION=2.5.6); /health ok, version 2.5.6 (оговорка: поле version – эхо переменной окружения, настоящее доказательство версии – ProductVersion exe)
19:34:20 – шаг 4 – АНОНС долгой фазы: полный конвейер validate→train (байес, ~1–3 мин)→…→backtest (~2–6 мин)→export; журнал _demo_samples_s53/run_full_s53.log
19:35:34 – шаг 4 – validate/confirm/train/decompose/optimize/scenario/planning прошли (время train – в run_full_s53.log); идёт backtest (~2–6 мин)
19:37:37 – шаг 5 – конвейер завершён EXIT_CODE=0: train 45,7 с, backtest 101,1 с (status ok, 5 окон, verdict coverage_low); HTML 1 154 727 б, PPTX 513 767 б, 16 слайдов (отчёт движка). Запускаю checks_s53.py
19:41:48 – шаг 6 – checks_s53.py: 8 из 8 PASS (checks.json); контроли падения сработали (1,3,4 – подсаженный текст; 8 – гейт на образце s51 даёт код 1)
19:42:20 – шаг 7 – движок PID 36224 снят через /shutdown (завершился сам), порт 8799 свободен, процессов econometrica-sidecar нет
19:43:17 – шаг 8 – написан Projects/SAMPLES_s53.md (8/8 PASS; 16 слайдов объяснено по build(); замечание: сырые даты «2024-12-30T00:00:00» в сроке плана)
EXIT: OK
