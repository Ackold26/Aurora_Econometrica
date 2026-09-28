# -*- coding: utf-8 -*-
"""Сторож снятия процессов в хуке установщика `src-tauri/installer_hooks.nsh` (CPD-208, s55, 2026-09-28).

Зачем: вызов `taskkill /FI "USERNAME eq %USERNAME%" /IM <образ> /T /F` у процесса без повышения
висит минутами – у стандартного пользователя ~7 мин, у администратора без повышения >30 с (реестр
CPD-208, Smart Analytica s57), и цель за это время не гасится. Эконометрика ставится `currentUser`
(`src-tauri/tauri.conf.json`), установщик идёт без повышения – класс у нас жив. Порознь ключи `/T`
и `/FI USERNAME` быстрые, зависает только их сочетание в ОДНОМ вызове taskkill. Макрос
AURORA_KILL_AND_WAIT поэтому снимает в два шага (эталон SA `897d7c7`): свои PID даёт tasklist
с фильтром по учётной записи, дерево гасится по PID (`/PID … /T /F`).

Сторож держит запрет и решения хука, которые правка обязана была сохранить:
  (1) ни один вызов taskkill не несёт одновременно `/T` и `/FI "USERNAME …"`;
  (2) дерево гасится (`/T` на месте) – без него дочерние процессы движка переживают главный;
  (3) снимается только СВОЁ – PID из tasklist с фильтром `USERNAME eq %USERNAME%` в той же строке;
  (4) проверка живости – БЕЗ фильтра по учётной записи и через `$SYSDIR\\find.exe` («бить узко,
      смотреть широко», шапка хука, 18.09.2026);
  (5) каждая внешняя команда идёт через `cmd /c` (иначе `%USERNAME%` не развернётся) и через
      nsExec::Exec (без окна и без OEM-вывода в журнал);
  (6) `tasklist`/`taskkill` без полных путей – закавыченный путь в начале строки `cmd /c` ломал
      разбор кавычек (зонд 18.09.2026); внешние пары кавычек эталона SA тут не нужны.
Проверяется макрос AURORA_KILL_AND_WAIT и то, что его вставляют оба хука (PREINSTALL, PREUNINSTALL)
для обоих образов.

Аудит s55 (AUDIT_s55_257.md, M-3/M-4): проверок присутствия ключей мало – сторож был зелёным при
`%%a`, без `/FO CSV`, с `tokens=2`, без `if /i`, а цель переживала снятие. Поэтому ещё:
  (7) рабочий разбор строки снятия (`tokens=1,2 delims=,`, `%a`/`%~b` с одним `%`, `if /i %a==…`,
      CSV) и проверки живости (CSV и имя в кавычках: таблица режет имя до 25 знаков, а у
      интерфейса их 27 – проверка всегда отвечала «процесса нет»);
  (8) ИСПОЛНЯЕМЫЕ пробы (только Windows): обе строки макроса выполняются как у nsExec на
      подставном процессе с дочерним и именем длиннее 25 знаков; и макрос целиком, собранный
      `makensis` из комплекта Tauri (`%LOCALAPPDATA%\\tauri\\NSIS`) в учебный установщик, – если
      makensis нет, эта проба пропускается.

Запуск: `python tools/test_installer_hooks.py` (стандартная библиотека) или через pytest.
Выход 0 = все зелёные; иначе список провалов, код 1.
"""
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

try:
    import pytest
except ImportError:  # запуск без pytest: `python tools/test_installer_hooks.py`
    pytest = None

_ROOT = Path(__file__).resolve().parents[1]
_HOOK = _ROOT / "src-tauri" / "installer_hooks.nsh"
_KILL_MACRO = "AURORA_KILL_AND_WAIT"
_HOOKS = ("NSIS_HOOK_PREINSTALL", "NSIS_HOOK_PREUNINSTALL")
_IMAGES = ("econometrica-sidecar.exe", "aurora-econometrica-gui.exe")
_USER_FILTER = re.compile(r'/FI\s+"USERNAME eq %USERNAME%"', re.I)
# (7) Разбор вывода tasklist в строке снятия: шаблон → что ломается без него.
_KILL_PARSE = (
    (r'for /f "tokens=1,2 delims=," (?<!%)%a in \(', "поля CSV «имя, PID» в %a и %b, переменная с одним %"),
    (r"\('tasklist [^']*/FO CSV", "tasklist в CSV – иначе строка не делится запятой"),
    (r'if /i (?<!%)%a=="\$\{IMAGE\}"', "первое поле сверяется с именем образа"),
    (r"taskkill /PID (?<!%)%~b /T /F", "снятие дерева по PID из второго поля"),
)


def macro_body(text, name):
    """Строки макроса без комментариев (NSIS: `;` или `#` в начале строки)."""
    m = re.search(r"^!macro\s+" + name + r"\b(.*?)^!macroend", text, re.S | re.M)
    if not m:
        return None
    return [ln.strip() for ln in m.group(1).splitlines()
            if ln.strip() and not ln.lstrip().startswith((";", "#"))]


def taskkill_args(line):
    """Аргументы каждого вызова taskkill в строке – от имени утилиты до конца строки."""
    return [line[m.end():] for m in re.finditer(r"taskkill(?:\.exe)?\"?", line, re.I)]


def check(text):
    fails = []
    body = macro_body(text, _KILL_MACRO)
    if body is None:
        return [f"{_KILL_MACRO}: макрос не найден в {_HOOK.name}"]
    kills = [ln for ln in body if re.search(r"\btaskkill\b", ln, re.I)]
    checks = [ln for ln in body if re.search(r"\btasklist\b", ln, re.I) and "find.exe" in ln.lower()]
    if not kills:
        fails.append(f"{_KILL_MACRO}: нет ни одного вызова taskkill – файлы движка перед копированием не освобождаются")
    for ln in kills:
        if not ln.startswith("nsExec::Exec"):
            fails.append(f"{_KILL_MACRO}: снятие не через nsExec::Exec (окно cmd или кракозябры в журнале): {ln}")
        if not re.match(r"nsExec::Exec\s+[`']cmd /c ", ln):
            fails.append(f"{_KILL_MACRO}: снятие не через `cmd /c` – %USERNAME% не развернётся, "
                         f"фильтр мёртв (шапка хука, 18.09.2026): {ln}")
        for args in taskkill_args(ln):
            has_t = re.search(r"(?<!\S)/T(?!\S)", args, re.I)
            has_user = re.search(r"/FI\s+\"USERNAME", args, re.I)
            if has_t and has_user:
                fails.append(f"{_KILL_MACRO}: taskkill несёт одновременно /T и /FI USERNAME – вешает установку "
                             f"у пользователя без повышения на минуты (CPD-208): {ln}")
            if not has_t:
                fails.append(f"{_KILL_MACRO}: taskkill без /T – дочерние процессы движка переживут "
                             f"главный и займут файлы: {ln}")
        if not (re.search(r"\btasklist\b", ln, re.I) and _USER_FILTER.search(ln) and "/PID" in ln.upper()):
            fails.append(f"{_KILL_MACRO}: PID для снятия берутся не из tasklist с фильтром по своей "
                         f"учётной записи – погаснет чужой сеанс программы: {ln}")
        if re.search(r"\$SYSDIR\\(taskkill|tasklist)", ln, re.I):
            fails.append(f"{_KILL_MACRO}: полный путь к taskkill/tasklist в строке снятия – отвергнут зондом "
                         f"18.09.2026 (ломает разбор кавычек в cmd /c): {ln}")
        # (7) Рабочий разбор: поля CSV «имя»,«PID» → %a, %~b. Переменная цикла на командной строке
        # `cmd /c` – с ОДНИМ `%` (`%%a` – только в .cmd, иначе «Непредвиденное появление: %%a»).
        for pattern, why in _KILL_PARSE:
            if not re.search(pattern, ln):
                fails.append(f"{_KILL_MACRO}: строка снятия не разбирает вывод tasklist как задумано "
                             f"({why}) – цель переживёт снятие, у каждого покупателя «Обновление не "
                             f"выполнено» (аудит s55, M-3): {ln}")
    if not checks:
        fails.append(f"{_KILL_MACRO}: нет проверки живости через tasklist | find")
    for ln in checks:
        # Табличный tasklist режет имя образа до 25 знаков; у интерфейса 27 – `find` полного имени
        # не находил, для интерфейса проверка всегда отвечала «процесса нет» (аудит s55, M-4).
        if not (re.search(r"/FO\s+CSV", ln, re.I) and '/I """${IMAGE}"""' in ln):
            long_images = [i for i in _IMAGES if len(i) > 25]
            fails.append(f"{_KILL_MACRO}: проверка живости не через CSV с именем в кавычках – табличный "
                         f"вывод режет имя до 25 знаков, {', '.join(long_images)} для неё всегда "
                         f"«не запущен» (аудит s55, M-4): {ln}")
        if _USER_FILTER.search(ln):
            fails.append(f"{_KILL_MACRO}: проверка живости с фильтром по учётной записи – процесс другого "
                         f"сеанса станет невидим, и установка доложит «успешно» поверх занятого файла: {ln}")
        if "$sysdir\\find.exe" not in ln.lower():
            fails.append(f"{_KILL_MACRO}: find не по полному пути $SYSDIR – `find` из Git for Windows "
                         f"не понимает /I и молча выдаёт «процесса нет»: {ln}")
    for hook in _HOOKS:
        hbody = macro_body(text, hook)
        if hbody is None:
            fails.append(f"{hook}: макрос не найден в {_HOOK.name}")
            continue
        for image in _IMAGES:
            if not any(re.match(r"!insertmacro\s+" + _KILL_MACRO + r'\s+"' + re.escape(image) + '"', ln)
                       for ln in hbody):
                fails.append(f"{hook}: {image} не снимается через {_KILL_MACRO}")
    return fails


def _hook_text():
    return _HOOK.read_text(encoding="utf-8-sig")


def test_installer_hook_kill_without_tree_and_user_filter_in_one_call():
    fails = check(_hook_text())
    assert not fails, "\n".join(fails)


def test_guard_catches_old_hanging_form():
    """Мутация на копии: прежняя строка (CPD-208) обязана покраснеть сторожем."""
    old = "  nsExec::Exec 'cmd /c taskkill /FI \"USERNAME eq %USERNAME%\" /IM \"${IMAGE}\" /T /F'"
    text = _hook_text()
    body = macro_body(text, _KILL_MACRO)
    kill = next(ln for ln in body if re.search(r"\btaskkill\b", ln, re.I))
    mutated = text.replace(kill, old.strip(), 1)
    assert mutated != text
    assert any("CPD-208" in f for f in check(mutated))


# Поломки, при которых прежний сторож оставался зелёным (аудит s55, M-3), и возврат табличной
# проверки живости (M-4): фрагмент действующей строки → замена.
_BREAKAGES = {
    "percent_doubled": ("%a in (", "%%a in ("),
    "no_csv_in_kill": (" /FO CSV /NH')", " /NH')"),
    "tokens_2": ('"tokens=1,2 delims=,"', '"tokens=2 delims=,"'),
    "no_image_if": ('do if /i %a=="${IMAGE}" taskkill', "do taskkill"),
    "table_check": ('/FO CSV /NH | "$SYSDIR\\find.exe" /I """${IMAGE}"""', '/NH | "$SYSDIR\\find.exe" /I "${IMAGE}"'),
}


def _break(text, name):
    old, new = _BREAKAGES[name]
    assert text.count(old) == 1, (name, text.count(old))
    return text.replace(old, new, 1)


def _each_breakage(fn):
    if pytest is None:
        return fn
    return pytest.mark.parametrize("name", sorted(_BREAKAGES))(fn)


@_each_breakage
def test_guard_catches_audit_breakages(name):
    """Мутация на копии текста: каждая поломка из аудита s55 обязана покраснеть сторожем."""
    text = _hook_text()
    mutated = _break(text, name)
    assert mutated != text
    assert check(mutated), f"сторож зелёный при поломке {name}"


# ─── (8) Исполняемые пробы: строки макроса на подставном процессе ───────────────────────────────

_SYSDIR = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
_NO_WINDOW = 0x08000000


def _windows_only(fn):
    if pytest is None:
        return fn
    return pytest.mark.skipif(sys.platform != "win32", reason="nsExec/cmd/tasklist – только Windows")(fn)


def _nsexec_command(line):
    """Командная строка, которую nsExec::Exec отдаёт CreateProcess (строка NSIS без кавычек-ограничителей)."""
    m = re.match(r"nsExec::Exec\s+(['`])(.*)\1$", line)
    assert m, line
    return m.group(2)


def _expand(cmd, image):
    """Подстановки NSIS, которые встречаются в строках макроса: ${IMAGE} и $SYSDIR."""
    out = cmd.replace("${IMAGE}", image).replace("$SYSDIR", str(_SYSDIR)).replace("$$", "$")
    assert "$" not in out, f"неразвёрнутая переменная NSIS: {out}"
    return out


def _macro_lines(text):
    body = macro_body(text, _KILL_MACRO)
    check_ln = next(ln for ln in body if re.search(r"\btasklist\b", ln, re.I) and "find.exe" in ln.lower())
    kill_ln = next(ln for ln in body if re.search(r"\btaskkill\b", ln, re.I))
    return _nsexec_command(check_ln), _nsexec_command(kill_ln)


def _alive(image):
    out = subprocess.run(f'tasklist /FI "IMAGENAME eq {image}" /FO CSV /NH', capture_output=True).stdout
    return f'"{image}"'.encode("ascii") in out


def _wait(pred, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.2)
    return pred()


class _Decoy:
    """Подставной процесс с дочерним: копия cmd.exe под именем длиннее 25 знаков (как у интерфейса)
    запускает копию ping.exe. Имена уникальны – параллельные прогоны друг друга не снимут."""

    def __init__(self, tmp):
        tag = uuid.uuid4().hex[:8]
        self.image = f"aurora-hooktest-{tag}-gui.exe"
        self.child = f"aurora-hooktest-{tag}-kid.exe"
        assert len(self.image) > 25
        self.image_path = Path(tmp) / self.image
        self.child_path = Path(tmp) / self.child
        shutil.copyfile(_SYSDIR / "cmd.exe", self.image_path)
        shutil.copyfile(_SYSDIR / "PING.EXE", self.child_path)
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen(
            f'"{self.image_path}" /c ""{self.child_path}" -n 600 127.0.0.1 >nul"',
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        assert _wait(lambda: _alive(self.image) and _alive(self.child), 10), "подставной процесс не поднялся"

    def cleanup(self):
        for image in (self.image, self.child):
            subprocess.run(f'taskkill /IM "{image}" /T /F', capture_output=True)
        if self.proc is not None:
            self.proc.wait(timeout=10)


@_windows_only
def test_macro_lines_execute_on_decoy(tmp_path):
    """Обе строки макроса, как их исполнит nsExec: проверка видит длинное имя, снятие гасит дерево."""
    check_cmd, kill_cmd = _macro_lines(_hook_text())
    decoy = _Decoy(tmp_path)
    check_cmd, kill_cmd = _expand(check_cmd, decoy.image), _expand(kill_cmd, decoy.image)
    try:
        assert subprocess.run(check_cmd, capture_output=True).returncode != 0, "процесса нет, а проверка «жив»"
        # Процесса нет: строка «задачи отсутствуют» не должна дойти до taskkill (сторож `if /i`).
        empty = subprocess.run(kill_cmd, capture_output=True)
        assert empty.stderr.strip() == b"", f"снятие при пустом списке вызвало taskkill: {empty.stderr!r}"
        decoy.start()
        assert subprocess.run(check_cmd, capture_output=True).returncode == 0, \
            f"проверка живости не видит {decoy.image} ({len(decoy.image)} знаков)"
        subprocess.run(kill_cmd, capture_output=True, timeout=60)
        assert _wait(lambda: not _alive(decoy.image), 5), "подставной процесс пережил снятие"
        assert _wait(lambda: not _alive(decoy.child), 5), "дочерний процесс пережил снятие (/T)"
        assert subprocess.run(check_cmd, capture_output=True).returncode != 0
    finally:
        decoy.cleanup()


def _makensis():
    base = os.environ.get("LOCALAPPDATA")
    exe = Path(base) / "tauri" / "NSIS" / "makensis.exe" if base else None
    return exe if exe and exe.is_file() else None


@_windows_only
def test_macro_built_by_makensis_kills_decoy(tmp_path):
    """Макрос целиком (разбор строк NSIS, $SYSDIR, nsExec), собранный makensis комплекта Tauri
    в учебный установщик: при живом подставном процессе установщик доходит до конца, дерево снято.

    При поломке макрос уходит в `_stuck`: пишет `.update-blocked` в профиль и показывает окно –
    проба ждёт не дольше 60 с и снимает учебный установщик вместе с окном."""
    makensis = _makensis()
    if makensis is None:
        pytest.skip("makensis из комплекта Tauri не найден (%LOCALAPPDATA%\\tauri\\NSIS)")
    decoy = _Decoy(tmp_path)
    reached = tmp_path / "reached_end.txt"
    nsi = tmp_path / "probe.nsi"
    nsi.write_text(
        "Unicode true\nRequestExecutionLevel user\nSilentInstall silent\n"
        f'Name "hook probe"\nOutFile "{tmp_path / "probe.exe"}"\n'
        f'!include "{_HOOK}"\nInstallDir "$TEMP\\aurora-hook-probe"\n'
        "Section\n"
        f'  !insertmacro {_KILL_MACRO} "{decoy.image}" t1\n'
        f'  FileOpen $0 "{reached}" w\n  FileWrite $0 "gone"\n  FileClose $0\n'
        "SectionEnd\n", encoding="utf-8-sig")
    built = subprocess.run([str(makensis), "/V2", str(nsi)], capture_output=True)
    assert built.returncode == 0, built.stdout.decode("utf-8", "replace")[-2000:]
    probe = None
    try:
        decoy.start()
        probe = subprocess.Popen([str(tmp_path / "probe.exe"), "/S"])
        try:
            probe.wait(timeout=60)
        except subprocess.TimeoutExpired:
            pass
        assert reached.exists(), "макрос не дошёл до конца: подставной процесс не снят (ушёл в _stuck)"
        assert not _alive(decoy.image) and not _alive(decoy.child), "дерево подставного процесса живо"
    finally:
        if probe is not None and probe.poll() is None:
            subprocess.run(f"taskkill /PID {probe.pid} /T /F", capture_output=True)
        decoy.cleanup()


def main():
    fails = check(_hook_text())
    if fails:
        for f in fails:
            print("FAIL:", f)
        print(f"ИТОГ: провалов {len(fails)}")
        return 1
    print(f"OK: {_KILL_MACRO} – снятие без сочетания /T и /FI USERNAME, дерево по PID своей учётной записи, "
          f"проверка живости без фильтра через $SYSDIR\\find.exe; вставлен в {', '.join(_HOOKS)} для обоих образов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
