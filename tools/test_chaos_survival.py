"""C2 (2026-07-03): выживаемость — межпроцессная блокировка проекта.

Зонд tmp/probe_c2_chaos.py доказал боем: (1) file_lock держит МЕЖДУ
процессами (сценарий «два окна приложения»): второй процесс получает
LockTimeout с русским сообщением, после освобождения захват мгновенный;
(2) OneDrive: полный save/load pickle + validate + decompose в реальной
OneDrive-папке — ok. Этот тест закрепляет (1) в прогоне.

Код-verify (без теста): атомарная запись модели (mkstemp + os.replace,
tmp-очистка при ошибке) — «диск полон»/крах записи не бьёт latest.pkl;
краш сайдкара посреди MCMC → рестарт с пустым реестром задач → /progress
отвечает idle (durable-модель цела).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils.file_lock import project_lock, LockTimeout  # noqa: E402

_HOLDER = '''
import sys, time
from pathlib import Path
ROOT = Path(sys.argv[1])
for p in (str(ROOT / "sidecar"), str(ROOT / "sidecar" / "econometrica")):
    sys.path.insert(0, p)
from utils.file_lock import project_lock
with project_lock(Path(sys.argv[2]), timeout=5.0):
    print("ACQUIRED", flush=True)
    time.sleep(2.0)
'''


def test_project_lock_interprocess(tmp_path):
    """Два ПРОЦЕССА (два окна приложения): пока первый держит блокировку,
    второй получает LockTimeout с понятным русским сообщением; после
    освобождения захват проходит сразу."""
    holder_py = tmp_path / '_holder.py'
    holder_py.write_text(_HOLDER, encoding='utf-8')
    p = subprocess.Popen(
        [sys.executable, str(holder_py), str(ROOT), str(tmp_path)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        line = p.stdout.readline()
        assert 'ACQUIRED' in line, f'держатель не захватил lock: {line!r}'

        t0 = time.perf_counter()
        with pytest.raises(LockTimeout) as ei:
            with project_lock(tmp_path, timeout=0.8):
                pass
        dt = time.perf_counter() - t0
        assert dt < 2.0, f'ожидание превысило timeout: {dt:.1f}с'
        msg = str(ei.value)
        assert 'блокировку' in msg and 'Подождите' in msg, (
            f'сообщение должно быть понятным по-русски: {msg}'
        )
    finally:
        p.wait(timeout=10)

    # Держатель вышел → захват мгновенный.
    with project_lock(tmp_path, timeout=2.0):
        pass


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
