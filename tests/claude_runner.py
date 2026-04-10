"""
Claude CLI runner — replicates how the Tauri app invokes Claude.

Mirrors the logic from src-tauri/src/commands/claude.rs:
  1. Sets up a temporary workspace
  2. Copies CLAUDE.md + .claude/commands/ + inbox files
  3. Runs: claude -p "/{command}" --print --output-format stream-json --dangerously-skip-permissions
  4. Parses stream-json output, collects full text
  5. Returns RunResult(text, exit_code, duration_sec, raw_chunks)
  6. Cleans up workspace
"""
import json
import platform
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# On Windows, claude is a .cmd script — subprocess needs shell=True to find it
_IS_WINDOWS = platform.system() == "Windows"

import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import CABINETS_ROOT, CLAUDE_TIMEOUT_SECONDS, CACHE_DIR


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    text: str
    exit_code: int
    duration_sec: float
    cabinet_id: str
    command: str
    error: Optional[str] = None
    raw_chunks: list = field(default_factory=list)

    @property
    def passed_basic(self) -> bool:
        return self.exit_code == 0 and len(self.text) > 0

    @property
    def char_count(self) -> int:
        return len(self.text)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_key(cabinet_id: str, command: str, inbox_files: list[Path]) -> str:
    """Build a hash key from cabinet + command + inbox file contents."""
    import hashlib
    h = hashlib.sha256()
    h.update(cabinet_id.encode())
    h.update(command.encode())
    for f in sorted(inbox_files):
        if f.exists():
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _load_cache(key: str) -> Optional[RunResult]:
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return RunResult(**data)
    except Exception:
        return None


def _save_cache(key: str, result: RunResult) -> None:
    p = _cache_path(key)
    data = {
        "text": result.text,
        "exit_code": result.exit_code,
        "duration_sec": result.duration_sec,
        "cabinet_id": result.cabinet_id,
        "command": result.command,
        "error": result.error,
        "raw_chunks": [],  # don't cache raw chunks
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Stream-JSON parser
# ---------------------------------------------------------------------------

def _parse_stream_json(stdout: str) -> tuple[str, list]:
    """
    Parse Claude CLI --output-format stream-json output.

    Each line is a JSON object. We collect text from:
      {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "..."}}

    Returns (full_text, raw_chunks).
    """
    chunks = []
    text_parts = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            chunks.append(obj)
            # Format 1: streaming chunks (normal operation)
            if obj.get("type") == "content_block_delta":
                delta = obj.get("delta", {})
                if delta.get("type") == "text_delta":
                    text_parts.append(delta.get("text", ""))
            # Format 2: assistant message with content array (errors, short responses)
            elif obj.get("type") == "assistant":
                msg = obj.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
            # Format 3: result line with error message
            elif obj.get("type") == "result" and obj.get("is_error"):
                err_text = obj.get("result", "")
                if err_text and not text_parts:
                    text_parts.append(err_text)
        except json.JSONDecodeError:
            # Might be a partial line or non-JSON progress line — skip
            pass
    return "".join(text_parts), chunks


# ---------------------------------------------------------------------------
# Workspace setup
# ---------------------------------------------------------------------------

def _setup_workspace(
    cabinet_id: str,
    inbox_files: list[Path],
    workspace: Path,
) -> None:
    """
    Populate the temp workspace:
      workspace/
        CLAUDE.md
        .claude/commands/*.md
        inbox/<files>
    """
    cabinet_dir = CABINETS_ROOT / cabinet_id

    # Copy CLAUDE.md
    src_claude = cabinet_dir / "CLAUDE.md"
    if src_claude.exists():
        shutil.copy2(src_claude, workspace / "CLAUDE.md")

    # Copy .claude/commands/
    src_commands = cabinet_dir / ".claude" / "commands"
    if src_commands.exists():
        dst_commands = workspace / ".claude" / "commands"
        shutil.copytree(src_commands, dst_commands)

    # Copy inbox files
    if inbox_files:
        inbox_dir = workspace / "inbox"
        inbox_dir.mkdir(exist_ok=True)
        for src in inbox_files:
            if src.exists():
                shutil.copy2(src, inbox_dir / src.name)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_command(
    cabinet_id: str,
    command: str,
    inbox_files: Optional[list[Path]] = None,
    use_cache: bool = False,
    verbose: bool = False,
    timeout: int = CLAUDE_TIMEOUT_SECONDS,
) -> RunResult:
    """
    Run a cabinet command via Claude CLI and return the result.

    Args:
        cabinet_id: e.g. "creative-director"
        command:    e.g. "brand-memory" (without leading slash)
        inbox_files: list of Path objects to place in workspace/inbox/
        use_cache:  if True, check cache before running, save after
        verbose:    print progress to stderr
        timeout:    seconds before giving up (default from config)

    Returns:
        RunResult with .text, .exit_code, .duration_sec
    """
    inbox_files = inbox_files or []

    # Cache check
    if use_cache:
        key = _cache_key(cabinet_id, command, inbox_files)
        cached = _load_cache(key)
        if cached:
            if verbose:
                print(f"  [CACHE HIT] {cabinet_id}/{command}", file=sys.stderr)
            return cached

    # Build workspace
    with tempfile.TemporaryDirectory(prefix="aiagency_test_") as tmpdir:
        workspace = Path(tmpdir)
        _setup_workspace(cabinet_id, inbox_files, workspace)

        if verbose:
            print(f"  [RUN] claude -p '/{command}' in {cabinet_id}", file=sys.stderr)

        cmd = [
            "claude",
            "-p", f"/{command}",
            "--print",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ]

        start = time.time()
        # On Windows shell=True requires a string, not a list
        run_cmd = " ".join(f'"{c}"' if " " in c else c for c in cmd) if _IS_WINDOWS else cmd
        try:
            proc = subprocess.run(
                run_cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=_IS_WINDOWS,
            )
            duration = time.time() - start
            full_text, chunks = _parse_stream_json(proc.stdout)

            # Fallback: if stream-json parse gives nothing, try raw stdout
            if not full_text and proc.stdout.strip():
                full_text = proc.stdout.strip()

            result = RunResult(
                text=full_text,
                exit_code=proc.returncode,
                duration_sec=round(duration, 1),
                cabinet_id=cabinet_id,
                command=command,
                error=proc.stderr.strip() if proc.returncode != 0 else None,
                raw_chunks=chunks,
            )

            if verbose:
                status = "OK" if result.passed_basic else "FAIL"
                print(
                    f"  [{status}] {cabinet_id}/{command} "
                    f"({duration:.1f}s, {result.char_count} chars)",
                    file=sys.stderr,
                )

        except subprocess.TimeoutExpired:
            duration = time.time() - start
            result = RunResult(
                text="",
                exit_code=-1,
                duration_sec=round(duration, 1),
                cabinet_id=cabinet_id,
                command=command,
                error=f"Timeout after {timeout}s",
            )
            if verbose:
                print(f"  [TIMEOUT] {cabinet_id}/{command}", file=sys.stderr)

        except FileNotFoundError:
            result = RunResult(
                text="",
                exit_code=-2,
                duration_sec=0.0,
                cabinet_id=cabinet_id,
                command=command,
                error="claude CLI not found — is it installed and in PATH?",
            )

    # Save cache
    if use_cache:
        _save_cache(key, result)

    return result


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_commands(
    cabinet_id: str,
    commands: list[str],
    inbox_files: Optional[list[Path]] = None,
    use_cache: bool = False,
    verbose: bool = True,
    timeout: int = CLAUDE_TIMEOUT_SECONDS,
) -> list[RunResult]:
    """Run multiple commands for a cabinet sequentially."""
    return [
        run_command(cabinet_id, cmd, inbox_files, use_cache, verbose, timeout)
        for cmd in commands
    ]


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run a single cabinet command via Claude CLI")
    parser.add_argument("cabinet", help="Cabinet ID, e.g. creative-director")
    parser.add_argument("command", help="Command name without slash, e.g. brand-memory")
    parser.add_argument("--inbox", nargs="*", help="Inbox file paths")
    parser.add_argument("--cache", action="store_true", help="Use result cache")
    parser.add_argument("--timeout", type=int, default=CLAUDE_TIMEOUT_SECONDS)
    args = parser.parse_args()

    inbox = [Path(f) for f in (args.inbox or [])]
    result = run_command(args.cabinet, args.command, inbox, args.cache, verbose=True, timeout=args.timeout)

    print(f"\n{'='*60}")
    print(f"Cabinet:  {result.cabinet_id}")
    print(f"Command:  /{result.command}")
    print(f"Exit:     {result.exit_code}")
    print(f"Duration: {result.duration_sec}s")
    print(f"Length:   {result.char_count} chars")
    if result.error:
        print(f"Error:    {result.error}")
    print(f"{'='*60}\n")
    print(result.text[:2000] if result.text else "(empty output)")
    if len(result.text) > 2000:
        print(f"\n... [{result.char_count - 2000} more chars]")
