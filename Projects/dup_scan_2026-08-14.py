#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Замер дублирования Rust-ядра (src-tauri/src/**/*.rs) по линейке Aurora AI.
Только чтение. Считает sha256 каждого файла, строки, группирует по (относительный путь),
внутри группы — по хешу. Определяет идентичные / почти идентичные / уникальные файлы.
"""
import hashlib
import json
import os
from collections import defaultdict

ROOT = r"D:\Docs\Aurora_Ai\Dev"

PRODUCTS = {
    "Econometrica": r"Aurora_Econometrica_thinwt",
    "Legal": r"_wt_legal_master",
    "CreativeHub": r"Aurora_Creative_Hub",
    "Oracle": r"_wt_oracle_gwsign",
    "DocsLab": r"ROSST_AI_DocMaster",
    "SmartAnalytica": r"ROSST_AI_Media",
    "PRStudio": r"Aurora_PR_Master",
    "AIAgency": r"AI_APP_AGENCY",
    "MediaRadar": r"Aurora_Parser",
}

def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()

def count_lines(path):
    with open(path, "rb") as f:
        return f.read().count(b"\n") + 1

def collect():
    # data[product][relpath] = {"abs":..., "sha":..., "lines":...}
    data = {}
    for prod, dirname in PRODUCTS.items():
        base = os.path.join(ROOT, dirname, "src-tauri", "src")
        files = {}
        for dirpath, _, filenames in os.walk(base):
            for fn in filenames:
                if fn.endswith(".rs"):
                    absf = os.path.join(dirpath, fn)
                    rel = os.path.relpath(absf, base).replace("\\", "/")
                    try:
                        sha = sha256_of(absf)
                        lines = count_lines(absf)
                    except Exception as e:
                        sha = None
                        lines = None
                    files[rel] = {"abs": absf, "sha": sha, "lines": lines}
        data[prod] = files
    return data

def main():
    data = collect()

    # all relative paths seen anywhere
    all_paths = set()
    for prod, files in data.items():
        all_paths |= set(files.keys())

    # per-path: which products have it, and hash groups
    identical_report = []  # rows: path, n_copies, lines, cost, products
    near_report = []       # rows for paths present in >=2 products but not all same hash
    unique_report = []     # path present in exactly 1 product

    for path in sorted(all_paths):
        present = {prod: data[prod][path] for prod in PRODUCTS if path in data[prod]}
        n = len(present)
        if n == 1:
            prod = list(present.keys())[0]
            unique_report.append({
                "path": path, "product": prod, "lines": present[prod]["lines"]
            })
            continue

        # group by hash: any group with >=2 members is an "identical" entry
        # in its own right (byte-for-byte match across those specific products),
        # regardless of whether OTHER products holding the same path diverge.
        by_hash = defaultdict(list)
        for prod, info in present.items():
            by_hash[info["sha"]].append(prod)

        multi_groups = {h: prods for h, prods in by_hash.items() if len(prods) >= 2}
        singleton_groups = {h: prods for h, prods in by_hash.items() if len(prods) == 1}

        for sha, prods in multi_groups.items():
            lines = present[prods[0]]["lines"]
            cost = lines * (len(prods) - 1)
            identical_report.append({
                "path": path, "n_copies": len(prods), "products": sorted(prods),
                "lines": lines, "cost": cost
            })

        if singleton_groups:
            # diff each singleton against the LARGEST group present for this path
            # (majority variant = most common byte-content among products that have this path)
            baseline_hash, baseline_prods = max(by_hash.items(), key=lambda kv: len(kv[1]))
            baseline_prod = baseline_prods[0]
            baseline_path = present[baseline_prod]["abs"]
            with open(baseline_path, "r", encoding="utf-8", errors="replace") as f:
                baseline_lines = f.readlines()
            variants = []
            for sha, prods in singleton_groups.items():
                prod = prods[0]
                info = present[prod]
                with open(info["abs"], "r", encoding="utf-8", errors="replace") as f:
                    v_lines = f.readlines()
                import difflib
                sm = difflib.SequenceMatcher(a=baseline_lines, b=v_lines, autojunk=False)
                diff_lines = 0
                for tag, i1, i2, j1, j2 in sm.get_opcodes():
                    if tag != "equal":
                        diff_lines += max(i2 - i1, j2 - j1)
                variants.append({
                    "product": prod, "lines": info["lines"], "diff_lines": diff_lines
                })
            if variants:
                near_report.append({
                    "path": path,
                    "n_products": n,
                    "majority_products": sorted(baseline_prods),
                    "majority_lines": len(baseline_lines),
                    "variants": variants,
                })

    identical_report.sort(key=lambda r: r["cost"], reverse=True)
    near_report.sort(key=lambda r: r["n_products"], reverse=True)
    unique_report.sort(key=lambda r: (r["product"], r["path"]))

    total_identical_files = len(identical_report)
    total_identical_lines_all_copies = sum(r["lines"] * r["n_copies"] for r in identical_report)
    total_cost = sum(r["cost"] for r in identical_report)
    core_ge3 = [r for r in identical_report if r["n_copies"] >= 3]
    core_ge3_files = len(core_ge3)
    core_ge3_lines = sum(r["lines"] for r in core_ge3)  # lines in one copy
    core_ge3_cost = sum(r["cost"] for r in core_ge3)

    out = {
        "products_scanned": {k: v for k, v in PRODUCTS.items()},
        "file_counts_per_product": {p: len(f) for p, f in data.items()},
        "identical_files": identical_report,
        "near_identical_files": near_report,
        "unique_files": unique_report,
        "summary": {
            "total_paths_seen": len(all_paths),
            "identical_group_count": total_identical_files,
            "identical_total_lines_all_copies": total_identical_lines_all_copies,
            "total_dup_cost_lines": total_cost,
            "core_ge3_products_file_count": core_ge3_files,
            "core_ge3_lines_one_copy": core_ge3_lines,
            "core_ge3_dup_cost_lines": core_ge3_cost,
            "unique_file_count": len(unique_report),
        }
    }
    out_path = os.path.join(os.path.dirname(__file__), "dup_scan_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("WROTE", out_path)
    print(json.dumps(out["summary"], ensure_ascii=False, indent=2))
    print("file_counts_per_product:", out["file_counts_per_product"])

if __name__ == "__main__":
    main()
