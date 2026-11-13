#!/usr/bin/env python3
"""Convert a BEAVER mysqldump (beaver-table/beaver_db.zip: dw.sql, nova.sql, neutron.sql) into a
SQLite database the harness can run on.

CREATE TABLE: columns with their types mapped to SQLite affinities (ints -> INTEGER, float/
double/decimal -> REAL, everything else TEXT), PRIMARY KEY and FOREIGN KEY constraints kept
(describe_table and the key finder read them), plain KEY/INDEX lines dropped. INSERT values are
parsed here (MySQL escapes: \\' \\" \\\\ \\n \\r \\t \\0 \\Z) and bound as parameters, so no
quoting is translated. Streams the dump: nova.sql is 2GB.

Usage: python scripts/beaver_to_sqlite.py --dump dumps/nova.sql --out databases/nova.sqlite
"""

import argparse
import re
import sqlite3
import time

ESC = {"0": "\0", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a", "b": "\b"}
COL = re.compile(r"^\s*`([^`]+)`\s+([a-zA-Z]+)(\([^)]*\))?(.*?),?$")
PK = re.compile(r"^\s*PRIMARY KEY \((.+?)\)")
FK = re.compile(r"^\s*CONSTRAINT `[^`]*` FOREIGN KEY \((.+?)\) REFERENCES `([^`]+)` \((.+?)\)")


def affinity(t):
    t = t.lower()
    if t in ("int", "integer", "tinyint", "smallint", "mediumint", "bigint", "bit", "bool", "boolean"):
        return "INTEGER"
    if t in ("float", "double", "real", "decimal", "numeric"):
        return "REAL"
    return "TEXT"


def quoted(cols):
    return cols.replace("`", '"')


def create_sql(name, lines):
    cols, cons = [], []
    for ln in lines:
        if m := PK.match(ln):
            cons.append(f"PRIMARY KEY ({quoted(m.group(1))})")
        elif m := FK.match(ln):
            cons.append(f"FOREIGN KEY ({quoted(m.group(1))}) REFERENCES \"{m.group(2)}\" ({quoted(m.group(3))})")
        elif m := COL.match(ln):
            notnull = " NOT NULL" if "NOT NULL" in m.group(4) else ""
            cols.append(f"\"{m.group(1)}\" {affinity(m.group(2))}{notnull}")
    return f"CREATE TABLE \"{name}\" ({', '.join(cols + cons)})", len(cols)


def parse_values(s, i):
    """Rows of an INSERT ... VALUES (...),(...); statement, starting at s[i] == '('."""
    rows, row, n = [], [], len(s)
    while i < n:
        c = s[i]
        if c == "(":
            row = []
            i += 1
        elif c == "'":
            out, i = [], i + 1
            while True:
                j = s.find("'", i)
                k = s.find("\\", i)
                if k != -1 and k < j:
                    out.append(s[i:k])
                    out.append(ESC.get(s[k + 1], s[k + 1]))
                    i = k + 2
                elif s.startswith("''", j):
                    out.append(s[i:j] + "'")
                    i = j + 2
                else:
                    out.append(s[i:j])
                    i = j + 1
                    break
            row.append("".join(out))
        elif c in ",\n ":
            i += 1
        elif c == ")":
            rows.append(row)
            i += 1
        elif c == ";":
            break
        else:
            j = i
            while s[j] not in ",)":
                j += 1
            tok = s[i:j]
            if tok == "NULL":
                row.append(None)
            elif tok.startswith(("0x", "0X")):
                row.append(bytes.fromhex(tok[2:]).decode("utf-8", "replace"))
            else:
                try:
                    row.append(int(tok))
                except ValueError:
                    row.append(float(tok))
            i = j
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    con = sqlite3.connect(args.out)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    ncols, counts, t0 = {}, {}, time.time()
    table, body = None, []
    with open(args.dump, encoding="utf-8", errors="replace") as f:
        for line in f:
            if table is not None:
                if line.startswith(")"):
                    sql, ncols[table] = create_sql(table, body)
                    con.execute(f"DROP TABLE IF EXISTS \"{table}\"")
                    con.execute(sql)
                    counts[table], table = 0, None
                else:
                    body.append(line.rstrip("\n"))
            elif line.startswith("CREATE TABLE `"):
                table, body = line.split("`")[1], []
            elif line.startswith("INSERT INTO `"):
                name = line.split("`")[1]
                rows = parse_values(line, line.index("VALUES ") + 7)
                bad = [r for r in rows if len(r) != ncols[name]]
                if bad:
                    raise SystemExit(f"{name}: row with {len(bad[0])} values, table has {ncols[name]}")
                con.executemany(f"INSERT INTO \"{name}\" VALUES ({','.join('?' * ncols[name])})", rows)
                counts[name] += len(rows)
    con.commit()
    con.close()
    print(f"{len(counts)} tables, {sum(counts.values())} rows, {time.time() - t0:.0f}s -> {args.out}")
    for t, c in sorted(counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {t}: {c}")


if __name__ == "__main__":
    main()
