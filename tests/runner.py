"""
AI Agency Test Runner — CLI entry point.

Usage:
  python tests/runner.py                              # All tests
  python tests/runner.py --structural                  # Structural only (free, <5s)
  python tests/runner.py --smoke                       # 1 command per cabinet (~$2)
  python tests/runner.py --cabinet creative-director   # One cabinet
  python tests/runner.py --cabinet creative-director --command brand-memory
  python tests/runner.py --skip-expensive              # Skip /cycle, /strategy
  python tests/runner.py --use-cache                   # Reuse cached Claude results
  python tests/runner.py --no-integration              # Skip integration tests
"""
import argparse
import importlib
import importlib.util
import sys
import time
from pathlib import Path
from typing import Optional

# Add tests/ to path
sys.path.insert(0, str(Path(__file__).parent))

from config import CABINETS, CABINETS_ROOT, EXPONENTA_DIR, FIXTURES_DIR
from report_generator import ReportGenerator, TestResult


# ---------------------------------------------------------------------------
# Load structural test modules dynamically
# ---------------------------------------------------------------------------

def _load_structural() -> list:
    """Return list of (module_name, module) pairs for structural tests."""
    structural_dir = Path(__file__).parent / "structural"
    modules = []
    for py_file in sorted(structural_dir.glob("test_*.py")):
        spec_name = f"structural.{py_file.stem}"
        spec = importlib.util.spec_from_file_location(spec_name, py_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        modules.append((py_file.stem, mod))
    return modules


def _load_integration(cabinet_id: str) -> Optional[object]:
    """Load integration test module for a cabinet."""
    integration_dir = Path(__file__).parent / "integration"
    # Map cabinet-id to file name
    fname = f"test_{cabinet_id.replace('-', '_')}.py"
    fpath = integration_dir / fname
    if not fpath.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"integration.{fpath.stem}", fpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Run structural level
# ---------------------------------------------------------------------------

def run_structural(
    cabinets: list[str],
    report: ReportGenerator,
    verbose: bool = True,
) -> None:
    """Run all structural tests for given cabinets."""
    structural_modules = _load_structural()

    for mod_name, mod in structural_modules:
        if verbose:
            print(f"\n  [{mod_name}]")

        if not hasattr(mod, "run_all"):
            continue

        # Global tests (not per-cabinet)
        if hasattr(mod, "test_all_commands_start_with_slash_in_rust"):
            passed, msg = mod.test_all_commands_start_with_slash_in_rust()
            result = TestResult(
                level="structural",
                cabinet_id="GLOBAL",
                test_name="all_commands_start_with_slash",
                passed=passed,
                message=msg,
                duration_sec=0.0,
            )
            report.add(result)
            if verbose:
                status = "PASS" if passed else "FAIL"
                print(f"    [GLOBAL] [{status}] all_commands_start_with_slash: {msg}")

        for cabinet_id in cabinets:
            t0 = time.time()
            results = mod.run_all(cabinet_id)
            duration = time.time() - t0

            if verbose:
                print(f"    [{cabinet_id}]")

            for name, passed, msg in results:
                result = TestResult(
                    level="structural",
                    cabinet_id=cabinet_id,
                    test_name=name,
                    passed=passed,
                    message=msg,
                    duration_sec=round(duration / max(len(results), 1), 3),
                )
                report.add(result)
                if verbose:
                    status = "PASS" if passed else "FAIL"
                    print(f"      [{status}] {name}: {msg}")


# ---------------------------------------------------------------------------
# Run integration level
# ---------------------------------------------------------------------------

def run_integration(
    cabinets: list[str],
    report: ReportGenerator,
    commands_filter: Optional[list[str]] = None,
    smoke_mode: bool = False,
    skip_expensive: bool = False,
    use_cache: bool = False,
    verbose: bool = True,
    delay_sec: int = 0,
) -> None:
    """Run integration tests for given cabinets."""
    for cabinet_id in cabinets:
        mod = _load_integration(cabinet_id)
        if mod is None:
            if verbose:
                print(f"\n  [{cabinet_id}] No integration tests found (skipping)")
            continue

        if verbose:
            print(f"\n  [{cabinet_id}]")

        if not hasattr(mod, "run_all"):
            continue

        kwargs = dict(
            smoke_mode=smoke_mode,
            skip_expensive=skip_expensive,
            use_cache=use_cache,
            verbose=verbose,
            delay_sec=delay_sec,
        )
        if commands_filter:
            kwargs["commands_filter"] = commands_filter

        results: list[TestResult] = mod.run_all(cabinet_id, **kwargs)
        for r in results:
            report.add(r)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="AI Agency automated test runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--structural", action="store_true",
                        help="Run only structural tests (no Claude CLI calls)")
    parser.add_argument("--smoke", action="store_true",
                        help="Smoke mode: 1 cheap command per cabinet")
    parser.add_argument("--cabinet", metavar="ID",
                        help="Run only for this cabinet (e.g. creative-director)")
    parser.add_argument("--command", metavar="CMD",
                        help="Run only this command (requires --cabinet)")
    parser.add_argument("--skip-expensive", action="store_true",
                        help="Skip /cycle and /strategy commands")
    parser.add_argument("--use-cache", action="store_true",
                        help="Use cached Claude results")
    parser.add_argument("--no-integration", action="store_true",
                        help="Skip all integration tests")
    parser.add_argument("--no-structural", action="store_true",
                        help="Skip all structural tests")
    parser.add_argument("--verbose", "-v", action="store_true", default=True,
                        help="Verbose output (default: on)")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress per-test output")
    parser.add_argument("--report", metavar="FILE",
                        help="Save markdown report to FILE")
    parser.add_argument("--delay", type=int, default=0, metavar="SEC",
                        help="Seconds to wait between integration tests (avoids rate limits)")
    args = parser.parse_args()

    verbose = not args.quiet

    # Determine cabinet list
    if args.cabinet:
        if args.cabinet not in CABINETS:
            print(f"ERROR: Unknown cabinet '{args.cabinet}'. Known: {list(CABINETS.keys())}")
            sys.exit(1)
        cabinets = [args.cabinet]
    else:
        # Sort by test_priority
        cabinets = sorted(CABINETS.keys(), key=lambda c: CABINETS[c].get("test_priority", 9))

    commands_filter = [args.command] if args.command else None

    report = ReportGenerator()

    print("=" * 60)
    print("  AI Agency Test Runner")
    print(f"  Cabinets: {', '.join(cabinets)}")
    mode_labels = []
    if args.structural:
        mode_labels.append("structural-only")
    if args.smoke:
        mode_labels.append("smoke")
    if args.skip_expensive:
        mode_labels.append("skip-expensive")
    if args.use_cache:
        mode_labels.append("cached")
    if mode_labels:
        print(f"  Mode: {', '.join(mode_labels)}")
    print("=" * 60)

    t_start = time.time()

    # LEVEL 1: Structural
    if not args.no_structural:
        print("\n=== LEVEL 1: Structural Tests ===")
        run_structural(cabinets, report, verbose=verbose)

    # LEVEL 2: Integration
    if not args.no_integration and not args.structural:
        print("\n=== LEVEL 2: Integration Tests ===")
        run_integration(
            cabinets=cabinets,
            report=report,
            commands_filter=commands_filter,
            smoke_mode=args.smoke,
            skip_expensive=args.skip_expensive,
            use_cache=args.use_cache,
            verbose=verbose,
            delay_sec=args.delay,
        )

    # Report
    total_elapsed = time.time() - t_start
    print("\n" + "=" * 60)
    report.print_summary(elapsed_sec=total_elapsed)

    if args.report:
        report.save_markdown(Path(args.report), elapsed_sec=total_elapsed)
        print(f"\nReport saved to: {args.report}")

    # Exit code: 0 = all pass, 1 = some fail
    if report.has_failures():
        sys.exit(1)


if __name__ == "__main__":
    main()
