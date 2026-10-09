"""Build a tiny index and run a real CatalogSearchContext search against it.

check_retrieval_wiring.py proves the tool is offered; this proves the tool WORKS --
construction loads the encoder, and a query comes back with the right table. The two
failures on this lane were one of each kind, so both are worth holding.
"""
import json
import sys
import tempfile
from pathlib import Path

NL = Path("C:/Users/rohin/Documents/CMU/Capstone/nl2sql-databao/nl2sql-v2")
sys.path.insert(0, str(NL / "src"))

import numpy as np
import yaml
from sentence_transformers import SentenceTransformer

from nl2sql.context import CatalogSearchContext

MODEL = "BAAI/bge-base-en-v1.5"
QP = "Represent this sentence for searching relevant passages: "

tables = [
    {"name": "p.d.orders", "description": "customer orders with totals",
     "columns": [{"name": "id", "type": "INT64", "description": ""},
                 {"name": "total", "type": "FLOAT64",
                  "description": "order total in dollars"}],
     "foreign_keys": []},
    {"name": "p.d.weather", "description": "daily temperature readings",
     "columns": [{"name": "day", "type": "DATE", "description": ""},
                 {"name": "temp_c", "type": "FLOAT64",
                  "description": "temperature in celsius"}],
     "foreign_keys": []},
]
chunks = [yaml.safe_dump({"table": {"name": t["name"],
                                    "description": t["description"],
                                    "columns": [c["name"] for c in t["columns"]]}},
                         sort_keys=False) for t in tables]

d = Path(tempfile.mkdtemp())
enc = SentenceTransformer(MODEL)
vecs = enc.encode(chunks, normalize_embeddings=True)
np.savez_compressed(
    d / "tiny.npz", chunks=np.array(chunks),
    vecs=np.asarray(vecs, dtype="float32"),
    tables=np.array([json.dumps(tables)]),
    model_id=np.array([MODEL]), query_prefix=np.array([QP]),
    doc_prefix=np.array([""]))

sc = CatalogSearchContext(d, "tiny")
print(f"constructed; model={sc.model_id!r} prefix={sc.query_prefix[:28]!r}...")
print(f"tables loaded: {sorted(sc.tables)}")

out = sc.search("how much money did customers spend", limit=1)
print("\n--- search('how much money did customers spend') ---")
print(out)
assert "orders" in out, "the money question should retrieve the orders table"
assert "weather" not in out.split("JOINED")[0], "it should not rank weather first"

out2 = sc.search("what was the temperature each day", limit=1)
print("\n--- search('what was the temperature each day') ---")
print(out2)
assert "weather" in out2, "the temperature question should retrieve weather"

print("\nretrieval works end to end: construction loads the encoder, and queries "
      "return the right table card")
