# Spider 2.0-Lite BigQuery: four lanes, 204 questions

**What this is.** The BigQuery split of Spider 2.0-Lite has never been scored in this
project — every published number is the 135 SQLite locals. This is four runs over all
204 BigQuery instances (`bq###` 179, `ga###` 25) across 69 databases, with
`Qwen/Qwen3.6-35B-A3B` on one H200, greedy decoding, so the lanes differ only by the
one thing each adds.

Per-question outcomes are in [bigquery_lane_comparison.md](bigquery_lane_comparison.md).
Every number below is reproducible from the scripts named beside it.

---

## 1. The lanes

| lane | adds | correct | n | accuracy | 95% CI |
|---|---|---:|---:|---:|---:|
| `bq_v2` | baseline: 40 steps, truncating schema dump, dead `find_value` | 69 | 204 | 33.8% | ±6.5 |
| `bq_v3` | five harness fixes, 60 steps | 84 | 204 | 41.2% | ±6.8 |
| **`bq_v3r`** | **+ gated output-shape rubric** | **95** | **200** | **47.5%** | **±6.9** |
| `bq_v3s` | + catalog retrieval (`search_context`, k=16, additive) | 87 | 204 | 42.6% | ±6.8 |

`scripts/compare_lanes.py --a <base> --b <new> --a-traces ... --b-traces ...`

Those intervals are ±14 questions wide. A single lane-to-lane difference smaller than
that is not evidence on its own, which is why each claim below is backed by a flip
count or an internal control rather than by the net.

---

## 2. Where the accuracy actually went

`scripts/error_taxonomy.py` buckets every **wrong** episode by its last failure state,
one bucket each, so the buckets sum to the loss. It separates failures the harness
caused from failures the model made.

| | `bq_v2` | `bq_v3` | `bq_v3r` | `bq_v3s` |
|---|---:|---:|---:|---:|
| **harness: prompt truncated, table names lost** | **77** | 0 | 0 | 0 |
| harness: dead tool offered (`find_value`) | 5 | 0 | 0 | 0 |
| harness: ran out of steps, submitted exploratory SQL | 36 | 15 | 7 | 13 |
| harness: query cancelled for time | 0 | 7 | 3 | 8 |
| harness: scan budget refused the query | 0 | 0 | 1 | 2 |
| **harness subtotal** | **118** | **22** | **11** | **23** |
| model: answered, answer was wrong | 17 | 98 | 94 | 94 |
| **total wrong** | 135 | 120 | 105 | 117 |

**87% of the baseline's failures were handicaps we imposed, not mistakes the model
made.** 77 of 135 wrong episodes had been shown a schema dump cut mid-table by
`text[:60_000]`, so every table after the cut was invisible and the resulting
"Unrecognized name" errors read like model failures. Another 36 ran out of steps at 40
and submitted whatever they had; 5 more were steered into a tool the backend refuses.

One caveat on reading that column honestly: the harness buckets take priority, so a
`bq_v2` episode with a truncated prompt is counted as handicapped even if the model
would also have got it wrong. 41 of the 149 truncated episodes still answered
correctly. The right reading is "118 of 135 wrong episodes carried a harness
handicap", not "118 were caused by it".

The model-error count rising from 17 to 98 is not the model getting worse. It is the
handicaps being removed so that the real failure distribution becomes visible.

---

## 3. What the model now gets wrong

`scripts/wrong_answer_shapes.py` compares each submitted result against the gold CSV.
On the best lane, all 97 wrong submitted answers are shape-comparable:

| kind | n | share |
|---|---:|---:|
| too many rows | 49 | 51% |
| too few rows | 15 | 15% |
| wrong column count | 32 | 33% |
| same shape, different values | 1 | 1% |

**Two thirds of remaining failures are the wrong row set, and a third are the wrong
columns. Almost none are the right shape with wrong numbers.** The model is generally
finding the right tables and computing something sensible; what it gets wrong is the
grain — a missing filter, an un-deduplicated join, a `GROUP BY` at the wrong level.

That is a strikingly different picture from "the model can't write SQL", and it is the
reason the rubric works.

---

## 4. The rubric: +8.1 points against a measured noise floor

The rubric is a planning pass that states what the answer should look like — how many
rows, which columns, what ordering — and is appended to the prompt only when it is
confident (`rows_confidence == "high"` and `exact_rows` set). 127 of 203 questions
passed that gate.

The gate gives a free internal control: questions that fail it get a prompt **byte
identical** to `bq_v3`'s, so whatever they move is sampling variance at temperature 0.

| group | n | `bq_v3` | `bq_v3r` | delta | flips |
|---|---:|---:|---:|---:|---|
| **rubric in the prompt** | 123 | 41.5% | **49.6%** | **+8.1** | +18 / −8 |
| prompt byte-identical | 77 | 42.9% | 44.2% | +1.3 | +7 / −6 |

`scripts/analysis/rubric_split.py`

The gated group beat its own noise floor by about 7 points with a clear flip
asymmetry. Two limits: n=123 puts a wide interval on +8.1, so the credible part is the
contrast rather than the point estimate; and the groups are not randomly assigned,
since the gate selects questions where the model was confident about the row count.

The rubric targets exactly the failure mode section 3 measures, which is why it is the
one intervention that moved the number.

---

## 5. Retrieval: a clean null

The context engine was expected to matter here. It does not.

| | | |
|---|---:|---|
| episodes that called `search_context` | 154 / 204 (75%) | 244 calls, **0 errored** |
| episodes that **used** it | 39.0% → 40.9% | flips +19 / −16 |
| episodes that did **not** use it | 48.0% → 48.0% | flips +4 / −4 |
| databases **with** column descriptions (n=164) | 39.0% → 39.0% | — |

`scripts/analysis/retrieval_effect.py`

The tool was genuinely exercised — three quarters of episodes, no failed calls,
verified live in the traces before the lane was allowed to run — and it moved nothing.
This is not "the model ignored retrieval"; it is "retrieval added nothing usable once
every table was already named in the prompt".

**This answers the open question about investing in the context engine.** Retrieval
measured as vestigial on the 135 SQLite locals, and the argument was that its real
test would be enterprise-scale schemas. This is that test — 69 BigQuery databases, up
to 785 tables each, 301,106 indexed chunks — and the finding holds, *provided the
schema dump is not truncating*.

Worth being precise about one thing, because it looked like the opposite early on. The
27.5%-vs-50.9% gap between truncated and complete prompts in `bq_v2` was never
evidence for retrieval. It was evidence for fixing the dump, and fixing the dump is
what moved the number.

Retrieval's own quality is not the limitation. Measured against official gold SQL for
128 questions (`scripts/check_retrieval_recall.py`): all-tables recall is 61.7% at
k=8 and 70.3% at k=16. The misses concentrate in large, *well-described*,
sibling-heavy databases — `noaa_data` (218 tables, 96% described), `sdoh` (294),
`census_bureau_acs_1` (351) — where gold wants `county_2017_5yr` among a dozen
`county_YYYY_Nyr` variants. The distinguishing token is a year **in the name**, which
semantic similarity cannot separate and a complete name list separates trivially.

---

## 6. The biggest remaining headroom is selection, not generation

| | questions | share |
|---|---:|---:|
| solved by **at least one** lane | **128** | **62.7%** |
| best single lane (`bq_v3r`) | 95 | 46.6% |
| solved by **all four** lanes | 35 | 17.2% |
| solved by **no** lane | 76 | 37.3% |

Cumulative union, best lane first: `bq_v3r` 46.6% → +`bq_v3` 53.4% → +`bq_v3s` 58.8%
→ +`bq_v2` 62.7%.

| lanes solving it | questions |
|---:|---:|
| 0 | 76 |
| 1 | 28 |
| 2 | 28 |
| 3 | 37 |
| 4 | 35 |

**A perfect selector over these four runs would score 62.7% against the best single
lane's 46.6%** — about 16 points, 28 of which sit in questions exactly one lane
solved. That mirrors the SQLite split, where pass@1 47.4% rose to pass@4 69.6%, and it
says the same thing: generation is not the binding constraint, selection is.

The flip side is that **39 of 204 questions (19%) change outcome more than once across
the four lanes.** That is the temperature-0 variance baked into every comparison in
this document, and it is why the rubric's internal control matters more than its net
delta. Comparing `bq_v2` to the best lane: 41 questions recovered, 13 regressed, 35
were always right and 76 always wrong.

---

## 7. The 76 that no lane solved

| database | never solved | in lane | rate |
|---|---:|---:|---:|
| `firebase` | 6 | 9 | 67% |
| `ga360` | 6 | 12 | 50% |
| `ga4` | 6 | 17 | 35% |
| `fda` | 4 | 5 | 80% |
| `ncaa_basketball` | 4 | 5 | 80% |
| `chicago` | 3 | 5 | 60% |
| `mitelman` | 3 | 3 | 100% |

**18 of the 25 `ga###` questions are never solved by any lane.** The three Google
Analytics / Firebase event databases — `ga4`, `ga360`, `firebase` — account for 18 of
the 76, and they are the deeply-nested event-stream schemas where an answer requires
`UNNEST` over two or three levels of `STRUCT` plus a `_TABLE_SUFFIX` date filter. The
`ga` family's accuracy is 10/25 in the best lane against 85/179 for `bq###`, and the
schemas are the reason: the collapsed-wildcard fix made them *visible*, which is why
`ga` moved 7 → 10, but seeing the schema is not the same as being able to write
correct nested SQL against it.

Fourteen databases yielded nothing at all across four configurations, though most are
one- or two-question databases where that is unremarkable: `mitelman` (3 for 3),
`fec` (2), `CYMBAL_INVESTMENTS` (2), `ebi_chembl` (2), and ten more with a single
question each.

---

## 8. Cost

| lane | scanned | on-demand cost |
|---|---:|---:|
| `bq_v2` | 1.0944 TiB | $6.84 |
| `bq_v3` | 1.5194 TiB | $9.50 |
| `bq_v3r` | 1.3106 TiB | $8.19 |
| `bq_v3s` | 1.3370 TiB | $8.36 |

About $33 total at $6.25/TiB, the 1 TiB monthly free tier having been spent. A lane
that finishes more episodes bills more, since a correct answer scans more than an
abandoned one.

Three things cost **zero** warehouse budget: the rubric passes (the planning agent
reads the catalog Spider 2.0 ships, not the warehouse — verified at 0 B scanned), the
retrieval index build (70 databases, 22.6 min on an L4), and all three recall gates.

`bq_v3r` and `bq_v3s` scan figures are floors: rows lost by restarted shards were
rebuilt from traces, which carry the score but not `scan_bytes`.

---

## 9. What I would do next

1. **Selection, not generation.** 62.7% is reachable with the lanes already run. A
   judge or majority vote over 4 samples is the single largest available gain, and it
   needs no new harness work — the four runs are on disk.
2. **Grain, not retrieval.** Two thirds of residual failures are the wrong row set.
   The rubric already recovers some of that by stating expected row counts; extending
   it to state the expected *grain* ("one row per county per year") targets the
   measured failure directly.
3. **Do not invest further in retrieval for this split.** Section 5 is a null with
   75% tool usage and zero errors, and section 7 shows the hard databases fail for a
   reason retrieval cannot address.
4. **Leave the step cap at 60.** It still refuses 15 episodes at 0% correct, but
   `bq282` showed what raising it buys at the margin: 27 timeout retries and a
   fallback submission.

---

## Reproducing this

```bash
cd nl2sql-v2
uv run python scripts/compare_lanes.py \
    --a ../results/bq_v2_run.csv  --a-traces ../logs/traces/bq_v2 \
    --b ../results/bq_v3r_run.csv --b-traces ../logs/traces/bq_v3r
uv run python scripts/error_taxonomy.py \
    bq_v2:../logs/traces/bq_v2:../results/bq_v2_run.csv \
    bq_v3r:../logs/traces/bq_v3r:../results/bq_v3r_run.csv
uv run python scripts/wrong_answer_shapes.py ../logs/traces/bq_v3r \
    --run ../results/bq_v3r_run.csv
uv run python scripts/analysis/rubric_split.py
uv run python scripts/analysis/retrieval_effect.py
uv run python scripts/per_question_report.py \
    --lane bq_v2:../results/bq_v2_run.csv:../logs/traces/bq_v2 \
    --lane bq_v3:../results/bq_v3_run.csv:../logs/traces/bq_v3 \
    --lane bq_v3r:../results/bq_v3r_run.csv:../logs/traces/bq_v3r \
    --lane bq_v3s:../results/bq_v3s_run.csv:../logs/traces/bq_v3s \
    --out ../documents/bigquery_lane_comparison.md
```

Individual episodes are readable in the trajectory viewer:

```bash
uv run python scripts/analysis/to_openhands.py --runs 'bq_v3*' \
    --source spider2_lite_bq --run-csv '../results/bq_v3*_run.csv' \
    --out ../logs/openhands
uv run python scripts/serve_trajectories.py --dir ../logs/openhands --port 8008
```
