"""Schema for the spider2-lite warehouse lanes, read from the repo instead of the warehouse.

spider2-lite ships the whole catalog as JSON under
resource/databases/<engine>/<db>/<namespace>/<table>.json, with the same fields for
both engines:

    table_name, table_fullname, column_names, column_types, description, sample_rows
    (+ nested_column_names / nested_column_types for BigQuery STRUCTs)

So list_tables, describe_table and the column lookups cost **zero warehouse queries
and zero dollars** -- only run_sql_query needs credentials. That matters more here
than on SQLite: BigQuery bills per byte scanned and Snowflake per warehouse-second,
and describe_table is the second-most-called tool in our traces.

The namespace directory is the qualifier the agent must actually type:
  BigQuery : <project>.<dataset>  -> `project.dataset.table`
  Snowflake: <SCHEMA>             -> DB.SCHEMA.TABLE
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

# engine name -> its directory under resource/databases/
ENGINE_DIRS = {"bigquery": "bigquery", "snowflake": "snowflake", "sqlite": "sqlite"}


@dataclass
class CatalogTable:
    name: str                               # bare table name
    fullname: str                           # what SQL must reference
    namespace: str                          # project.dataset, or SCHEMA
    columns: list = field(default_factory=list)        # [(name, type)]
    nested: list = field(default_factory=list)         # [(path, type)] BigQuery structs
    descriptions: list = field(default_factory=list)
    sample_rows: list = field(default_factory=list)
    loaded: bool = False                    # has its JSON been read

    @property
    def qualified(self) -> str:
        return f"{self.namespace}.{self.name}" if self.namespace else self.name


class LiteCatalog:
    """The tables of one spider2-lite database, loaded from the shipped JSON."""

    def __init__(self, db_name: str, engine: str, lite_root: Path):
        self.db_name = db_name
        self.engine = engine
        self.root = Path(lite_root) / "resource/databases" / ENGINE_DIRS.get(
            engine, engine)
        self.db_dir = self._find_db_dir(db_name)
        self.tables: dict[str, CatalogTable] = {}
        self._paths: dict[str, Path] = {}
        if self.db_dir is not None:
            self._load()

    # ── locating the database directory ──────────────────────────────────
    def _find_db_dir(self, db_name: str) -> Path | None:
        exact = self.root / db_name
        if exact.is_dir():
            return exact
        if not self.root.is_dir():
            return None
        # question db names and directory names differ in case for some entries
        lowered = db_name.lower()
        for p in self.root.iterdir():
            if p.is_dir() and p.name.lower() == lowered:
                return p
        return None

    @property
    def available(self) -> bool:
        return bool(self.tables)

    def _load(self) -> None:
        """Index tables from the directory listing only.

        The per-table JSON carries sample rows and is read lazily: a database like
        ebi_chembl has 788 of them, and on a network volume loading all of that to
        answer list_tables() costs far more than the schema is worth. Filenames give
        the table name, and the namespace directory gives the qualifier, which is
        everything the index needs.
        """
        for ns_dir in sorted(self.db_dir.iterdir()):
            if not ns_dir.is_dir():
                continue
            for jf in sorted(ns_dir.glob("*.json")):
                name = jf.stem
                # bigquery dirs are "project.dataset", snowflake dirs are "SCHEMA"
                fullname = (f"{ns_dir.name}.{name}" if "." in ns_dir.name
                            else f"{self.db_dir.name}.{ns_dir.name}.{name}")
                self.tables[fullname] = CatalogTable(
                    name=name, fullname=fullname, namespace=ns_dir.name)
                self._paths[fullname] = jf

    def _detail(self, t: "CatalogTable") -> "CatalogTable":
        """Fill in columns and sample rows on first use, from the shipped JSON."""
        if t.loaded:
            return t
        jf = self._paths.get(t.fullname)
        if jf is None or not jf.exists():
            t.loaded = True
            return t
        try:
            blob = json.loads(jf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            t.loaded = True
            return t
        t.columns = list(zip(blob.get("column_names") or [],
                             blob.get("column_types") or []))
        t.nested = list(zip(blob.get("nested_column_names") or [],
                            blob.get("nested_column_types") or []))
        t.descriptions = blob.get("description") or []
        t.sample_rows = blob.get("sample_rows") or []
        # the JSON is authoritative for the name SQL must use
        if blob.get("table_fullname"):
            t.fullname = blob["table_fullname"]
        t.loaded = True
        return t

    # ── lookups ──────────────────────────────────────────────────────────
    @property
    def namespaces(self) -> list[str]:
        return sorted({t.namespace for t in self.tables.values()})

    def list_tables(self) -> list[str]:
        """Fully qualified, because that is what the agent has to type: BigQuery
        needs project.dataset.table, and these databases span several datasets."""
        return sorted(self.tables)

    def project_for(self, dataset: str) -> str | None:
        """The project that owns a dataset, for repairing an under-qualified
        reference. Namespaces here are "project.dataset" on BigQuery, so the
        project is recoverable from the catalog without asking the warehouse."""
        want = dataset.lower()
        for ns in self.namespaces:
            project, _, ds = ns.rpartition(".")
            if project and ds.lower() == want:
                return project
        return None

    def resolve(self, name: str) -> CatalogTable:
        """exact fullname -> case-insensitive -> namespace.table -> unique bare name."""
        if name in self.tables:
            return self.tables[name]
        lowered = name.lower()

        hits = [t for k, t in self.tables.items() if k.lower() == lowered]
        if len(hits) == 1:
            return hits[0]

        hits = [t for t in self.tables.values() if t.qualified.lower() == lowered]
        if len(hits) == 1:
            return hits[0]

        hits = [t for t in self.tables.values() if t.name.lower() == lowered]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            opts = ", ".join(t.fullname for t in hits[:8])
            raise ValueError(f"Table {name!r} is ambiguous; use one of: {opts}")

        import difflib
        near = [k for k in self.tables if lowered in k.lower()]
        near += [c for c in difflib.get_close_matches(name, list(self.tables),
                                                      n=5, cutoff=0.5)
                 if c not in near]
        hint = ("Did you mean: " + ", ".join(near[:6]) + ". ") if near else ""
        raise ValueError(f"Unknown table {name!r} in {self.db_name}. {hint}"
                         f"Use list_tables() for the full list.")

    def table(self, name: str) -> "CatalogTable":
        """Resolve AND materialise: the only safe way for callers outside this
        module to touch .columns or .sample_rows, which load lazily."""
        return self._detail(self.resolve(name))

    def columns(self, name: str) -> list:
        t = self._detail(self.resolve(name))
        if not t.columns:
            raise ValueError(f"No columns recorded for {t.fullname!r}.")
        # (name, type, nullable) to match dbbase.DatabaseLike; the shipped catalog
        # carries no nullability, and saying "UNKNOWN" beats inventing "YES"
        return [(c, ty, "UNKNOWN") for c, ty in t.columns]

    def describe(self, name: str, sample_rows: int = 5,
                 max_nested: int = 60) -> str:
        t = self._detail(self.resolve(name))
        lines = [f"table: {t.fullname}", "columns:"]
        descs = t.descriptions or []
        for i, (c, ty) in enumerate(t.columns):
            d = descs[i] if i < len(descs) else None
            lines.append(f"  {c}  {ty}" + (f"  -- {d}" if d else ""))

        # BigQuery STRUCT/ARRAY paths: without these the agent cannot address
        # nested fields, which is most of what the GA-style datasets contain
        extra = [(p, ty) for p, ty in t.nested
                 if p not in {c for c, _ in t.columns}]
        if extra:
            lines.append("nested fields (use UNNEST / dotted paths):")
            for p, ty in extra[:max_nested]:
                lines.append(f"  {p}  {ty}")
            if len(extra) > max_nested:
                lines.append(f"  [{len(extra) - max_nested} more nested fields]")

        if t.sample_rows:
            import pandas as pd
            df = pd.DataFrame(t.sample_rows[:sample_rows])
            lines.append(f"sample rows:\n{df.to_csv(index=False)}")
        else:
            lines.append("sample rows: none shipped for this table")
        lines.append("[schema from the Spider2 catalog -- no warehouse query was run]")
        return "\n".join(lines)

    def column_values_hint(self, table: str, column: str, limit: int = 20) -> str:
        """Distinct values seen in the shipped sample rows.

        Only a hint -- a handful of rows, not the real distribution -- but free, and
        enough to fix the spelling/casing mistakes get_column_values exists to catch.
        """
        t = self._detail(self.resolve(table))
        names = {c for c, _ in t.columns}
        if column not in names:
            ci = [c for c in names if c.lower() == column.lower()]
            if len(ci) != 1:
                raise ValueError(f"Unknown column {column!r} in {t.fullname!r}. "
                                 f"Columns: {sorted(names)}")
            column = ci[0]
        seen, out = set(), []
        for row in t.sample_rows:
            v = row.get(column)
            key = str(v)
            if key not in seen:
                seen.add(key)
                out.append(v)
            if len(out) >= limit:
                break
        if not out:
            return (f"no sample values shipped for {t.fullname}.{column}; "
                    f"run a SELECT DISTINCT if you need real values")
        body = "\n".join(str(v) for v in out)
        return (f"values seen in the catalog's {len(t.sample_rows)} sample rows "
                f"(not the full distribution):\n{body}")


def load_catalog(db_name: str, engine: str, lite_root: Path) -> LiteCatalog | None:
    cat = LiteCatalog(db_name, engine, lite_root)
    return cat if cat.available else None
