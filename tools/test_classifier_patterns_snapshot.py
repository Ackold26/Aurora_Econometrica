"""Сторож снимка шаблонов колонок: движок == снимок, который читает фронтенд-сторож.

Зачем (К3-1, s62). Фронтенд классифицирует колонки шаблонами, полученными от
движка (`export_patterns_as_json`). Если движок не ответил при входе в конвейер,
окно работает на запасном наборе `EMBEDDED_FALLBACK`
(src/lib/services/classifier-patterns.js). Запасной набор беднее движка → имена,
которых он не знает (`TV (GRP)`, `OLV.views`, «охват»), остаются «денежными» и
физическая метрика обучается как рубли (ROI раздувается в тысячи раз).

Защита двухзвенная, потому что vitest не может вызвать Python:
  1. ЭТОТ тест: снимок src/lib/services/__tests__/fixtures/
     engine-classifier-patterns.snapshot.json == то, что отдаёт движок сейчас.
     Добавили шаблон в движок, снимок не обновили → красный.
  2. Vitest classifier-patterns-fallback-parity.test.js: каждый шаблон снимка
     есть в EMBEDDED_FALLBACK. Обновили снимок, запасной набор не пополнили → красный.

Обновить снимок (после правки шаблонов движка):
    cd sidecar/econometrica && python -c "import json; \
from utils.column_detection import export_patterns_as_json as e; \
print(json.dumps(e(), ensure_ascii=False, indent=1))" \
> ../../src/lib/services/__tests__/fixtures/engine-classifier-patterns.snapshot.json
затем пополнить EMBEDDED_FALLBACK тем же шаблоном.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = (
    ROOT / 'src' / 'lib' / 'services' / '__tests__' / 'fixtures'
    / 'engine-classifier-patterns.snapshot.json'
)


def test_snapshot_equals_engine_export():
    from utils.column_detection import export_patterns_as_json

    snapshot = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    engine = export_patterns_as_json()
    # Сравниваем через JSON-круг: типы (list/dict) и порядок значимы одинаково.
    engine = json.loads(json.dumps(engine, ensure_ascii=False))
    for kind in sorted(set(engine['kinds']) | set(snapshot['kinds'])):
        assert snapshot['kinds'].get(kind) == engine['kinds'].get(kind), (
            f"категория '{kind}': снимок устарел относительно движка. "
            "Обновите снимок и пополните EMBEDDED_FALLBACK "
            "(команда – в docstring этого файла)."
        )
    assert snapshot['unit_label_rules'] == engine['unit_label_rules'], (
        'unit_label_rules: снимок устарел относительно движка'
    )
    assert snapshot == engine, 'снимок расходится с экспортом движка'
