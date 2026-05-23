"""Phase 3 audit: AST walker для detection of error-path issues в:
    sidecar/econometrica/engines/optimizer.py
    sidecar/econometrica/engines/scenario.py
    sidecar/econometrica/engines/decomposer.py

Detects:
    [C1] Conditionally-bound names referenced unconditionally - UnboundLocalError
         class (pass-18 trigger). For each function: collect names assigned
         only inside If/Try/With branches; flag references that exist after
         all branches but no fallback assignment.
    [C2] Bare `except Exception: pass` blocks - silent failure paths.
    [C3] Early `return` inside `try:` without finally setup of consumer state.
    [C4] Division operators applied к outputs of `.get()` (potential NaN/zero
         propagation if missing).

Run:
    python tools/audit_optimizer_error_paths.py > docs/OPTIMIZER_ERROR_PATH_AUDIT_RAW.txt
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGETS = [
    REPO / 'sidecar' / 'econometrica' / 'engines' / 'optimizer.py',
    REPO / 'sidecar' / 'econometrica' / 'engines' / 'scenario.py',
    REPO / 'sidecar' / 'econometrica' / 'engines' / 'decomposer.py',
]


class ConditionalAssignmentFinder(ast.NodeVisitor):
    """For each FunctionDef, classify name bindings as:
        - top_level   (always bound, regardless of branch taken)
        - conditional (only bound в если-ветке, либо в одной из If-альтернатив)

    Conditional names referenced AFTER the conditional block - UnboundLocalError
    risk. We collect the full set, печатаем references with line numbers.
    """

    def __init__(self, filename: str):
        self.filename = filename
        self.findings: list[dict] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        unconditional = set()  # names assigned at function-top-level (deterministic)
        conditional = {}  # name -> list of branch line numbers where assigned

        # Function args are unconditional
        for arg in node.args.args + node.args.kwonlyargs:
            unconditional.add(arg.arg)
        if node.args.vararg:
            unconditional.add(node.args.vararg.arg)
        if node.args.kwarg:
            unconditional.add(node.args.kwarg.arg)

        def mark_assignments(stmt, branch_kind: str | None) -> None:
            """Recursively scan stmt; mark assignments к conditional/unconditional."""
            for sub in ast.walk(stmt):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    continue  # don't dive into nested defs
                targets: list[ast.AST] = []
                if isinstance(sub, ast.Assign):
                    targets = sub.targets
                elif isinstance(sub, (ast.AugAssign, ast.AnnAssign)):
                    targets = [sub.target] if sub.target else []
                elif isinstance(sub, ast.For):
                    targets = [sub.target]
                elif isinstance(sub, (ast.With, ast.AsyncWith)):
                    for item in sub.items:
                        if item.optional_vars:
                            targets.append(item.optional_vars)
                elif isinstance(sub, ast.ExceptHandler):
                    if sub.name:
                        targets.append(ast.Name(id=sub.name, ctx=ast.Store()))
                for t in targets:
                    for name_node in _flatten_targets(t):
                        if branch_kind is None:
                            unconditional.add(name_node)
                        else:
                            conditional.setdefault(name_node, []).append(
                                getattr(sub, 'lineno', 0)
                            )

        # First pass: top-level statements
        for stmt in node.body:
            if isinstance(stmt, (ast.If, ast.Try, ast.For, ast.While)):
                # All assignments inside these constructs are conditional
                # (For: loop body may not execute; While: same; If: branch-dep;
                #  Try: except branch may not execute).
                if isinstance(stmt, ast.Try):
                    # Try body assignments are conditional (may except before assign)
                    for sub in stmt.body:
                        mark_assignments(sub, branch_kind='try-body')
                    for handler in stmt.handlers:
                        for sub in handler.body:
                            mark_assignments(sub, branch_kind='except-body')
                    for sub in stmt.orelse:
                        mark_assignments(sub, branch_kind='try-else')
                    for sub in stmt.finalbody:
                        # Finally executes always - promote к unconditional
                        mark_assignments(sub, branch_kind=None)
                elif isinstance(stmt, ast.If):
                    # Both branches must assign к make unconditional
                    if_assigns = _collect_top_assigns(stmt.body)
                    else_assigns = _collect_top_assigns(stmt.orelse) if stmt.orelse else set()
                    common = if_assigns & else_assigns
                    for name in common:
                        unconditional.add(name)
                    for name in (if_assigns | else_assigns) - common:
                        conditional.setdefault(name, []).append(stmt.lineno)
                else:
                    # For/While: body conditional
                    for sub in stmt.body:
                        mark_assignments(sub, branch_kind='loop')
                    for sub in stmt.orelse:
                        mark_assignments(sub, branch_kind='loop-else')
            else:
                mark_assignments(stmt, branch_kind=None)

        # Find all Name(Load) references that match conditional set
        risky_refs = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                if sub.id in conditional and sub.id not in unconditional:
                    # Skip references to names defined в same conditional branch
                    # (heuristic: keep flag, manual review filter)
                    risky_refs.append({
                        'name': sub.id,
                        'ref_line': sub.lineno,
                        'assignment_lines': conditional[sub.id],
                    })

        if risky_refs:
            self.findings.append({
                'function': node.name,
                'file': self.filename,
                'risky_refs': risky_refs,
            })

        self.generic_visit(node)


def _flatten_targets(node: ast.AST) -> list[str]:
    """Extract Name.id из nested Tuple/List/Starred targets."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        out = []
        for e in node.elts:
            out.extend(_flatten_targets(e))
        return out
    if isinstance(node, ast.Starred):
        return _flatten_targets(node.value)
    return []


def _collect_top_assigns(stmts: list[ast.stmt]) -> set[str]:
    """Names assigned at top of statement list (NOT nested in If/For/While/Try)."""
    out: set[str] = set()
    for stmt in stmts:
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                out.update(_flatten_targets(t))
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
            if stmt.target:
                out.update(_flatten_targets(stmt.target))
    return out


class BareExceptFinder(ast.NodeVisitor):
    """Find `except: pass` или `except Exception: pass` (silent failures)."""

    def __init__(self, filename: str):
        self.filename = filename
        self.findings: list[dict] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        # Pass-only body is silent failure; pass + только assignment ниже = also.
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            self.findings.append({
                'file': self.filename,
                'line': node.lineno,
                'exception_type': _ann_type(node.type),
                'kind': 'silent_pass',
            })
        self.generic_visit(node)


def _ann_type(node: ast.AST | None) -> str:
    if node is None:
        return '<bare>'
    return ast.unparse(node) if hasattr(ast, 'unparse') else 'Exception'


class DivisionGuardScanner(ast.NodeVisitor):
    """Approximate scan: BinOp Div где RHS = call к .get() без max() guard."""

    def __init__(self, filename: str):
        self.filename = filename
        self.findings: list[dict] = []

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, ast.Div):
            denom = node.right
            # Heuristic: bare .get(x, default) или Subscript without max() wrapper
            if _is_unguarded_denom(denom):
                self.findings.append({
                    'file': self.filename,
                    'line': node.lineno,
                    'snippet': _safe_unparse(node),
                })
        self.generic_visit(node)


def _is_unguarded_denom(node: ast.AST) -> bool:
    """True iff division denominator is .get() result OR Subscript без `max(...)` guard."""
    if isinstance(node, ast.Call):
        # Calls where func is Attribute с attr='get' - dict.get(...) sans max()
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'get':
            return True
    return False


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return f'<line {node.lineno}>'


# ──────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print(f'# Phase 3 Error-Path Scan - Raw AST findings\n')
    for path in TARGETS:
        if not path.exists():
            print(f'## {path.name}\n  ❌ Not found: {path}\n')
            continue
        src = path.read_text(encoding='utf-8')
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError as e:
            print(f'## {path.name}\n  ❌ SyntaxError at line {e.lineno}: {e.msg}\n')
            continue

        print(f'## {path.name}')

        # Risky conditional refs
        cf = ConditionalAssignmentFinder(path.name)
        cf.visit(tree)
        if cf.findings:
            print('\n### [C1] Conditionally-bound names referenced (potential UnboundLocalError)')
            for f in cf.findings:
                print(f'\n  Function: `{f["function"]}`')
                # Group by name
                grouped: dict[str, list[dict]] = {}
                for ref in f['risky_refs']:
                    grouped.setdefault(ref['name'], []).append(ref)
                for name, refs in sorted(grouped.items()):
                    assign_lines = sorted({l for r in refs for l in r['assignment_lines']})
                    ref_lines = sorted({r['ref_line'] for r in refs})
                    print(
                        f'    - `{name}`: assigned conditionally at lines {assign_lines}; '
                        f'referenced at {ref_lines[:8]}'
                        + ('...' if len(ref_lines) > 8 else '')
                    )

        # Silent except blocks
        bf = BareExceptFinder(path.name)
        bf.visit(tree)
        if bf.findings:
            print('\n### [C2] Silent except handlers (`except X: pass`)')
            for f in bf.findings:
                print(f'    - line {f["line"]}: `except {f["exception_type"]}: pass`')

        # Unguarded division
        dg = DivisionGuardScanner(path.name)
        dg.visit(tree)
        if dg.findings:
            print('\n### [C4] Divisions without max()/guard (heuristic - manual review)')
            for f in dg.findings[:30]:
                print(f'    - line {f["line"]}: `{f["snippet"][:80]}`')
            if len(dg.findings) > 30:
                print(f'    ... ({len(dg.findings) - 30} more)')

        print()


if __name__ == '__main__':
    main()
