"""
Quick test of the BEAVER context engine.
Run from the nl2sql-databao root:
  cd /Users/juliepark/Desktop/cmu_sem2/Capstone/ghs/databao-context-engine
  uv run python ../nl2sql-databao/beaver/test_context_engine.py
"""

from pathlib import Path
from databao_context_engine import DatabaoContextEngine

BEAVER_DCE_DIR = Path(__file__).parent / "beaver-dce"

print(f"Loading context engine from: {BEAVER_DCE_DIR}")
engine = DatabaoContextEngine(domain_dir=BEAVER_DCE_DIR)

# Show all built contexts
all_contexts = engine.get_all_contexts()
print(f"\nBuilt contexts: {len(all_contexts)}")
for ctx in all_contexts:
    print(f"  - datasource_id={ctx.datasource_id}")
    # Print first 500 chars of context
    preview = str(ctx.context)[:500]
    print(f"    preview: {preview}\n")

# Run some test queries
test_queries = [
    "customer sales revenue",
    "order total amount date",
    "product category inventory",
]

for query in test_queries:
    print(f"\n{'='*60}")
    print(f"Query: {query}")
    print('='*60)
    results = engine.search_context(query)
    print(f"Found {len(results)} results")
    for i, r in enumerate(results[:3]):  # show top 3
        print(f"\n--- Result {i+1} ---")
        print(str(r.context_result)[:400])
