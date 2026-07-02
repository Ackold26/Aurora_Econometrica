"""MCMC params по бэкенду — характеризующие тесты мат-аудита 2026-07-02 (F-28).

Прежде get_mcmc_params решал по check_compiler(): без g++ → 2×1000×500 с ярлыком
sampler='Metropolis'. Ложь вдвойне: ключ sampler нигде не читается, Metropolis
запрещён (цепочка numpyro→pytensor→ADVI), а главное — Tier-1 NUTS идёт через
numpyro/JAX, которому g++ НЕ нужен: клиентская поставка с вендоренным JAX
получала ложный даунгрейд (2 цепи вместо канонических 4 — Vehtari et al. 2021,
половина draws). Теперь решает бэкенд: JAX или компилятор → полные 4/2000/2000;
урезка — только для PyTensor Python-mode (ни JAX, ни g++).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from engines.modeler import get_mcmc_params  # noqa: E402


def test_jax_without_compiler_gets_full_params():
    """Ядро F-28: JAX без g++ → полные канонические параметры (было 2×1000×500)."""
    p = get_mcmc_params(has_compiler=False, has_jax=True)
    assert (p['chains'], p['draws'], p['tune']) == (4, 2000, 2000)


def test_compiler_without_jax_gets_full_params():
    p = get_mcmc_params(has_compiler=True, has_jax=False)
    assert (p['chains'], p['draws'], p['tune']) == (4, 2000, 2000)


def test_neither_gets_reduced_but_honest_sampler():
    """Медленный путь: урезанные параметры, но ярлык честный (NUTS, не Metropolis)."""
    p = get_mcmc_params(has_compiler=False, has_jax=False)
    assert (p['chains'], p['draws'], p['tune']) == (2, 1000, 500)
    assert p['sampler'] == 'NUTS', 'Metropolis запрещён в цепочке — ярлык врал'


def test_autodetect_in_this_env():
    """Наша среда (numpyro установлен): автоопределение даёт полные параметры
    даже без компилятора — регрессия ложного даунгрейда."""
    pytest.importorskip('numpyro')
    p = get_mcmc_params(has_compiler=False)
    assert (p['chains'], p['draws'], p['tune']) == (4, 2000, 2000)


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
