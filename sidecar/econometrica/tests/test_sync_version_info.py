"""`build_sidecar.py::sync_version_info()` — сведение версии движка с версией
продукта не должно уметь молчать (s49, находка ведущей 18.09.2026).

Симптом: собранный `econometrica-sidecar.exe` (18.09, 12:01:56) нёс
`FileVersion`/`ProductVersion` 2.5.4.0, когда продукт уже 2.5.5 (`package.json`
поднят в 11:58:47, ДО завершения той же сборки). Гипотеза ведущей была «шаг
сверяет время файла, а не содержимое» (тот же класс, что уже записан в памяти:
«шаг подготовки, сверяющий время файла вместо версии, молча кладёт старое»).

Зонд (прямой вызов `sync_version_info()` живьём против текущего
`version_info.txt`=2.5.4 и `package.json`=2.5.5) её ОПРОВЕРГ: функция сравнивает
СОДЕРЖИМОЕ регулярным выражением (`vi.read_text()` → `re.sub` → `text != before`),
не время файла, и корректно свела файл до 2.5.5.0 с первого вызова. Настоящая
причина расхождения - гонка совместных сессий в общем git worktree: сборка,
породившая exe от 12:01:56, стартовала ДО правки `package.json` (PyInstaller-этап
после `sync_version_info()` идёт много минут), `sync_version_info()` в её начале
честно прочитал ЕЩЁ старую версию 2.5.4 и корректно не нашёл расхождения - не
дефект шага, а свойство любой синхронизации-в-начале-долгой-сборки при
конкурентной правке версии в общем дереве. Полная фактура - в отчёте сессии.

Этот файл тем не менее закрывает прямой запрос ведущей (её пункт 3): доказать,
что сторож `sync_version_info()` дЕЙСТВИТЕЛЬНО падает на расхождении, а не
молча проходит мимо - на случай, если сама гипотеза про время файла была
неверна (подтверждено), но верна для БУДУЩЕГО класса дефекта - если регексы
substitution когда-нибудь перестанут совпадать с форматом файла (опечатка,
чужая правка формата PyInstaller version-file), функция обязана упасть, а не
тихо «уже на версии продукта X» соврать при фактическом расхождении.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SIDECAR_ROOT = _HERE.parent

if str(_SIDECAR_ROOT) not in sys.path:
    sys.path.insert(0, str(_SIDECAR_ROOT))

import build_sidecar  # noqa: E402

_VI_TEMPLATE = """# UTF-8 (тестовая мини-версия настоящего version_info.txt)
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v0}, {v1}, {v2}, 0),
    prodvers=({v0}, {v1}, {v2}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '041904B0',
          [
            StringStruct('CompanyName', 'Aurora Platform LLC'),
            StringStruct('FileVersion', '{v0}.{v1}.{v2}.0'),
            StringStruct('ProductVersion', '{v0}.{v1}.{v2}.0'),
          ],
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1049, 1200])]),
  ],
)
"""

# То же самое, но StringStruct-строки в двойных кавычках - substitution-регексы
# `sync_version_info()` ловят только одинарные (как в настоящем файле), поэтому
# после правки filevers/prodvers (эти регексы кавычек не используют) StringStruct
# останутся НЕТРОНУТЫМИ - имитация «формат разошёлся, подстановка молча не
# сработала для части полей».
_VI_TEMPLATE_MISMATCHED_QUOTES = _VI_TEMPLATE.replace(
    "StringStruct('FileVersion', '{v0}.{v1}.{v2}.0')",
    'StringStruct("FileVersion", "{v0}.{v1}.{v2}.0")',
).replace(
    "StringStruct('ProductVersion', '{v0}.{v1}.{v2}.0')",
    'StringStruct("ProductVersion", "{v0}.{v1}.{v2}.0")',
)


def _make_repo(tmp_path, package_version: str, vi_template: str, vi_version=(2, 5, 4)):
    """Строит фейковый корень (package.json + sidecar/econometrica/version_info.txt)
    в изоляции от настоящего репозитория - ничего в реальном дереве не трогает."""
    fake_root = tmp_path / "sidecar" / "econometrica"
    fake_root.mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        f'{{\n  "name": "test",\n  "version": "{package_version}"\n}}\n', encoding="utf-8"
    )
    vi = fake_root / "version_info.txt"
    vi.write_text(
        vi_template.format(v0=vi_version[0], v1=vi_version[1], v2=vi_version[2]),
        encoding="utf-8",
    )
    return fake_root, vi


# ─── Красное-зелёное на сам вопрос ведущей: молчит или падает/сводит ────────

def test_sync_updates_stale_version_to_match_product(tmp_path, monkeypatch):
    """Основной случай (ровно то, что нашла ведущая): version_info.txt=2.5.4,
    package.json=2.5.5 → после вызова файл обязан стать 2.5.5.0 везде."""
    fake_root, vi = _make_repo(tmp_path, "2.5.5", _VI_TEMPLATE, vi_version=(2, 5, 4))
    monkeypatch.setattr(build_sidecar, "ROOT", fake_root)
    build_sidecar.sync_version_info()
    text = vi.read_text(encoding="utf-8")
    assert "2.5.5.0" in text
    assert "2.5.4" not in text, "старая версия обязана исчезнуть из файла целиком"
    assert "filevers=(2, 5, 5, 0)" in text
    assert "prodvers=(2, 5, 5, 0)" in text


def test_sync_is_noop_when_already_synced(tmp_path, monkeypatch):
    fake_root, vi = _make_repo(tmp_path, "2.5.5", _VI_TEMPLATE, vi_version=(2, 5, 5))
    monkeypatch.setattr(build_sidecar, "ROOT", fake_root)
    before = vi.read_text(encoding="utf-8")
    build_sidecar.sync_version_info()  # не обязан упасть и не обязан ничего менять
    assert vi.read_text(encoding="utf-8") == before


def test_sync_exits_loudly_when_format_drifts_and_substitution_cannot_land(tmp_path, monkeypatch):
    """Имитация «формат version_info.txt разошёлся с регексами substitution»
    (двойные кавычки вместо одинарных у StringStruct) - именно тот класс,
    который ведущая просила проверить прямо: если шаг умеет только молчать при
    фактическом расхождении, это дефект. Здесь - не молчит: сторож обязан
    завершить процесс ошибкой (sys.exit(1)), а не напечатать «уже на версии
    продукта» при незакрытом расхождении."""
    fake_root, vi = _make_repo(
        tmp_path, "2.5.5", _VI_TEMPLATE_MISMATCHED_QUOTES, vi_version=(2, 5, 4)
    )
    monkeypatch.setattr(build_sidecar, "ROOT", fake_root)
    with pytest.raises(SystemExit) as exc_info:
        build_sidecar.sync_version_info()
    assert exc_info.value.code == 1
    # filevers/prodvers (регекс без кавычек) успел подтянуться до правильной
    # версии, а StringStruct - нет: файл на диске остаётся в противоречивом
    # состоянии, ИМЕННО поэтому сторож обязан упасть, а не сказать «готово».
    text = vi.read_text(encoding="utf-8")
    assert "filevers=(2, 5, 5, 0)" in text
    assert '"FileVersion", "2.5.4.0"' in text, (
        "StringStruct в двойных кавычках не должен был совпасть с одинарнокавычечным "
        "регексом - если совпал, тестовая имитация несостоятельна"
    )


def test_sync_exits_on_malformed_product_version(tmp_path, monkeypatch):
    fake_root, vi = _make_repo(tmp_path, "2.5", _VI_TEMPLATE, vi_version=(2, 5, 4))
    monkeypatch.setattr(build_sidecar, "ROOT", fake_root)
    with pytest.raises(SystemExit) as exc_info:
        build_sidecar.sync_version_info()
    assert exc_info.value.code == 1


# ─── Зонд-регрессия: сам факт находки ведущей воспроизведён и закрыт ─────────

def test_probe_reproduces_and_closes_the_reported_symptom(tmp_path, monkeypatch):
    """Тот же сценарий, что был у ведущей на реальном движке (2.5.4 vs 2.5.5),
    доказывает и красное (файл до вызова несёт 2.5.4 при продукте 2.5.5 - то,
    что увидел ИТ-специалист покупателя в свойствах файла), и зелёное (после
    вызова - расхождения нет)."""
    fake_root, vi = _make_repo(tmp_path, "2.5.5", _VI_TEMPLATE, vi_version=(2, 5, 4))
    monkeypatch.setattr(build_sidecar, "ROOT", fake_root)
    before = vi.read_text(encoding="utf-8")
    assert "2.5.4.0" in before and "2.5.5.0" not in before, "красное: расхождение воспроизведено"
    build_sidecar.sync_version_info()
    after = vi.read_text(encoding="utf-8")
    assert "2.5.5.0" in after and "2.5.4.0" not in after, "зелёное: расхождение закрыто"
