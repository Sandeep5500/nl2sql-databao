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

    def __init__(self, project_dir: Path, datasource_id: str):
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
