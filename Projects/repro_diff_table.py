"""Таблица расхождений между прогонами – по каналам и по величинам.

Читает снимки, сделанные `repro_extract_metrics.py`, и печатает расхождение
каждой пары в процентах (для окупаемости, коэффициента, переноса и насыщения)
и в процентных пунктах (для доли канала во вкладе). Дополнительно показывает,
какую долю ширины правдоподобного диапазона окупаемости составляет расхождение.

Пример:
    python Projects/repro_diff_table.py --dir <каталог снимков> --pairs A1:A2 A1:B A1:C
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ВЕЛИЧИНЫ = [
    ("roi", "окупаемость", "%"),
    ("contribution_pct", "доля вклада", "п.п."),
    ("beta", "коэффициент", "%"),
    ("decay", "перенос", "%"),
    ("alpha", "форма насыщения", "%"),
    ("gamma", "точка насыщения", "%"),
]


def расхождение(a, b, единица: str):
    if a is None or b is None:
        return None
    if единица == "п.п.":
        return abs(float(a) - float(b))
    if float(a) == 0:
        return None
    return abs(float(a) - float(b)) / abs(float(a)) * 100.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--pairs", nargs="+", required=True, help="Пары вида A1:C")
    args = ap.parse_args()

    корень = Path(args.dir)
    снимки = {}
    for файл in корень.glob("*.json"):
        снимки[файл.stem] = json.loads(файл.read_text(encoding="utf-8"))

    for пара in args.pairs:
        левый, правый = пара.split(":")
        a, b = снимки[левый], снимки[правый]
        print(f"\n### {левый} против {правый}  (зерно {a['seed']} и {b['seed']})")
        шапка = ["канал"] + [имя for _, имя, _ in ВЕЛИЧИНЫ] + ["доля диапазона"]
        print("| " + " | ".join(шапка) + " |")
        print("|" + "---|" * len(шапка))
        for канал, va in a["channels"].items():
            vb = b["channels"].get(канал)
            if not vb:
                continue
            ячейки = [канал.replace("\n", " ").strip()]
            for ключ, _, единица in ВЕЛИЧИНЫ:
                d = расхождение(va.get(ключ), vb.get(ключ), единица)
                ячейки.append("н/д" if d is None else (f"{d:.2f} %" if единица == "%" else f"{d:.1f} п.п."))
            низ, верх = va.get("roi_ci_low"), va.get("roi_ci_high")
            if низ is not None and верх is not None and верх > низ:
                доля = abs(float(va["roi"]) - float(vb["roi"])) / (float(верх) - float(низ)) * 100
                ячейки.append(f"{доля:.1f} %")
            else:
                ячейки.append("н/д")
            print("| " + " | ".join(ячейки) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
