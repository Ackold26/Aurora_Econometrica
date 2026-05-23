"""Apply merge_rules to a dataframe - материализация виртуальных каналов.

Frontend InsightsPanel позволяет объединить слабые каналы в один
(«Малые медиа» из 4 источников). Merge сохраняется как metadata
(`merged_from[]` на виртуальной column). Физически в xlsx такой
колонки нет.

Backend (modeler/decomposer/optimizer/awareness) читает xlsx и
применяет этот helper, чтобы создать `df[merged_name] = sum(sources)`
до использования в логике. Idempotent: повторный вызов не меняет df.
"""
from __future__ import annotations

import pandas as pd


def apply_merge_rules(df: pd.DataFrame, merge_rules: dict | None) -> pd.DataFrame:
    """Создать виртуальные колонки в df по правилам merge.

    Args:
        df: dataframe после read_excel/read_csv.
        merge_rules: `{merged_name: [source_col1, source_col2, ...]}`.
            None или {} - no-op.

    Returns:
        Тот же df (mutated in place). Для удобства chaining.
    """
    if not merge_rules:
        return df
    for merged_name, source_cols in merge_rules.items():
        if merged_name in df.columns:
            continue  # уже есть в файле
        if not isinstance(source_cols, (list, tuple)) or not source_cols:
            continue
        available = [c for c in source_cols if c in df.columns]
        if not available:
            continue  # все sources отсутствуют - caller (column guard) обработает
        df[merged_name] = df[available].fillna(0).sum(axis=1)
    return df
