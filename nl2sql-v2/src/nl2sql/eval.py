"""Spider2-lite scoring, ported unchanged from scripts/spider2_benchmark.py."""

import json
import math
import os
import re

import pandas as pd

from .config import EVAL_JSONL, GOLD_EXEC_DIR


def load_eval_standards() -> dict:
    standards = {}
    with open(EVAL_JSONL) as f:
        for line in f:
            row = json.loads(line)
            standards[row["instance_id"]] = row
    return standards


def _normalize(value):
    if pd.isna(value):
        return 0
    return value


def _vectors_match(v1, v2, tol=1e-2, ignore_order=False):
    v1 = [_normalize(x) for x in v1]
    v2 = [_normalize(x) for x in v2]
    if ignore_order:
        v1 = sorted(v1, key=lambda x: (x is None, str(x), isinstance(x, (int, float))))
        v2 = sorted(v2, key=lambda x: (x is None, str(x), isinstance(x, (int, float))))
    if len(v1) != len(v2):
        return False
    for a, b in zip(v1, v2):
        if pd.isna(a) and pd.isna(b):
            continue
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if not math.isclose(float(a), float(b), abs_tol=tol):
                return False
        elif a != b:
            return False
    return True


def compare_dataframes(pred, gold, condition_cols=None, ignore_order=False) -> bool:
    if condition_cols:
        if not isinstance(condition_cols, (list, tuple)):
            condition_cols = [condition_cols]
        gold_check = gold.iloc[:, condition_cols]
    else:
        gold_check = gold
    t_gold = gold_check.transpose().values.tolist()
    t_pred = pred.transpose().values.tolist()
    for gold_vector in t_gold:
        if not any(_vectors_match(gold_vector, pv, ignore_order=ignore_order)
                   for pv in t_pred):
            return False
    return True


def score_against_gold(pred_df, instance_id: str, standards: dict) -> tuple[int, str]:
    pattern = re.compile(rf"^{re.escape(instance_id)}(_[a-z])?\.csv$")
    gold_files = sorted(GOLD_EXEC_DIR / f for f in os.listdir(GOLD_EXEC_DIR)
                        if pattern.match(f))
    if not gold_files:
        return 0, "no_gold_files"

    standard = standards.get(instance_id, {})
    condition_cols = standard.get("condition_cols")
    ignore_order = standard.get("ignore_order", False)

    if isinstance(condition_cols, list) and condition_cols \
            and isinstance(condition_cols[0], list):
        flat_cols = condition_cols
    else:
        flat_cols = [condition_cols] * len(gold_files)

    for gold_file, cols in zip(gold_files, flat_cols):
        try:
            gold_df = pd.read_csv(gold_file)
            if compare_dataframes(pred_df, gold_df, condition_cols=cols,
                                  ignore_order=ignore_order):
                return 1, f"matches {gold_file.name}"
        except Exception:
            continue
    return 0, "result_mismatch"
