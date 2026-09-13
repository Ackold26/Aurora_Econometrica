"""Гигиена состава поставки — Б-53 (следы прогонов тестов) + Б-46 (дубль dist/).

Один корень у обоих дефектов: широкий шаблон ресурсов Tauri
(`"../sidecar/econometrica/**/*"`) забирал в поставку ВСЁ, что лежало в
каталоге `sidecar/econometrica/` на момент сборки — включая собственный
дубль вывода PyInstaller (`dist/`, 926 МБ, Б-46, backlog) и следы прогонов
тестов (`.hypothesis`, `.pytest_cache`, `__pycache__`, Б-53, коммит
21d28ebe). Из-за этого состав поставки зависел от того, гоняли ли перед
сборкой тесты — два прогона одного кода давали разные установщики.

Лечение — две линии обороны, обе проверяются здесь БЕЗ полной сборки
установщика:

1. `tauri.conf.json` → явный список ресурсов sidecar (только exe + `_internal/`,
   не `**/*`). Рантайму движка (`src-tauri/src/econ_sidecar.rs::resolve_bundled_exe`)
   ничего больше не нужно — dev-режим (`spawn_python_dev`) читает исходники
   напрямую из репозитория, минуя Tauri-ресурсы.
2. `build_sidecar.py::purge_test_residue()` — снимает `__pycache__`/`.hypothesis`/
   `.pytest_cache`/`.mypy_cache`/`.ruff_cache` из уже собранного PyInstaller-пакета
   ПЕРЕД синком в `sidecar/econometrica/` (вторая линия — на случай, если след
   окажется внутри `_internal/`, куда `--add-data` копирует исходные каталоги
   как есть, вместе с тем мусором, что в них лежал на момент сборки).

Б-54 (найден 13.09.2026 разбором того же узкого списка ресурсов): узкий список
снял костыль широкого шаблона, который СЛУЧАЙНО клал `data/kpi_display_registry.json`
хотя бы рядом с exe. На самом деле каталог `data/` вообще не был в `--add-data`
PyInstaller — паспорт отображения KPI не попадал в собранный `_internal/` НИКОГДА,
`utils/kpi_display.py::_load()` кидал `FileNotFoundError`, а оба потребителя
(`aurora_html/sections.py`, `aurora_pptx/kpi_helpers.py`) глотали её через
`except Exception: return None` — отчёты молча откатывались на денежные подписи
для любого KPI. Лечение — `'--add-data', f'{ROOT / "data"}:data'` в
`PYINSTALLER_ARGS`; сторож на класс — `KNOWN_FILE_RELATIVE_RESOURCES` +
`add_data_destinations()` в `build_sidecar.py`: реестр всех известных
`Path(__file__)`-чтений ресурса, сверяемый с фактическим списком `--add-data`.

Отдельно — вопрос о молчаливом `except Exception: return None`, спрятавшем
Б-54 месяцами: вызывающие (`aurora_html/sections.py`, `aurora_pptx/kpi_helpers.py`)
не трогаем (чужая зона, и отчёт обязан собираться без паспорта, падать нельзя).
Лечение — на стороне `utils/kpi_display.py::_load()`: ловит `FileNotFoundError`
отдельно, пишет `logger.error()` и перевыбрасывает — широкий except выше как
ловил, так и ловит, поведение вызывающих не изменилось, но пропажа реестра
теперь видна в журнале sidecar без живого прогона на собранном пакете.
"""

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SIDECAR_ROOT = _HERE.parent                            # sidecar/econometrica/
_REPO_ROOT = _SIDECAR_ROOT.parent.parent                 # корень рабочего дерева
_TAURI_CONF = _REPO_ROOT / 'src-tauri' / 'tauri.conf.json'

if str(_SIDECAR_ROOT) not in sys.path:
    sys.path.insert(0, str(_SIDECAR_ROOT))

from build_sidecar import (  # noqa: E402
    KNOWN_FILE_RELATIVE_RESOURCES,
    PYINSTALLER_ARGS,
    TEST_RESIDUE_DIR_NAMES,
    add_data_destinations,
    purge_test_residue,
)


# ─── Б-46/Б-53: явный список ресурсов, не широкий шаблон ──────────────────────

def test_tauri_resources_do_not_use_wide_sidecar_glob():
    """Ресурс sidecar в tauri.conf.json — явный список (exe + _internal/), не '**/*'.

    Регресс на широкий шаблон (`../sidecar/econometrica/**/*` или голый
    `../sidecar/econometrica/`) снова заберёт в поставку dist/ (Б-46) и любой
    мусор, оказавшийся в дереве на момент сборки (Б-53, тесты/`__pycache__`/
    `.hypothesis`/`.pytest_cache`).
    """
    assert _TAURI_CONF.exists(), f'tauri.conf.json не найден: {_TAURI_CONF}'
    conf = json.loads(_TAURI_CONF.read_text(encoding='utf-8'))
    resources = conf['bundle']['resources']

    sidecar_entries = [r for r in resources if 'sidecar/econometrica' in r]
    assert sidecar_entries, (
        'ни один ресурс не ссылается на sidecar/econometrica - движок не уедет клиенту'
    )

    wide = [r for r in sidecar_entries if '**' in r or r.rstrip('/').endswith('econometrica')]
    assert not wide, (
        f'широкий шаблон ресурсов sidecar вернулся: {wide} - заберёт dist/ (Б-46) '
        'и любые следы тестов (Б-53) вместе с рантаймом'
    )

    # Список обязан быть РОВНО тем, что нужно рантайму: exe + _internal/.
    # Не шире (см. wide выше) и не уже - иначе движок перестанет запускаться
    # у клиента, а сторож должен был бы упасть ДО того, как это заметит живой прогон.
    expected_suffixes = ('econometrica-sidecar.exe', '_internal', '_internal/')
    unexpected = [r for r in sidecar_entries if not r.rstrip('/').endswith(('econometrica-sidecar.exe', '_internal'))]
    assert not unexpected, f'неожиданный ресурс sidecar (не exe и не _internal/): {unexpected}'

    has_exe = any(r.rstrip('/').endswith('econometrica-sidecar.exe') for r in sidecar_entries)
    has_internal = any(r.rstrip('/').endswith('_internal') for r in sidecar_entries)
    assert has_exe, 'ресурс на econometrica-sidecar.exe пропал - движок не будет спавниться'
    assert has_internal, 'ресурс на _internal/ пропал - exe будет собран без своих зависимостей'


# ─── Б-53: сторож на класс, мутационное доказательство ────────────────────────

def _plant_residue(pkg_root: Path) -> list[Path]:
    """Создаёт подставное дерево: настоящий код движка вперемешку со следами
    прогонов тестов/линтеров - ровно та форма, что нашёл живой прогон 12.09
    (`.hypothesis`, `.pytest_cache`, `__pycache__` рядом с исходниками,
    скопированными `--add-data` внутрь `_internal/`).
    """
    (pkg_root / '_internal' / 'engines').mkdir(parents=True)
    (pkg_root / '_internal' / 'engines' / 'channel_action.py').write_text('# real module\n')
    (pkg_root / 'econometrica-sidecar.exe').write_bytes(b'MZ-fake-pe-header')

    residue_dirs = [
        pkg_root / '_internal' / 'engines' / '__pycache__',
        pkg_root / '_internal' / 'aurora_pptx' / '__pycache__',
        pkg_root / '_internal' / '.hypothesis',
        pkg_root / '.pytest_cache',
        pkg_root / '.ruff_cache',
    ]
    for d in residue_dirs:
        d.mkdir(parents=True)
        (d / 'trace.bin').write_bytes(b'\x00\x01\x02')
    return residue_dirs


def test_purge_test_residue_removes_and_only_removes_traces(tmp_path):
    """RED->GREEN мутацией: следы кладём сами, сторож обязан снять ИМЕННО их
    и не тронуть настоящий код рядом.
    """
    pkg = tmp_path / 'econometrica-sidecar'
    residue_dirs = _plant_residue(pkg)
    real_module = pkg / '_internal' / 'engines' / 'channel_action.py'
    real_exe = pkg / 'econometrica-sidecar.exe'

    # RED - до чистки мутация реальна: следы физически на диске.
    for d in residue_dirs:
        assert d.exists(), f'мутация не создалась: {d}'

    removed = purge_test_residue(pkg)

    # GREEN - после чистки следов нет.
    for d in residue_dirs:
        assert not d.exists(), f'{d} должен быть снят purge_test_residue, но остался'
    assert len(removed) == len(residue_dirs)
    assert {p.name for p in residue_dirs} <= TEST_RESIDUE_DIR_NAMES | {p.name for p in residue_dirs}

    # Настоящие файлы движка - не тронуты.
    assert real_module.exists() and real_module.read_text() == '# real module\n'
    assert real_exe.exists() and real_exe.read_bytes() == b'MZ-fake-pe-header'


def test_purge_test_residue_no_op_on_clean_tree(tmp_path):
    """Отрицательный контроль: без мутации сторож ничего не снимает и не падает."""
    pkg = tmp_path / 'clean-sidecar'
    (pkg / '_internal').mkdir(parents=True)
    (pkg / '_internal' / 'module.py').write_text('# ok\n')
    (pkg / 'econometrica-sidecar.exe').write_bytes(b'MZ')

    removed = purge_test_residue(pkg)

    assert removed == []
    assert (pkg / '_internal' / 'module.py').exists()
    assert (pkg / 'econometrica-sidecar.exe').exists()


def test_purge_test_residue_handles_nested_residue(tmp_path):
    """Вложенный след (__pycache__ внутри каталога, который сам не является
    следом) снимается, не роняя обход os.walk(topdown=False)."""
    pkg = tmp_path / 'nested'
    deep = pkg / '_internal' / 'a' / 'b' / 'c' / '__pycache__'
    deep.mkdir(parents=True)
    (deep / 'x.pyc').write_bytes(b'\x00')
    (pkg / '_internal' / 'a' / 'b' / 'module.py').write_text('# ok\n')

    removed = purge_test_residue(pkg)

    assert removed == [deep]
    assert not deep.exists()
    assert (pkg / '_internal' / 'a' / 'b' / 'module.py').exists()


# ─── Б-54: каждый Path(__file__)-ресурс обязан быть в --add-data ─────────────

def test_all_known_file_relative_resources_are_bundled():
    """Реальный `PYINSTALLER_ARGS` обязан покрывать весь реестр
    `KNOWN_FILE_RELATIVE_RESOURCES` — иначе один из модулей движка
    (`utils/kpi_display.py` и далее по списку) читает несуществующий в
    собранном пакете путь и молча возвращает None/падает мимо тестов
    (оба потребителя паспорта KPI глотают исключение).
    """
    dests = add_data_destinations(PYINSTALLER_ARGS)
    missing = set(KNOWN_FILE_RELATIVE_RESOURCES) - dests
    assert not missing, (
        f'ресурс(ы) {sorted(missing)} читаются движком по Path(__file__)-пути, '
        f'но не перечислены в --add-data PYINSTALLER_ARGS: '
        f'{[KNOWN_FILE_RELATIVE_RESOURCES[m] for m in missing]}'
    )


def test_add_data_destinations_extraction_catches_missing_entry():
    """Мутация: убираем пару `'--add-data', '...:data'` из КОПИИ реального
    списка аргументов - проверка обязана покраснеть и НАЗВАТЬ ровно эту пропажу
    (Б-54 воспроизведена искусственно, настоящий build_sidecar.py не трогаем).
    """
    mutated = list(PYINSTALLER_ARGS)
    for i, item in enumerate(mutated):
        if item == '--add-data' and mutated[i + 1].rsplit(':', 1)[-1] == 'data':
            del mutated[i:i + 2]
            break
    else:
        raise AssertionError(
            "не нашли пару '--add-data ...:data' в PYINSTALLER_ARGS - мутацию "
            "ставить не на чем (регресс сам по себе уже произошёл?)"
        )

    # RED - на испорченной копии реестр обязан заметить пропажу ровно 'data'.
    dests = add_data_destinations(mutated)
    missing = set(KNOWN_FILE_RELATIVE_RESOURCES) - dests
    assert missing == {'data'}, (
        f'мутация должна была снять ровно data:data, получили пропажу {missing}'
    )

    # GREEN - реальный (не мутированный) список по-прежнему полон.
    assert not set(KNOWN_FILE_RELATIVE_RESOURCES) - add_data_destinations(PYINSTALLER_ARGS)


def test_purge_test_residue_dir_names_match_bs53_incident():
    """Регресс-замок на конкретные имена из инцидента 12.09 (.hypothesis,
    .pytest_cache, __pycache__) - расширять список можно, сужать нельзя без
    осознанного решения."""
    assert {'__pycache__', '.hypothesis', '.pytest_cache'} <= TEST_RESIDUE_DIR_NAMES


# ─── Б-54: пропажа паспорта KPI обязана оставить след в журнале ───────────────
#
# Вопрос владельца: молчаливый `except Exception: return None` в вызывающих
# (aurora_html/sections.py::_passport_html, aurora_pptx/kpi_helpers.py::_passport)
# скрывал Б-54 месяцами. Их не трогаем (чужая зона, и отчёт обязан собираться
# даже без паспорта - падать нельзя). Лечение - на стороне utils/kpi_display.py
# (не код отчётов, модуль чтения ресурса): `_load()` теперь ловит
# FileNotFoundError отдельно, пишет logger.error() и ПЕРЕВЫБРАСЫВАЕТ - широкий
# except выше как ловил, так и ловит, отчёт как собирался без паспорта, так и
# собирается; разница - теперь пропажа реестра видна в журнале sidecar без
# живого прогона на собранном пакете.

def test_missing_kpi_registry_logs_error_before_raising(monkeypatch, caplog):
    """Мутация: подменяем `_DATA_PATH` на несуществующий файл, сбрасываем кеш
    модуля - `_load()` обязана и залогировать ошибку, и поднять исключение
    (чтобы существующий `except Exception: return None` у вызывающих продолжил
    работать как раньше)."""
    import importlib
    import logging

    kpi_display = importlib.import_module('utils.kpi_display')
    missing_path = _HERE / '_does_not_exist' / 'kpi_display_registry.json'
    assert not missing_path.exists()

    monkeypatch.setattr(kpi_display, '_DATA_PATH', missing_path)
    monkeypatch.setattr(kpi_display, '_registry', {})

    with caplog.at_level(logging.ERROR, logger='utils.kpi_display'):
        with pytest.raises(FileNotFoundError):
            kpi_display._load()

    assert any(
        'Реестр отображения KPI не найден' in rec.message and str(missing_path) in rec.message
        for rec in caplog.records
    ), f'ожидали ERROR-запись про пропажу {missing_path}, получили: {[r.message for r in caplog.records]}'


def test_kpi_registry_loads_cleanly_when_present(monkeypatch):
    """Отрицательный контроль: реальный файл на месте - `_load()` не логирует
    ошибку и не падает (мутация выше не путает штатный путь с поломанным)."""
    import importlib

    kpi_display = importlib.import_module('utils.kpi_display')
    monkeypatch.setattr(kpi_display, '_registry', {})

    data = kpi_display._load()

    assert isinstance(data, dict) and data, 'реальный kpi_display_registry.json обязан грузиться штатно'
