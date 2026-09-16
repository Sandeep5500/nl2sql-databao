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
