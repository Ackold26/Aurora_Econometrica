"""
Report generator — console summary + markdown file output.
"""
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class TestResult:
    level: str            # "structural" | "integration"
    cabinet_id: str
    test_name: str
    passed: bool
    message: str
    duration_sec: float
    command: Optional[str] = None      # For integration tests
    char_count: Optional[int] = None   # For integration tests
    warnings: list[str] = field(default_factory=list)


class ReportGenerator:
    def __init__(self):
        self._results: list[TestResult] = []
        self._start_time: float = time.time()

    def add(self, result: TestResult) -> None:
        self._results.append(result)

    def has_failures(self) -> bool:
        return any(not r.passed for r in self._results)

    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------

    def print_summary(self, elapsed_sec: float = 0.0) -> None:
        structural = [r for r in self._results if r.level == "structural"]
        integration = [r for r in self._results if r.level == "integration"]

        s_pass = sum(1 for r in structural if r.passed)
        s_fail = sum(1 for r in structural if not r.passed)
        i_pass = sum(1 for r in integration if r.passed)
        i_fail = sum(1 for r in integration if not r.passed)

        total_pass = s_pass + i_pass
        total_fail = s_fail + i_fail
        total = total_pass + total_fail

        print(f"\n{'='*60}")
        print(f"  SUMMARY  |  {total} tests  |  {total_pass} pass  |  {total_fail} fail")
        if elapsed_sec:
            print(f"  Time: {elapsed_sec:.1f}s")
        print(f"{'='*60}")

        if structural:
            print(f"\n  Structural: {s_pass}/{s_pass+s_fail} pass")
        if integration:
            print(f"  Integration: {i_pass}/{i_pass+i_fail} pass")

        # List failures
        failures = [r for r in self._results if not r.passed]
        if failures:
            print(f"\n  FAILURES ({len(failures)}):")
            for r in failures:
                cmd_label = f" /{r.command}" if r.command else ""
                print(f"    [FAIL] {r.cabinet_id}{cmd_label} :: {r.test_name}")
                print(f"           {r.message}")

        print()

    # ------------------------------------------------------------------
    # Markdown report
    # ------------------------------------------------------------------

    def save_markdown(self, path: Path, elapsed_sec: float = 0.0) -> None:
        from datetime import datetime, timezone, timedelta
        msk = timezone(timedelta(hours=3))
        now = datetime.now(msk).strftime("%Y-%m-%d %H:%M МСК")

        structural = [r for r in self._results if r.level == "structural"]
        integration = [r for r in self._results if r.level == "integration"]

        s_pass = sum(1 for r in structural if r.passed)
        s_fail = len(structural) - s_pass
        i_pass = sum(1 for r in integration if r.passed)
        i_fail = len(integration) - i_pass
        total_pass = s_pass + i_pass
        total_fail = s_fail + i_fail

        lines = [
            "# AI Agency Test Report",
            f"\n**Date:** {now}  ",
            f"**Total:** {total_pass + total_fail} tests | **{total_pass} pass** | **{total_fail} fail**",
        ]
        if elapsed_sec:
            lines.append(f"**Duration:** {elapsed_sec:.1f}s")

        # Structural section
        if structural:
            lines.append("\n---\n")
            lines.append(f"## Structural Tests — {s_pass}/{len(structural)} pass\n")
            lines.append("| Cabinet | Test | Status | Message |")
            lines.append("|---------|------|--------|---------|")
            for r in structural:
                icon = "✅" if r.passed else "❌"
                lines.append(f"| {r.cabinet_id} | {r.test_name} | {icon} | {r.message[:80]} |")

        # Integration section
        if integration:
            lines.append("\n---\n")
            lines.append(f"## Integration Tests — {i_pass}/{len(integration)} pass\n")

            # Group by cabinet
            cabinets_seen = []
            by_cabinet: dict[str, list[TestResult]] = {}
            for r in integration:
                if r.cabinet_id not in by_cabinet:
                    by_cabinet[r.cabinet_id] = []
                    cabinets_seen.append(r.cabinet_id)
                by_cabinet[r.cabinet_id].append(r)

            for cabinet_id in cabinets_seen:
                cab_results = by_cabinet[cabinet_id]
                cab_pass = sum(1 for r in cab_results if r.passed)
                lines.append(f"\n### {cabinet_id} — {cab_pass}/{len(cab_results)} pass\n")
                lines.append("| Command | Status | Duration | Details |")
                lines.append("|---------|--------|----------|---------|")
                for r in cab_results:
                    icon = "✅" if r.passed else "❌"
                    cmd = f"/{r.command}" if r.command else r.test_name
                    dur = f"{r.duration_sec:.1f}s" if r.duration_sec else "—"
                    msg = r.message[:100]
                    lines.append(f"| {cmd} | {icon} | {dur} | {msg} |")
                    # Warnings
                    for w in r.warnings:
                        lines.append(f"| | ⚠️ | | {w[:100]} |")

        # Failures section
        failures = [r for r in self._results if not r.passed]
        if failures:
            lines.append("\n---\n")
            lines.append(f"## Failures ({len(failures)})\n")
            for r in failures:
                cmd_label = f" `/{r.command}`" if r.command else ""
                lines.append(f"- **{r.cabinet_id}**{cmd_label} `{r.test_name}`: {r.message}")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
