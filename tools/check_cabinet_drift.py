"""Cabinet Drift Guard — страж рассинхронизации кабинета econometrist.

Кабинет `New_AI_Agency/econometrist/` (CLAUDE.md + LEGACY_COMMANDS.md +
.claude/commands/*.md) исторически копировался руками в 11 репозиториев/
worktree под `Dev/*` — единого механизма синхронизации не было, и правки
в одну копию молча не долетали до остальных.

Решение (аудит 2026-07): SSOT продукта = `Aurora_Econometrica` (и его git
worktree `Aurora_Econometrica_avrora` — должны совпадать байт-в-байт после
мержа веток). Остальные 8 копий живут в hub-приложениях (AI_APP_AGENCY,
Aurora_Creative_Hub, Aurora_PR_Master, ROSST_AI_Creative, ROSST_AI_DocMaster,
ROSST_AI_Legal, ROSST_AI_Legal_commercial, ROSST_AI_Media) — у каждой своя
легитимная редакция промпта (см. блок «ЖЁСТКИЙ SCOPE» внутри CLAUDE.md,
привязка к конкретному hub-продукту). Эти копии НЕ унифицируются со SSOT —
скрипт только показывает их состояние (матрица), чтобы расхождение было
видно, а не обнаруживалось постфактум багрепортом.

Режимы:
    python tools/check_cabinet_drift.py                 # человекочитаемо
    python tools/check_cabinet_drift.py --strict-pair    # + exit 1 при
                                                           # расхождении SSOT-пары
    python tools/check_cabinet_drift.py --json            # машиночитаемо
    python tools/check_cabinet_drift.py --json --strict-pair

Сравнение файлов нормализует переводы строк (CRLF -> LF) — правки часто
приходят с Windows-редакторов, и голый byte-diff тонул бы в шуме line-ending,
а не в содержательном расхождении.

Как добавить новую копию кабинета в матрицу: дописать путь (относительно
`Dev/`) в список `KNOWN_HUB_COPIES` ниже. Копия, для которой путь не
существует на диске (в т.ч. битый symlink), отображается как "нет" —
это не ошибка запуска.

`--strict-pair` в linked worktree (например, `Aurora_Econometrica_avrora`
до мержа в основной репозиторий) НЕ проваливает коммит: pre-commit там
завалил бы первую же правку кабинета на ветке, где расхождение с SSOT
легитимно по определению. Строгий exit 1 действует только в основном
дереве, где расхождение уже некуда списывать на "ещё не смёржено".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

CABINET_REL = Path("New_AI_Agency") / "econometrist"

# Dev/ — общий родитель для SSOT-репо и worktree, и для всех hub-копий.
DEV_ROOT = Path(__file__).resolve().parents[2]

# SSOT-пара: продукт-репозиторий и его git worktree. Могут легитимно
# разойтись, пока worktree на отдельной ветке — не смёржено в SSOT.
SSOT_REPO = "Aurora_Econometrica"
SSOT_WORKTREE = "Aurora_Econometrica_avrora"

# Hub-копии со своей легитимной SCOPE-редакцией промпта — наблюдаем,
# не унифицируем.
KNOWN_HUB_COPIES = [
    "AI_APP_AGENCY",
    "Aurora_Creative_Hub",
    "Aurora_PR_Master",
    "ROSST_AI_Creative",
    "ROSST_AI_DocMaster",
    "ROSST_AI_Legal",
    "ROSST_AI_Legal_commercial",
    "ROSST_AI_Media",
]


def is_linked_worktree(cwd: Path | None = None) -> bool:
    """True, если запуск идёт из linked git worktree (не основного дерева репо).

    Основной сигнал: `--git-dir` != `--git-common-dir` — для основного дерева
    оба указывают на один и тот же `.git`, для linked worktree `--git-dir`
    смотрит в `<основной .git>/worktrees/<имя>`, а `--git-common-dir` — на
    общий `.git`. Дублируем проверкой подстроки "worktrees" в `--git-dir` —
    если сравнение путей когда-нибудь даст ложноотрицательный результат
    (например, из-за регистра букв на Windows), эта проверка подстрахует.
    При любой ошибке git (не репозиторий, git недоступен и т.п.) — считаем
    "не worktree", чтобы не заблокировать хук там, где решение неочевидно.
    """
    try:
        git_dir = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd, capture_output=True, text=True, check=True,
        ).stdout.strip()
        common_dir = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=cwd, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False

    git_dir_abs = Path(git_dir).resolve()
    common_dir_abs = Path(common_dir).resolve()
    if git_dir_abs != common_dir_abs:
        return True
    return "worktrees" in Path(git_dir).as_posix()


def _normalize(data: bytes) -> bytes:
    """CRLF -> LF, чтобы line-ending не маскировался под содержательный дрейф."""
    return data.replace(b"\r\n", b"\n")


def _cabinet_dir(repo_name: str) -> Path:
    return DEV_ROOT / repo_name / CABINET_REL


def _iter_cabinet_files(cabinet_dir: Path) -> list[Path]:
    if not cabinet_dir.is_dir():
        return []
    return sorted(p for p in cabinet_dir.rglob("*") if p.is_file())


@dataclass
class RepoSnapshot:
    """Состояние кабинета в одном репозитории на момент запуска."""

    repo_name: str
    exists: bool = False
    file_count: int = 0
    folder_hash: str | None = None  # нормализованный сводный SHA-256
    newest_mtime: float | None = None
    rel_files: dict[str, str] = field(default_factory=dict)  # rel_path -> file SHA-256

    @classmethod
    def capture(cls, repo_name: str) -> "RepoSnapshot":
        cabinet_dir = _cabinet_dir(repo_name)
        files = _iter_cabinet_files(cabinet_dir)
        if not files:
            return cls(repo_name=repo_name, exists=cabinet_dir.is_dir())

        rel_files: dict[str, str] = {}
        newest_mtime = 0.0
        folder_digest = hashlib.sha256()
        # Детерминированный порядок (sorted) — сводный хэш стабилен между
        # запусками на одном и том же содержимом.
        for f in files:
            rel = f.relative_to(cabinet_dir).as_posix()
            raw = f.read_bytes()
            normalized = _normalize(raw)
            file_hash = hashlib.sha256(normalized).hexdigest()
            rel_files[rel] = file_hash
            folder_digest.update(rel.encode("utf-8"))
            folder_digest.update(b"\0")
            folder_digest.update(normalized)
            folder_digest.update(b"\0")
            newest_mtime = max(newest_mtime, f.stat().st_mtime)

        return cls(
            repo_name=repo_name,
            exists=True,
            file_count=len(files),
            folder_hash=folder_digest.hexdigest(),
            newest_mtime=newest_mtime,
            rel_files=rel_files,
        )


def diff_snapshots(a: RepoSnapshot, b: RepoSnapshot) -> list[str]:
    """Список человекочитаемых отличий между двумя снимками кабинета."""
    diffs: list[str] = []
    all_rel = sorted(set(a.rel_files) | set(b.rel_files))
    for rel in all_rel:
        in_a = rel in a.rel_files
        in_b = rel in b.rel_files
        if in_a and not in_b:
            diffs.append(f"только в {a.repo_name}: {rel}")
        elif in_b and not in_a:
            diffs.append(f"только в {b.repo_name}: {rel}")
        elif a.rel_files[rel] != b.rel_files[rel]:
            diffs.append(f"содержимое отличается: {rel}")
    return diffs


def cluster_hub_copies(snapshots: list[RepoSnapshot]) -> dict[str, str]:
    """repo_name -> метка кластера. Копии с одинаковым folder_hash — один кластер."""
    hash_to_label: dict[str, str] = {}
    result: dict[str, str] = {}
    next_id = 1
    for snap in snapshots:
        if not snap.exists or snap.folder_hash is None:
            result[snap.repo_name] = "нет"
            continue
        label = hash_to_label.get(snap.folder_hash)
        if label is None:
            label = f"кластер {next_id}"
            hash_to_label[snap.folder_hash] = label
            next_id += 1
        result[snap.repo_name] = label

    # Кластер из одного элемента — не кластер, а уникальная копия.
    counts: dict[str, int] = {}
    for label in result.values():
        if label == "нет":
            continue
        counts[label] = counts.get(label, 0) + 1
    for repo_name, label in list(result.items()):
        if label != "нет" and counts.get(label, 0) == 1:
            result[repo_name] = "уникальна"

    return result


def build_report(strict_pair: bool) -> dict:
    ssot_repo_snap = RepoSnapshot.capture(SSOT_REPO)
    ssot_worktree_snap = RepoSnapshot.capture(SSOT_WORKTREE)
    pair_diffs = diff_snapshots(ssot_repo_snap, ssot_worktree_snap)
    pair_diverged = bool(pair_diffs)

    hub_snapshots = [RepoSnapshot.capture(name) for name in KNOWN_HUB_COPIES]
    clusters = cluster_hub_copies(hub_snapshots)

    hub_rows = []
    for snap in hub_snapshots:
        hub_rows.append(
            {
                "repo": snap.repo_name,
                "exists": snap.exists,
                "file_count": snap.file_count if snap.exists else None,
                "folder_hash": snap.folder_hash,
                "newest_mtime": snap.newest_mtime,
                "cluster": clusters[snap.repo_name],
            }
        )

    return {
        "ssot_pair": {
            "repo": SSOT_REPO,
            "worktree": SSOT_WORKTREE,
            "repo_exists": ssot_repo_snap.exists,
            "worktree_exists": ssot_worktree_snap.exists,
            "diverged": pair_diverged,
            "diffs": pair_diffs,
            "strict": strict_pair,
        },
        "hub_copies": hub_rows,
    }


def _fmt_mtime(mtime: float | None) -> str:
    if mtime is None:
        return "—"
    import datetime

    return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")


def print_human_report(report: dict) -> None:
    pair = report["ssot_pair"]
    print("=== SSOT-пара (Aurora_Econometrica <-> Aurora_Econometrica_avrora) ===")
    if not pair["repo_exists"] or not pair["worktree_exists"]:
        missing = []
        if not pair["repo_exists"]:
            missing.append(pair["repo"])
        if not pair["worktree_exists"]:
            missing.append(pair["worktree"])
        print(f"  Отсутствует: {', '.join(missing)}")
    elif not pair["diverged"]:
        print("  Идентичны (после нормализации CRLF->LF). ОК.")
    else:
        prefix = "РАСХОЖДЕНИЕ (--strict-pair)" if pair["strict"] else "расхождение веток: сверь после мержа"
        print(f"  {prefix}:")
        for d in pair["diffs"]:
            print(f"    - {d}")

    print()
    print("=== Hub-копии (информационно, свои легитимные SCOPE-редакции) ===")
    header = f"{'репозиторий':<26} {'файлов':>7}  {'свежайший файл':<17} {'хэш папки':<12} кластер"
    print(header)
    print("-" * len(header))
    for row in report["hub_copies"]:
        if not row["exists"]:
            print(f"{row['repo']:<26} {'—':>7}  {'—':<17} {'—':<12} нет")
            continue
        short_hash = row["folder_hash"][:10] if row["folder_hash"] else "—"
        print(
            f"{row['repo']:<26} {row['file_count']:>7}  "
            f"{_fmt_mtime(row['newest_mtime']):<17} {short_hash:<12} {row['cluster']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--strict-pair",
        action="store_true",
        help="exit 1 если SSOT-пара (repo/worktree) расходится — только в основном "
        "git-дереве. В linked worktree строгая проверка откладывается до мержа "
        "(расхождение легитимно), отчёт остаётся информационным.",
    )
    parser.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    args = parser.parse_args()

    # В linked worktree (наш случай — Aurora_Econometrica_avrora на отдельной
    # ветке) --strict-pair не должен заваливать pre-commit: расхождение с SSOT
    # там легитимно, пока ветка не смёржена. Строгий гейт имеет смысл только
    # в основном дереве, где "ещё не смёржено" уже не оправдание.
    # cwd не передаём: git сам берёт текущую рабочую директорию процесса —
    # то есть корень репозитория, из которого lefthook реально запустил хук.
    deferred_strict = args.strict_pair and is_linked_worktree()
    effective_strict = args.strict_pair and not deferred_strict

    report = build_report(strict_pair=effective_strict)

    if deferred_strict and not args.json:
        print("linked worktree: строгая проверка пары отложена до мержа (информационно ниже)")
        print()

    if args.json:
        if deferred_strict:
            report["ssot_pair"]["strict_deferred_worktree"] = True
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human_report(report)

    if effective_strict and report["ssot_pair"]["diverged"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
