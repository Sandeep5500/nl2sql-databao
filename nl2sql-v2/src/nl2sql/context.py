"""DCE semantic search with optional LLM query expansion + Reciprocal Rank Fusion."""

from pathlib import Path

RRF_K = 60

_EXPAND_PROMPT = (
    "You rewrite database-schema search queries. Given a query, produce {n} alternative "
    "phrasings that might match table/column descriptions (use synonyms, likely column "
    "names, related metrics). One per line, no numbering, no commentary.\n\nQuery: {query}"
)


class SearchContext:
    def __init__(self, project_dir: Path, datasource_id: str,
                 expansion_client=None, expansion_model: str | None = None):
        from databao_context_engine import DatabaoContextEngine  # heavy import, defer
        from databao_context_engine.datasources.types import DatasourceId
        self.engine = DatabaoContextEngine(project_dir)
        self.datasource_id = DatasourceId.from_string_repr(datasource_id)
        self.expansion_client = expansion_client
        self.expansion_model = expansion_model

    def _search(self, text: str, limit: int):
        return self.engine.search_context(
            text, limit=limit, datasource_ids=[self.datasource_id]
        )

    def _expand(self, query: str, n: int) -> list[str]:
        resp = self.expansion_client.chat.completions.create(
            model=self.expansion_model,
            messages=[{"role": "user",
                       "content": _EXPAND_PROMPT.format(n=n, query=query)}],
            temperature=0.7, max_tokens=300,
        )
        lines = [l.strip("-• \t") for l in (resp.choices[0].message.content or "").splitlines()]
        return [l for l in lines if l][:n]

    def search(self, query: str, limit: int = 8, expansion_queries: int = 0) -> str:
        queries = [query]
        if expansion_queries and self.expansion_client:
            try:
                queries += self._expand(query, expansion_queries)
            except Exception:
                pass  # expansion is best-effort; plain search still runs

        if len(queries) == 1:
            results = self._search(query, limit)
            chunks = [r.context_result for r in results]
        else:
            # Reciprocal Rank Fusion across all query variants
            scores: dict[str, float] = {}
            for q in queries:
                for rank, r in enumerate(self._search(q, limit)):
                    scores[r.context_result] = scores.get(r.context_result, 0.0) \
                        + 1.0 / (RRF_K + rank + 1)
            chunks = [c for c, _ in sorted(scores.items(), key=lambda kv: -kv[1])][:limit]

        if not chunks:
            return "no matching context found"
        return "\n\n---\n\n".join(chunks)


class TableContext:
    """Per-table records from the context engine's enriched YAML (descriptions,
    declared keys), looked up by table name. This is the same content
    search_context returns, addressed by name instead of ranked retrieval."""

    def __init__(self, project_dir: Path, datasource_id: str,
                 explored: bool = False):
        import yaml
        path = Path(project_dir) / "output" / datasource_id
        doc = yaml.safe_load(path.read_text())
        self.tables: dict[str, dict] = {}
        for cat in (doc.get("context") or {}).get("catalogs") or []:
            for schema in cat.get("schemas") or []:
                for t in schema.get("tables") or []:
                    self.tables[str(t.get("name", "")).lower()] = t
        # keys precomputed by scripts/compute_keys.py (absent -> no key lines
        # for tables without a declared primary key)
        self.keys: dict[str, dict] = {}
        kpath = Path(project_dir) / "output" / "keys" / (Path(datasource_id).stem + ".json")
        if kpath.exists():
            import json
            self.keys = {k.lower(): v for k, v in json.loads(kpath.read_text()).items()}
        # notes from scripts/explore_notes.py
        self.explored: dict = {}
        npath = Path(project_dir) / "output" / "notes" / (Path(datasource_id).stem + ".json")
        if explored and npath.exists():
            import json
            self.explored = json.loads(npath.read_text())
        # column profiles precomputed by scripts/compute_profile.py
        self.profiles: dict[str, dict] = {}
        ppath = Path(project_dir) / "output" / "profile" / (Path(datasource_id).stem + ".json")
        if ppath.exists():
            import json
            self.profiles = {
                t.lower(): {c.lower(): p for c, p in (rec.get("columns") or {}).items()}
                for t, rec in json.loads(ppath.read_text()).items()}

    def profile(self, table: str, column: str) -> str:
        """One-line facts about a column's values (scripts/compute_profile.py)."""
        p = (self.profiles.get(table.lower()) or {}).get(column.lower())
        if not p:
            return ""
        kind, parts = p.get("kind", ""), []
        if kind in ("integer", "decimal", "date", "datetime") and "min" in p:
            parts.append(f"{kind} {p['min']} .. {p['max']}")
            if p.get("stored_like"):
                parts.append(f"stored as text like '{p['stored_like']}'")
        elif kind:
            parts.append(kind)
        if p.get("values"):
            parts.append("values: " + ", ".join(f"{v} ({n})" for v, n in p["values"]))
        elif p.get("shapes"):
            parts.append("formats (9 = digit, A = letters): " + ", ".join(
                f"{s} {round(100 * share)}% e.g. '{ex}'" for s, share, ex in p["shapes"]))
        if p.get("numeric_values"):
            parts.append(f"{p['numeric_values']} values are numbers")
        if p.get("empty_strings"):
            parts.append(f"{p['empty_strings']} empty strings")
        return "; ".join(parts)

    def explored_notes(self, table: str) -> str:
        """Notes from scripts/explore_notes.py, in the form left by the two later
        passes: verify_notes.py drops a note whose cited query does not show it,
        rewrite_notes.py reduces the rest to facts with no advice."""
        tables = {k.lower(): v for k, v in (self.explored.get("tables") or {}).items()}
        rec = tables.get(table.lower())
        if not rec or rec.get("error") or "table_note" not in rec:
            return ""

        def text(x):
            if x.get("verdict") == "no":
                return ""
            return " ".join(str(x.get("fact", x.get("note", ""))).split())

        lines = [f"  (table) {' '.join(str(rec.get('table_fact', rec['table_note'])).split())}"]
        lines += [f"  (table) {text(p)}" for p in rec.get("pitfalls") or [] if text(p)]
        lines += [f"  {c.get('column')}: {text(c)}"
                  for c in rec.get("column_notes") or [] if text(c)]
        return "\n".join(lines)

    def database_note(self) -> str:
        return (self.explored.get("database_fact")
                or self.explored.get("database_note") or "").strip()

    def get(self, table: str) -> dict | None:
        return self.tables.get(table.lower())

    def primary_key(self, table: str) -> list[str] | None:
        t = self.get(table) or {}
        return (t.get("primary_key") or {}).get("columns") or None

    def key_lines(self, table: str) -> list[str]:
        """What one row of the table is, labelled by how we know it."""
        pk = self.primary_key(table)
        if pk:
            return [f"primary key (declared): ({', '.join(pk)})"]
        rec = self.keys.get(table.lower())
        if not rec or "attempts" not in rec:
            return []
        if rec.get("chosen"):
            what = f" — {rec['row_is']}" if rec.get("row_is") else ""
            return [f"one row per ({', '.join(rec['chosen'])}){what}  "
                    "[no declared key; proposed by an LLM and verified unique in the data]"]
        dups = rec.get("duplicate_rows") or 0
        if dups:
            return [f"no key: {dups} rows are exact copies of another row"]
        return ["no key confirmed for this table"]

    def foreign_keys(self, table: str) -> list[str]:
        out = []
        for fk in (self.get(table) or {}).get("foreign_keys") or []:
            ref = str(fk.get("referenced_table", "")).split(".")[-1]
            src = ", ".join(m["from_column"] for m in fk.get("mapping") or [])
            dst = ", ".join(m["to_column"] for m in fk.get("mapping") or [])
            out.append(f"{src} -> {ref}.{dst}")
        return out

    def notes(self, table: str) -> str:
        t = self.get(table)
        if not t:
            return ""
        lines = []
        if t.get("description"):
            lines.append(f"  (table) {' '.join(str(t['description']).split())}")
        for c in t.get("columns") or []:
            if c.get("description"):
                lines.append(f"  {c['name']}: {' '.join(str(c['description']).split())}")
        return "\n".join(lines)
