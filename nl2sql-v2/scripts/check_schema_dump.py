#!/usr/bin/env python3
"""Self-test for full_schema_dump()'s budget tiers and shard collapse.

Runs against a fake catalog, so it needs no Spider2 checkout and no credentials:

    uv run python scripts/check_schema_dump.py

The property that matters is the one the bq_v2 run violated: EVERY table name must
survive the char cap. 149 of 204 episodes were shown a dump cut with text[:60_000],
so the tables after the cut were invisible and the agent's "Unrecognized name" errors
looked like model mistakes.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from run_benchmark import collapse_shards, full_schema_dump  # noqa: E402


class FakeDB:
    """A ga360-shaped catalog: a few real tables plus a big date-sharded family."""

    def __init__(self, n_plain=40, n_shards=300, cols=30, desc_chars=600):
        self.plain = [f"proj.ds.table_{i:03d}" for i in range(n_plain)]
        # real YYYYMMDD, walked day by day. The regex accepts 6 or 8 digits, and an
        # earlier version of this fixture emitted 7 for shard 100+, so two thirds of
        # the "shards" never matched and the test was checking almost nothing.
        d0 = date(2016, 8, 1)
        self.shards = [f"proj.ds.ga_sessions_{d0 + timedelta(days=i):%Y%m%d}"
                       for i in range(n_shards)]
        self.cols = cols
        self.desc_chars = desc_chars

    def list_tables(self):
        return sorted(self.plain + self.shards)

    def _columns(self, table):
        return [(f"column_{i:02d}", "STRING", "UNKNOWN") for i in range(self.cols)]

    def describe_table(self, table, sample_rows=5, context=None, notes=True):
        cols = "\n".join(f"  column_{i:02d}  STRING  -- {'d' * 40}"
                         for i in range(self.cols))
        return (f"table: {table}  (1000 rows)\ncolumns:\n{cols}\n"
                f"sample rows:\n{'s' * self.desc_chars}")


def check(label, db, cap):
    tables = db.list_tables()
    collapsed, families = collapse_shards(tables)
    text = full_schema_dump(db, char_cap=cap)
    missing = [t for t in collapsed if t not in text]
    over = len(text) > cap * 1.15      # the footer can push slightly past the cap
    print(f"\n{label}")
    print(f"  catalog            : {len(tables)} tables -> {len(collapsed)} after "
          f"collapse ({len(families)} families)")
    print(f"  dump length        : {len(text)} chars (cap {cap})")
    print(f"  names present      : {len(collapsed) - len(missing)}/{len(collapsed)}")
    assert not missing, f"{len(missing)} table names missing from the dump: {missing[:5]}"
    assert not over, f"dump is {len(text)} chars, far over the {cap} cap"
    if families:
        rep = next(iter(families))
        assert "_TABLE_SUFFIX" in text, "collapsed family without the wildcard hint"
        assert rep in text, f"family representative {rep} absent"
        print(f"  wildcard hint      : yes ({rep})")
    return text


def main():
    # the real shape: 340 tables, 300 of them one family -> must fit comfortably
    t = check("ga360-shaped (40 plain + 300 shards)", FakeDB(), 58_000)
    assert "[schema dump truncated]" not in t, "old naive truncation marker is back"

    # a genuinely wide database with no shards: tiers must degrade, not drop names
    t = check("wide, unsharded (400 tables, no families)",
              FakeDB(n_plain=400, n_shards=0), 58_000)
    assert "listed by name below" in t, \
        "a 400-table catalog should have fallen back to the name list"

    # a small database must still get full detail, unchanged in spirit
    t = check("small (8 tables)", FakeDB(n_plain=8, n_shards=0), 58_000)
    assert "sample rows" in t, "a small database should keep its sample rows"
    assert "listed by name below" not in t, "a small database should not degrade"

    # a cap so small only the floor fits
    t = check("tiny cap", FakeDB(n_plain=30, n_shards=0), 2_000)

    # two shards is not a family
    _, fams = collapse_shards(["a_20160801", "a_20160802"])
    assert not fams, "a two-shard family should be left alone"
    _, fams = collapse_shards(["a_20160801", "a_20160802", "a_20160803"])
    assert "a_*" in fams, "a three-shard family should collapse"
    assert fams["a_*"] == ("a", 3, "20160801", "20160803"), fams
    # YYYYMM as well as YYYYMMDD
    _, fams = collapse_shards(["m_201601", "m_201602", "m_201603"])
    assert "m_*" in fams, "YYYYMM families should collapse too"
    print("\nall schema-dump checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
