"""Живой прогон выгрузки параметров по настоящим файлам моделей.

Почему отдельным файлом: в среде сборки нет ни клиентских проектов, ни тяжёлых
зависимостей загрузчика, поэтому здесь прогон пропускается. Структурная часть
сторожа живёт в `test_json_export_params.py` и идёт всегда – сторож, который
молча пропускается везде, не сторож.

Что доказывается на настоящих файлах: выдача честна на моделях РАЗНЫХ дат
обучения – там, где тип переноса записан конкретно, он читается; там, где
записана настройка «auto», она не превращается в факт; коэффициенты каналов
приходят настоящими числами, а не пустотой.

🔴 Файл модели копируется во временный каталог перед чтением: загрузчик умеет
переписывать модель ленивой миграцией в безопасный формат, а в каталог клиента
тест писать не вправе.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.json_export import export_model_params_json  # noqa: E402

ФАКТИЧЕСКИЕ_ТИПЫ_ПЕРЕНОСА = ('geometric', 'weibull')


def _живые_модели() -> list[Path]:
    """Файлы моделей из проектов установленного продукта (может не быть – тогда пропуск)."""
    корень = os.environ.get('APPDATA')
    if not корень:
        return []
    проекты = Path(корень) / 'aurora-econometrica-gui' / 'projects'
    if not проекты.is_dir():
        return []
    найденные = sorted(проекты.glob('*/models/latest.pkl'))
    # Разные даты обучения: берём самую старую и самую свежую по времени файла.
    if len(найденные) > 2:
        по_дате = sorted(найденные, key=lambda p: p.stat().st_mtime)
        найденные = [по_дате[0], по_дате[-1]]
    return найденные


МОДЕЛИ = _живые_модели()

pytestmark = pytest.mark.skipif(
    not МОДЕЛИ, reason='живых файлов моделей на машине нет – прогон невозможен',
)


@pytest.fixture(params=[str(p) for p in МОДЕЛИ], ids=lambda p: Path(p).parent.parent.name[:24])
def выдача(request, tmp_path) -> dict:
    """Копия модели во временном каталоге → загрузка → выгрузка параметров."""
    from engines.persistence import load_model_with_compat

    исходник = Path(request.param)
    копия = tmp_path / 'latest.pkl'
    shutil.copy2(исходник, копия)
    подпись = исходник.with_suffix('.pkl.sha256')
    if подпись.exists():
        shutil.copy2(подпись, копия.with_suffix('.pkl.sha256'))

    модель = load_model_with_compat(копия)
    диагностика = None
    файл_диагностики = исходник.parent.parent / 'results' / 'model-diagnostics.json'
    if файл_диагностики.exists():
        диагностика = json.loads(файл_диагностики.read_text(encoding='utf-8'))
    return json.loads(export_model_params_json(модель, diagnostics=диагностика))


def test_каналы_отдают_настоящие_числа(выдача):
    assert выдача['channels'], 'в живой модели обязаны быть каналы'
    for имя, канал in выдача['channels'].items():
        for поле in ('beta', 'hill_alpha', 'hill_gamma', 'adstock_decay', 'adstock_mean_posterior'):
            assert канал[поле] is not None, f'{имя}.{поле} пустое – чтение разошлось со схемой модели'
        assert канал['beta_std'] is not None, f'{имя}: разброс не посчитан, хотя выборки в модели есть'


def test_тип_переноса_честен_на_любой_дате_обучения(выдача):
    for имя, канал in выдача['channels'].items():
        записано = канал['adstock_type_recorded']
        выведено = канал['adstock_type']
        if записано in ФАКТИЧЕСКИЕ_ТИПЫ_ПЕРЕНОСА:
            assert выведено == записано, f'{имя}: записанный тип переноса не прочитан'
            assert канал['adstock_decay_learned'] is (записано == 'geometric')
        else:
            assert выведено is None, (
                f'{имя}: записано «{записано}», а выдача утверждает тип «{выведено}» – подстановка'
            )


def test_история_и_гранулярность_не_подставлены(выдача):
    assert выдача['history']['length'] and выдача['history']['length'] > 0
    assert выдача['history']['granularity'] != 'monthly', (
        'период истории обязан читаться кодом периода модели, а не англоязычным умолчанием'
    )


def test_категории_каналов_не_подменяются_словом_unknown(выдача):
    for имя, канал in выдача['channels'].items():
        assert канал['category'] != 'unknown', f'{имя}: категория подставлена вместо честной пустоты'


def test_отсутствующее_названо_отсутствующим(выдача):
    поля = {запись['field'] for запись in выдача['absent_fields']}
    for запись in выдача['absent_fields']:
        assert запись['reason'], f'{запись["field"]}: отсутствие заявлено без причины'
    # Паспорт воспроизводимости в моделях этих дат не записывался – проверяем,
    # что это названо, а не замаскировано пустым разделом.
    if выдача['reproducibility'].get('available') is False:
        assert 'reproducibility' in поля
