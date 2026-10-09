"""DCE semantic search with optional LLM query expansion + Reciprocal Rank Fusion.

DCE ranks table AND column chunks together, so a plain top-8 is mostly column
chunks from 2-3 tables. With `group_tables` (default) we over-fetch chunks, fuse
them per TABLE, and return compact table cards for the top `limit` tables, then
list tables one join away (from the YAML's declared + inferred foreign keys).
"""

from pathlib import Path

import yaml

RRF_K = 60
OVERFETCH = 4          # chunks fetched per query = limit * OVERFETCH
HOP_MAX = 6            # joined tables listed after the cards
CARD_COL_DESC = 400    # chars of each matched column's description
CARD_TABLE_DESC = 1500

_EXPAND_PROMPT = (
    "You rewrite database-schema search queries. Given a query, produce {n} alternative "
    "phrasings that might match table/column descriptions (use synonyms, likely column "
    "names, related metrics). One per line, no numbering, no commentary.\n\nQuery: {query}"
)


def _chunk_table(text: str) -> tuple[str | None, str | None]:
    """(table, column) a DCE chunk's display text belongs to; column is None for table chunks."""
    try:
        y = yaml.safe_load(text)
    except yaml.YAMLError:
        return None, None
    if not isinstance(y, dict):
        return None, None
    if "table_name" in y:                      # column chunk: {table_name, column: {name, ...}}
        col = y.get("column")
        return y["table_name"], col.get("name") if isinstance(col, dict) else None
    if isinstance(y.get("table"), dict):       # table chunk: {table: {name, columns, ...}}
        return y["table"].get("name"), None
    return None, None


class SearchContext:
    def __init__(self, project_dir: Path, datasource_id: str,
                 expansion_client=None, expansion_model: str | None = None,
                 group_tables: bool = True, join_hops: bool = True):
        from databao_context_engine import DatabaoContextEngine  # heavy import, defer
        from databao_context_engine.datasources.types import DatasourceId
        self.engine = DatabaoContextEngine(project_dir)
        self.datasource_id = DatasourceId.from_string_repr(datasource_id)
        self.expansion_client = expansion_client
        self.expansion_model = expansion_model
        self.group_tables = group_tables
        self.join_hops = join_hops
        self.tables: dict[str, dict] = {}
        yml = Path(project_dir) / "output" / datasource_id
        if yml.exists():
            doc = yaml.safe_load(yml.read_text(encoding="utf-8"))
            for t in doc["context"]["catalogs"][0]["schemas"][0]["tables"]:
                self.tables[t["name"]] = t

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

    def _queries(self, query: str, expansion_queries: int) -> list[str]:
        queries = [query]
        if expansion_queries and self.expansion_client:
            try:
                queries += self._expand(query, expansion_queries)
            except Exception:
                pass  # expansion is best-effort; plain search still runs
        return queries

    def _fused(self, queries: list[str], per_query: int) -> list[tuple[str, float]]:
        """Reciprocal Rank Fusion of chunk display texts across query variants."""
        scores: dict[str, float] = {}
        for q in queries:
            for rank, r in enumerate(self._search(q, per_query)):
                scores[r.context_result] = scores.get(r.context_result, 0.0) \
                    + 1.0 / (RRF_K + rank + 1)
        return sorted(scores.items(), key=lambda kv: -kv[1])

    # ---- table-level retrieval --------------------------------------------------

    def rank_tables(self, query: str, limit: int = 8, expansion_queries: int = 0):
        """[(table, score, matched_columns)] for the top `limit` tables, plus the list
        of tables one verified join away that are not already ranked."""
        fused = self._fused(self._queries(query, expansion_queries), limit * OVERFETCH)
        agg: dict[str, dict] = {}
        for text, score in fused:
            table, col = _chunk_table(text)
            if not table:
                continue
            a = agg.setdefault(table, {"score": 0.0, "cols": []})
            a["score"] += score
            if col and col not in a["cols"]:
                a["cols"].append(col)
        ranked = sorted(agg.items(), key=lambda kv: -kv[1]["score"])[:limit]
        top = [(t, a["score"], a["cols"]) for t, a in ranked]
        hops = self._neighbours([t for t, _, _ in top]) if self.join_hops else []
        return top, hops

    def _joins(self, table: str) -> list[tuple[list[str], str, list[str]]]:
        out = []
        for fk in self.tables.get(table, {}).get("foreign_keys") or []:
            ref = str(fk.get("referenced_table", "")).split(".")[-1]
            m = fk.get("mapping") or []
            out.append(([x["from_column"] for x in m], ref, [x["to_column"] for x in m]))
        return out

    def _neighbours(self, top: list[str]) -> list[tuple[str, str]]:
        """(table, how it joins) for tables one FK away from the ranked ones."""
        seen, out = set(top), []
        lower = {t.lower(): t for t in self.tables}
        for t in top:
            for cols, ref, keys in self._joins(t):
                ref = lower.get(ref.lower(), ref)
                if ref not in seen:
                    seen.add(ref)
                    out.append((ref, f"{t}({', '.join(cols)}) -> {ref}({', '.join(keys)})"))
        for other in self.tables:   # tables that point INTO a ranked table
            if other in seen:
                continue
            for cols, ref, keys in self._joins(other):
                if lower.get(ref.lower()) in top:
                    seen.add(other)
                    out.append((other, f"{other}({', '.join(cols)}) -> {lower[ref.lower()]}({', '.join(keys)})"))
                    break
        return out[:HOP_MAX]

    def _card(self, table: str, cols: list[str]) -> str:
        t = self.tables.get(table)
        if not t:
            return f"TABLE {table}"
        lines = [f"TABLE {table}: {(t.get('description') or '')[:CARD_TABLE_DESC]}"]
        by_name = {c["name"]: c for c in t.get("columns", [])}
        for c in cols:
            if c in by_name:
                d = (by_name[c].get("description") or "")[:CARD_COL_DESC]
                lines.append(f"  - {c} ({by_name[c].get('type', '')}): {d}")
        rest = [n for n in by_name if n not in cols]
        if rest:
            lines.append(f"  other columns: {', '.join(rest)}")
        return "\n".join(lines)

    # ---- tool entry point -------------------------------------------------------

    def search(self, query: str, limit: int = 8, expansion_queries: int = 0) -> str:
        if self.group_tables and self.tables:
            top, hops = self.rank_tables(query, limit, expansion_queries)
            if not top:
                return "no matching context found"
            out = "\n\n".join(self._card(t, cols) for t, _, cols in top)
            if hops:
                out += "\n\nJOINED TABLES (one verified join away, not ranked above):\n" + \
                       "\n".join(f"  - {h}: {how}" for h, how in hops)
            return out

        queries = self._queries(query, expansion_queries)
        if len(queries) == 1:
            chunks = [r.context_result for r in self._search(query, limit)]
        else:
            chunks = [c for c, _ in self._fused(queries, limit)][:limit]
        if not chunks:
            return "no matching context found"
        return "\n\n---\n\n".join(chunks)

# ── retrieval over a prebuilt catalog index (the warehouse lanes) ────────────

_ENCODERS: dict = {}


def _encoder(model_id: str):
    """One SentenceTransformer per process, cached: loading is seconds and every
    episode on a shard embeds queries against the same model."""
    if model_id not in _ENCODERS:
        from sentence_transformers import SentenceTransformer
        _ENCODERS[model_id] = SentenceTransformer(model_id, trust_remote_code=True)
    return _ENCODERS[model_id]


class _Hit:
    """The one field SearchContext._fused and rank_tables read off a result."""
    __slots__ = ("context_result", "score")

    def __init__(self, context_result: str, score: float):
        self.context_result = context_result
        self.score = score


class CatalogSearchContext(SearchContext):
    """search_context over an index built by scripts/build_bq_context.py.

    Same public surface as SearchContext (search / rank_tables), same table cards and
    join hops, but the chunk search is a cosine scan over vectors on disk instead of
    a DCE DuckDB query. A warehouse database here is at most a few thousand chunks,
    so a brute-force matmul is well under a millisecond and needs no index format.
    """

    def __init__(self, index_dir, db_name: str, expansion_client=None,
                 expansion_model: str | None = None, group_tables: bool = True,
                 join_hops: bool = True):
        # deliberately not super().__init__(): that imports databao_context_engine
        # and opens the DCE project, neither of which exists for these databases.
        self.expansion_client = expansion_client
        self.expansion_model = expansion_model
        self.group_tables = group_tables
        self.join_hops = join_hops
        self.datasource_id = db_name
        self.engine = None

        import numpy as np

        base = Path(index_dir)
        yml = base / f"{db_name}.yaml"
        npz = base / f"{db_name}.npz"
        if not yml.exists() or not npz.exists():
            raise FileNotFoundError(
                f"no catalog index for {db_name!r} in {base} "
                f"(expected {yml.name} and {npz.name}); "
                f"run scripts/build_bq_context.py --db {db_name}")

        doc = yaml.safe_load(yml.read_text(encoding="utf-8"))
        self.tables = {t["name"]: t for t in
                       doc["context"]["catalogs"][0]["schemas"][0]["tables"]}

        blob = np.load(npz, allow_pickle=False)
        self.chunks = [str(c) for c in blob["chunks"]]
        mat = blob["vecs"].astype("float32")
        # stored normalised, but renormalise so a hand-built index cannot skew scores
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        self.vecs = mat / np.where(norms == 0, 1.0, norms)
        self.model_id = str(blob["model_id"][0]) if "model_id" in blob else ""
        self.query_prefix = str(blob["query_prefix"][0])             if "query_prefix" in blob else ""

    def _search(self, text: str, limit: int):
        import numpy as np

        enc = _encoder(self.model_id)
        # The prefix the index was BUILT with, carried in the index itself. nomic's
        # task prefixes are not optional-but-harmless: an index embedded with
        # "search_document: " must be queried with "search_query: ", and mixing them
        # degrades retrieval quietly rather than failing. See
        # scripts/dce_patches/0001-fk-text-and-nomic-prefixes.patch.
        q = enc.encode([self.query_prefix + text], normalize_embeddings=True)
        sims = self.vecs @ np.asarray(q, dtype="float32")[0]
        top = np.argsort(-sims)[:limit]
        return [_Hit(self.chunks[i], float(sims[i])) for i in top]
