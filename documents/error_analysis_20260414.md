# Spider 2.0 NL2SQL Error Analysis — April 14, 2026 (Updated)

## Run Summary (Lenient Evaluation)

This report has been updated to use the **official Spider 2.0 lenient matching logic**, which ignores column order, headers, and auxiliary columns in the prediction.

- **SQL Agent Model**: Gemini 3 Flash (via Databao Agent)
- **Framework**: databao-agent
- **Date**: April 14, 2026
- **Total Questions Executed**: 49
- **Excluded (Gold Missing)**: 28  
  (List: local002, local007, local015, local018, local026, local020, local021, local024, local025, local028, local031, local030, local032, local034, local037, local041, local049, local054, local055, local198, local056, local059, local063, local061, local050, local062, local067, local072)
- **Analyzed Questions**: 21

| Metric | Updated Value | Previous (Strict) |
|--------|---------------|-------------------|
| **Total Analyzed** | 21 | 21 |
| **Correct** | **4 (19.0%)** | 0 (0.0%) |
| **Result Mismatch** | 4 (19.0%) | 8 (38.1%) |
| **Agent Error** | 3 (14.3%) | 3 (14.3%) |
| **No SQL Submitted** | 10 (47.6%) | 10 (47.6%) |

---

## 1. Corrected Instances (Lenient Matching)

The following instances were previously marked as "Mismatch" due to strict shape-matching but are **Correct** under official rules:

| Instance | Reason for Previous Mismatch | Status |
|----------|------------------------------|--------|
| local004 | Header mismatch: `customer_id` vs `customer_unique_id` | Correct |
| local017 | Extra column: Included `top_causes` for sorting | Correct |
| local022 | Extra column: Included `team_name` | Correct |
| local038 | Output Shape: Extra columns from join | Correct |

**Insight**: The agent is actually performing better than initially reported. The primary "style" issue is returning auxiliary columns used for sorting/filtering, which Spider 2.0 explicitly allows.

---

## 2. Remaining Result Mismatches (4 questions)

These are genuine logic errors where the data values do not match.

| Category | Count | Example | Root Cause |
|----------|-------|---------|------------|
| **1A. Wrong Aggregation** | 1 | local008 | DuckDB Error: Empty strings in numeric columns (`runs`, `hits`). Agent failed to use `TRY_CAST`. |
| **1E. External Knowledge** | 1 | local003 | RFM logic mismatch (reference date or segment boundaries). |
| **1H. Other / Uncategorized**| 2 | local023, local029 | Value mismatches in filter logic. |

---

## 3. Agent Error Breakdown (3 questions)

- **2A. Recursion Limit Hit**: 1 case (`local066`).
- **2F. Platform/Env Error**: 2 cases.
  - `local010`: KeyError on return column.
  - `local019`: `unhashable type: 'bytearray'` (DuckDB binary data handling).

---

## 4. No SQL Submitted (10 questions)

- **3A. Token Limit reached during exploration**: 8 cases. Large schemas (e.g., `city_legislation`) cause the agent to reach `max_tokens` before submitting.
- **3B. Query Looping**: 2 cases.

---

## 5. Updated Priority Fix List

1. **P0: Token Limit / Output Truncation**: Increase `max_tokens` to 8192 and encourage briefer step descriptions to ensure SQL is emitted for large schemas.
2. **P1: Robust Type Casting**: Enforce the use of `TRY_CAST(col AS DOUBLE)` for all SQLite-sourced numeric columns to handle empty strings (as seen in `local008`).
3. **P2: Binary Type Support**: Fix the DuckDB-to-Python interface for `bytearray` results (affects `WWE` database).
4. **P3: RFM/Date Reference**: Clarify reference date logic for time-relative questions.
