"""Воспроизводимый рецепт обучения модели для приёмки полей паспорта воспроизводимости.

Назначение: снять снимок «до»/«после» правки engines/modeler.py (добавление
`data_fingerprint` в `reproducibility` и `adstock_selection` верхнего уровня),
обучая ОДНУ и ТУ ЖЕ модель на ОДНИХ И ТЕХ ЖЕ данных с фиксированным зерном,
но подключая движок из разных деревьев (--engine-root) — «до» из изолированной
копии на 72f13fa, «после» из основного дерева после правки.

🔴 Ничего не пишет в клиентские проекты. Входные данные копируются во
временный каталог; project_dir для train_model() — тоже временный каталог
(models/results там же, не в %APPDATA%).

Пример запуска (снимок «до», движок из изолированной копии):
    python Projects/repro_train_probe.py ^
        --engine-root D:/Docs/Aurora_Ai/Dev/_wt_repro_corpus/sidecar/econometrica ^
        --seed 42

Пример запуска (снимок «после» правки, движок из основного дерева):
    python Projects/repro_train_probe.py ^
        --engine-root D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica_thinwt/sidecar/econometrica ^
        --seed 42

По умолчанию источник данных — исходный xlsx проекта
«кагоцел-рф--данные-для-эконометрики---на-ммх-2306-26» (31 наблюдение,
5 каналов, из них 4 включены в project.json). У самого проекта в
%APPDATA%\\aurora-econometrica-gui\\projects\\<...>\\project.json поле
data_file уже null (путь к исходнику живёт только внутри старого
models/latest.pkl → config['data_file']) — путь ниже восстановлен оттуда.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_SOURCE_XLSX = (
    r"C:\Users\ackol\Desktop\Файлы для тестирования Авроры"
    r"\Эконометрика - тестовые файлы"
    r"\Кагоцел РФ+_данные для эконометрики + наши данные 29.08.xlsx"
)

# Конфигурация обучения — взята из project.json проекта
# "кагоцел-рф--данные-для-эконометрики---на-ммх-2306-26" (media_columns/
# control_columns/kpi_column как в файле; date_column и adstock_config там
# не заданы явно — date_column='Date' подтверждён по колонкам исходного
# xlsx, adstock_config='auto' на канал — так же, как в последнем реальном
# обучении этого проекта, зафиксированном в models/latest.pkl).
PROJECT_JSON_CONFIG = {
    "kpi_column": "Продажи в руб. бренд",
    "media_columns": [
        "OLV Бюджет до НДС до АК",
        "Banners Бюджет \nДО НДС до АК",
        "Social Бюджет \nДО НДС до АК",
        "Performance Бюджет \nДо НДС до АК",
    ],
    "control_columns": [
        "Кол-во запросов",
        "Продажи в уп. конкуренты",
    ],
    "date_column": "Date",
    "kpi_type": "sales",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine-root", required=True,
                     help="Путь к sidecar/econometrica движка, который обучает (изолированная копия ИЛИ основное дерево).")
    ap.add_argument("--source-xlsx", default=DEFAULT_SOURCE_XLSX,
                     help="Путь к исходному xlsx с данными проекта (по умолчанию — кагоцел, 31 набл.).")
    ap.add_argument("--seed", type=int, default=42, help="Фиксированное зерно MCMC.")
    ap.add_argument("--work-dir", default=None,
                     help="Временный каталог для копии данных и project_dir. По умолчанию — новый tempfile.mkdtemp().")
    ap.add_argument("--chains", type=int, default=None, help="Override числа цепей (по умолчанию — движок сам решит по наличию компилятора).")
    ap.add_argument("--draws", type=int, default=None, help="Override числа draws.")
    ap.add_argument("--tune", type=int, default=None, help="Override tune.")
    ap.add_argument("--keep-work-dir", action="store_true",
                     help="Не выводить путь на удаление в конце (каталог и так не удаляется автоматически).")
    args = ap.parse_args()

    engine_root = Path(args.engine_root).resolve()
    if not (engine_root / "engines" / "modeler.py").exists():
        print(f"ОШИБКА: не найден engines/modeler.py в {engine_root}", file=sys.stderr)
        return 2

    source_xlsx = Path(args.source_xlsx)
    if not source_xlsx.exists():
        print(f"ОШИБКА: исходный файл данных не найден: {source_xlsx}", file=sys.stderr)
        return 2

    work_dir = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="econ_repro_"))
    data_dir = work_dir / "data"
    project_dir = work_dir / "project"
    data_dir.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)

    # Копия данных во временный каталог — ничего не пишем в клиентский проект
    # и не читаем данные напрямую из %APPDATA%\...\projects\ на каждый прогон.
    data_copy = data_dir / source_xlsx.name
    shutil.copy2(source_xlsx, data_copy)

    config = dict(PROJECT_JSON_CONFIG)
    config["data_file"] = str(data_copy)
    config["adstock_config"] = {ch: "auto" for ch in config["media_columns"]}
    config["seed"] = args.seed

    mcmc_override = {}
    if args.chains is not None:
        mcmc_override["chains"] = args.chains
    if args.draws is not None:
        mcmc_override["draws"] = args.draws
    if args.tune is not None:
        mcmc_override["tune"] = args.tune
    config["mcmc_override"] = mcmc_override or None

    print(f"[repro_train_probe] engine_root = {engine_root}")
    print(f"[repro_train_probe] source_xlsx = {source_xlsx}")
    print(f"[repro_train_probe] work_dir    = {work_dir}")
    print(f"[repro_train_probe] seed        = {args.seed}")
    print(f"[repro_train_probe] mcmc_override = {config['mcmc_override']}")
    print(f"[repro_train_probe] config = {json.dumps(config, ensure_ascii=False, indent=2)}")

    sys.path.insert(0, str(engine_root))
    # Свежий импорт при повторном запуске в одном процессе исключаем — каждый
    # запуск скрипта = отдельный процесс python, так что кэш модулей не мешает.
    from engines.modeler import train_model  # noqa: E402

    t0 = time.monotonic()
    result = train_model(config, str(project_dir))
    elapsed = time.monotonic() - t0

    status = result.get("status") if isinstance(result, dict) else None
    print(f"[repro_train_probe] status = {status}")
    print(f"[repro_train_probe] время обучения = {elapsed:.1f} с ({elapsed / 60:.2f} мин)")

    model_path = project_dir / "models" / "latest.pkl"
    aurora_model_path = project_dir / "models" / "latest.aurora-model"
    saved_path = aurora_model_path if aurora_model_path.exists() else model_path
    print(f"[repro_train_probe] путь сохранённой модели = {saved_path} (существует: {saved_path.exists()})")
    print(f"[repro_train_probe] project_dir = {project_dir}")

    if status == "error":
        print(f"[repro_train_probe] ОШИБКА обучения: {result}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
