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

Запуск: `python tools/test_installer_hooks.py` (стандартная библиотека) или через pytest.
Выход 0 = все зелёные; иначе список провалов, код 1.
"""
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HOOK = _ROOT / "src-tauri" / "installer_hooks.nsh"
_KILL_MACRO = "AURORA_KILL_AND_WAIT"
_HOOKS = ("NSIS_HOOK_PREINSTALL", "NSIS_HOOK_PREUNINSTALL")
_IMAGES = ("econometrica-sidecar.exe", "aurora-econometrica-gui.exe")
_USER_FILTER = re.compile(r'/FI\s+"USERNAME eq %USERNAME%"', re.I)


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
    if not checks:
        fails.append(f"{_KILL_MACRO}: нет проверки живости через tasklist | find")
    for ln in checks:
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
