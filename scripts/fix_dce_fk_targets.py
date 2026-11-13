#!/usr/bin/env python3
"""Fill in the target column of foreign keys that name only the parent table, in the
context engine's records (<project>/output/databases/*.yaml).

SQLite allows `REFERENCES parent` without a column list, meaning the parent's primary key.
The engine records such a key with no to_column and then cannot read the record back
(pydantic: to_column field required), so indexing from the records fails for that whole
datasource. Building and indexing in one pass never reads the record, which is why the
Spider2 index did not hit this. A key whose parent has no primary key of matching width
is dropped; SQLite rejects such a key as well.

Usage (before indexing from the records):
    python scripts/fix_dce_fk_targets.py <project>/output/databases
"""

import sys
from pathlib import Path

import yaml


def main():
    root = Path(sys.argv[1])
    filled = dropped = files = 0
    for f in sorted(root.glob("*.yaml")):
        doc = yaml.safe_load(f.read_text())
        changed = False
        for cat in doc["context"]["catalogs"]:
            for schema in cat["schemas"]:
                pks = {t["name"].lower(): (t.get("primary_key") or {}).get("columns") or []
                       for t in schema["tables"]}
                for t in schema["tables"]:
                    keep = []
                    for fk in t.get("foreign_keys") or []:
                        maps = fk.get("mapping") or []
                        if all(m.get("to_column") for m in maps):
                            keep.append(fk)
                            continue
                        pk = pks.get(str(fk.get("referenced_table", "")).split(".")[-1].lower(), [])
                        changed = True
                        if maps and len(pk) == len(maps):
                            for m, col in zip(maps, pk):
                                m["to_column"] = m.get("to_column") or col
                            keep.append(fk)
                            filled += 1
                        else:
                            dropped += 1
                    if t.get("foreign_keys") is not None:
                        t["foreign_keys"] = keep
        if changed:
            files += 1
            f.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    print(f"{files} records changed: {filled} foreign keys given their parent's primary key, "
          f"{dropped} dropped (parent without a matching primary key)")


if __name__ == "__main__":
    main()
