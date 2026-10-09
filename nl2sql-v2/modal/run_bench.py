"""Run the harness itself on Modal, so nothing depends on a laptop staying awake.

    modal run nl2sql-v2/modal/run_bench.py::stage_data                    # once
    modal run nl2sql-v2/modal/run_bench.py::smoke                         # prove the venue
    modal run --detach nl2sql-v2/modal/run_bench.py::preflight
    modal run --detach nl2sql-v2/modal/run_bench.py::snow --limit 40      # calibration
    modal run --detach nl2sql-v2/modal/run_bench.py::snow --shards 8      # the full 412
    modal run --detach nl2sql-v2/modal/run_bench.py::dbt --smallest 3     # the gate
    modal volume get nl2sql-results results ./pulled                      # fetch output

Two Modal specifics this encodes:

* Volume writes are invisible to other containers until committed, and --resume reads
  the output CSV back, so every function commits before returning and the sharded run
  commits per shard.
* Shards are split BY DATABASE, not round-robin. The describe_table cache and
  Snowflake's own result cache are keyed by table and by query text, so keeping each
  database inside one shard turns repeated catalog work into cache hits instead of
  having eight shards each pay to describe GA4.
"""

import modal

REPO = "/root/nl2sql-v2"

base_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "unzip")
    .uv_pip_install(
        # the harness's own runtime deps (databao-context-engine is omitted: the
        # snow and dbt lanes do not use search_context, so the DCE index is not needed)
        "openai>=1.50", "duckdb>=1.1", "pandas>=2.0", "pyyaml>=6.0",
        "sqlglot>=30.18.0", "inspect-ai>=0.3.263",
        # the two extras, pinned as in pyproject.toml
        "snowflake-connector-python[pandas]>=3.12",
        "dbt-core>=1.9,<1.10", "dbt-duckdb>=1.9,<1.10",
        # the BigQuery half of spider2-lite, and db-dtypes so BigQuery
        # DATE/TIME columns land in pandas instead of raising
        "google-cloud-bigquery>=3.25", "db-dtypes>=1.2",
        # their evaluation_suite imports these at module scope
        "tqdm", "gdown",
    )
    # PYTHONUNBUFFERED: without it a script's prints only reach the Modal log
    # when it exits, so a long run looks hung when it is merely working.
    .env({"NL2SQL_DATA_ROOT": "/data", "NL2SQL_SCRATCH": "/tmp/nl2sql-scratch",
          # the retrieval index goes on the results volume: /data is populated once
          # by stage_data, while this is written by bq_index and read by every shard
          "NL2SQL_CONTEXT_DIR": "/results/context",
          "PYTHONUNBUFFERED": "1"})
)

# add_local_dir has to be the LAST layer: Modal refuses any layer added after a
# local-dir mount that was not made with copy=True. So both images branch from the
# base above and mount the source at the end.
image = base_image.add_local_dir("nl2sql-v2", REPO)

# The index builder needs torch + sentence-transformers, which the benchmark
# containers have no use for, so it gets its own branch. einops is required by
# nomic's remote code (build_bq_context.py --embedder nomic); the default bge needs
# none of it, but installing it keeps the flag usable.
embed_image = (
    base_image
    .uv_pip_install("sentence-transformers>=3.0", "einops>=0.8")
    .add_local_dir("nl2sql-v2", REPO)
)

# Spider2 questions/gold/dbt projects; the big downloads happen inside a container
spider2_data = modal.Volume.from_name("spider2-data", create_if_missing=True)
# results, traces and the shared describe_table cache
results = modal.Volume.from_name("nl2sql-results", create_if_missing=True)

app = modal.App("nl2sql-bench")

VOLUMES = {"/data": spider2_data, "/results": results}
# The dbt lane needs no warehouse credentials, and it is the track that runs while
# Snowflake access is still pending -- so it must not reference a secret that does
# not exist yet. Only the Snowflake functions ask for that one.
VLLM_SECRET = [modal.Secret.from_name("nl2sql-vllm")]


def _optional_secret(name: str) -> list:
    """Include a secret only if it exists.

    Modal resolves every function's secrets when it builds the app, so a
    hard reference to a secret that does not exist yet blocks the whole file --
    including stage_data and the dbt lane, which need no warehouse credentials
    and are precisely what should run while Snowflake access is pending.
    """
    try:
        secret = modal.Secret.from_name(name)
        secret.hydrate()
        return [secret]
    except Exception as e:
        print(f"[note] secret {name!r} unavailable ({type(e).__name__}); "
              f"Snowflake functions will fail until it is created, but the "
              f"dbt and staging functions are unaffected")
        return []


SNOW_SECRETS = VLLM_SECRET + _optional_secret("nl2sql-snowflake")
BQ_SECRETS = VLLM_SECRET + _optional_secret("nl2sql-bigquery")


# vLLM serve apps in this repo, keyed by the model their file serves. A Modal
# web_server function is reachable at
#   https://<workspace>--<app-name>-<function>.modal.run
SERVE_APPS = {"Qwen/Qwen3.5-9B": "nl2sql-vllm-qwen35",
              "Qwen/Qwen3.6-35B-A3B": "nl2sql-vllm-qwen36-35b"}


def serve_url(model: str, endpoint: str = "") -> str:
    """Resolve the actor endpoint.

    Without this a Modal run fails inside read_endpoint() looking for
    logs/vllm_endpoint.txt, a file that only ever existed on the SLURM cluster.
    """
    if endpoint:
        return endpoint
    app_name = SERVE_APPS.get(model)
    if not app_name:
        raise SystemExit(
            f"no serve app known for model {model!r}; pass endpoint= "
            f"explicitly or add it to SERVE_APPS")
    # ask Modal for the deployed function's own URL rather than guessing the
    # workspace slug (config has no "workspace" key)
    fn = modal.Function.from_name(app_name, "serve")
    url = None
    for attr in ("get_web_url", "web_url"):
        got = getattr(fn, attr, None)
        url = got() if callable(got) else got
        if url:
            break
    if not url:
        raise SystemExit(
            f"app {app_name!r} has no web URL - deploy it first: "
            f"modal deploy nl2sql-v2/modal/<its serve file>.py")
    return url.rstrip("/") + "/v1"


def _run(argv: list[str]) -> int:
    """Run a harness script from the repo dir, streaming its output to the logs."""
    import subprocess
    import sys
    print("+ " + " ".join(argv), flush=True)
    proc = subprocess.run([sys.executable, *argv], cwd=REPO)
    return proc.returncode


# ─────────────────────────── data staging ────────────────────────────────
# spider2-dbt/README.md: the project databases AND the gold databases ship as
# two Google Drive archives, unpacked by their setup.py into
# examples/<id>/*.duckdb and evaluation_suite/gold/<id>/*.duckdb. Without the
# second one the dbt lane cannot be scored at all.
# their setup.py opens these exact filenames, so gdown must write them as-is
DBT_ARCHIVES = (("1N3f7BSWC4foj-V-1C9n8M2XmgV7FOcqL", "DBT_start_db.zip"),
                ("1s0USV_iQLo4oe05QqAMnhGGp5jeejCzp", "dbt_gold.zip"))
# spider2-lite/README.md: the 135 local SQLite databases (only needed for the
# regression lane, not for snow or dbt)
LITE_SQLITE_ARCHIVE = "1coEVsCZq-Xvj9p2TnhBFoFTsY-UoYGmG"


@app.function(image=image, volumes=VOLUMES, timeout=4 * 60 * 60)
def stage_data(sqlite: bool = True, dbt: bool = True):
    """Populate /data from inside a container: nothing is uploaded from the laptop.

    The Spider2 repo itself carries the questions, the gold CSVs and the dbt projects.
    The SQLite databases (for the local regression lane) and the dbt DuckDB databases
    are separate downloads, so their locations are passed in rather than hardcoded.
    """
    import shutil
    import subprocess
    from pathlib import Path

    data = Path("/data")
    data.mkdir(parents=True, exist_ok=True)
    spider2 = data / "Spider2"
    # Downloads land on the volume, not /tmp: /tmp is a different device (so
    # os.replace across the two raises EXDEV) and it is lost between runs, which
    # would re-download gigabytes on every retry.
    staging = data / "_staging"
    staging.mkdir(parents=True, exist_ok=True)

    def fetch(file_id: str, dest: Path) -> Path:
        if dest.exists() and dest.stat().st_size > 1_000_000:
            print(f"{dest.name} already downloaded "
                  f"({dest.stat().st_size / 1e6:.0f}MB)", flush=True)
            return dest
        subprocess.run(["gdown", file_id, "-O", str(dest)], check=True)
        return dest

    if not spider2.exists():
        print("cloning Spider2 ...", flush=True)
        subprocess.run(["git", "clone", "--depth", "1",
                        "https://github.com/xlang-ai/Spider2.git", str(spider2)],
                       check=True)
    else:
        print("Spider2 already present", flush=True)

    if sqlite:
        target = spider2 / "spider2-lite/resource/databases/spider2-localdb"
        target.mkdir(parents=True, exist_ok=True)
        have = len(list(target.glob("*.sqlite")))
        if have < 31:
            print(f"staging the 135-question SQLite databases ({have} present) ...",
                  flush=True)
            zip_path = fetch(LITE_SQLITE_ARCHIVE, staging / "local_databases.zip")
            unpacked = staging / "localdb"
            subprocess.run(["unzip", "-q", "-o", str(zip_path), "-d", str(unpacked)],
                           check=True)
            for p in unpacked.rglob("*.sqlite"):
                # shutil.move, not Path.replace: these cross device boundaries
                shutil.move(str(p), str(target / p.name))
            shutil.rmtree(unpacked, ignore_errors=True)
        print(f"local SQLite databases: {len(list(target.glob('*.sqlite')))} "
              f"(expect 31)", flush=True)

    if dbt:
        dbt_dir = spider2 / "spider2-dbt"
        gold = dbt_dir / "evaluation_suite/gold"
        already = len(list(gold.glob("*/*.duckdb"))) if gold.exists() else 0
        if already:
            print(f"dbt gold databases already present: {already}", flush=True)
        else:
            for ix, (fid, fname) in enumerate(DBT_ARCHIVES):
                print(f"staging {fname} ({ix + 1}/{len(DBT_ARCHIVES)}) ...",
                      flush=True)
                src = fetch(fid, staging / fname)
                # their setup.py reads these from the spider2-dbt dir, by name
                shutil.copy2(str(src), str(dbt_dir / fname))
            print("running their setup.py ...", flush=True)
            proc = subprocess.run(["python", "setup.py"], cwd=str(dbt_dir),
                                  capture_output=True, text=True)
            print(f"setup.py exit={proc.returncode}", flush=True)
            tail = (proc.stdout or "").splitlines()[-15:]
            for line in tail:
                print("  " + line, flush=True)
            if proc.returncode != 0:
                print("  stderr: " + (proc.stderr or "")[-800:], flush=True)
        n_proj = len(list((dbt_dir / "examples").glob("*/*.duckdb")))
        n_gold = len(list(gold.glob("*/*.duckdb"))) if gold.exists() else 0
        print(f"dbt project databases: {n_proj}", flush=True)
        print(f"dbt gold databases   : {n_gold} (expect 68)", flush=True)
        if n_gold == 0:
            print("BLOCKER: without the gold databases the dbt lane cannot be "
                  "scored at all", flush=True)

    spider2_data.commit()
    print("\n== census ==", flush=True)
    _run(["scripts/census_targets.py",
          "--write-unscoreable", "/data/unscoreable.txt"])
    spider2_data.commit()


# ─────────────────────────── the SQLite regression lane ──────────────────
@app.function(image=image, volumes=VOLUMES, secrets=VLLM_SECRET, timeout=2 * 60 * 60)
def smoke(endpoint: str = "", model: str = "Qwen/Qwen3.6-35B-A3B",
          instances: str = "local002,local007"):
    """Prove the venue before trusting the refactor: run the known-good local lane.

    Separating "Modal works" from "the new code works" is worth one cheap run.
    """
    if _run(["scripts/check_all.py"]):
        raise SystemExit("offline checks failed; fix those before spending GPU time")
    argv = ["scripts/run_benchmark.py", "--schema-overview",
            "--instances", instances,
            "--output", "/results/modal_smoke.csv",
            "--trace-dir", "/results/traces/modal_smoke",
            "--model", model, "--context-mode", "full",
            "--endpoint", serve_url(model, endpoint)]
    rc = _run(argv)
    results.commit()
    return rc


# ─────────────────────────── Snowflake ───────────────────────────────────
@app.function(image=embed_image, volumes=VOLUMES, gpu="L4",
              timeout=4 * 60 * 60)
def bq_index(source: str = "spider2_lite_bq", embedder: str = "bge",
             force: bool = False, db: str = ""):
    """Synthesise the retrieval index for a warehouse lane onto /results.

    Free of warehouse cost and of LLM calls: every field comes from the catalog
    spider2-lite ships. See scripts/build_bq_context.py for why that is enough on
    BigQuery but not on SQLite.
    """
    # --out is left off: NL2SQL_CONTEXT_DIR already points both the builder and
    # the benchmark shards at the same place
    argv = ["scripts/build_bq_context.py", "--source", source,
            "--embedder", embedder]
    if db:
        for one in db.split(","):
            argv += ["--db", one]
    else:
        argv.append("--all")
    if force:
        argv.append("--force")
    rc = _run(argv)
    results.commit()
    return rc


@app.function(image=embed_image, volumes=VOLUMES, gpu="L4", timeout=60 * 60)
def bq_recall(source: str = "spider2_lite_bq", k: int = 8, verbose: bool = True):
    """Recall@k of the retrieval index against the official gold SQL.

    The gate before a retrieval lane: spider2-lite ships gold SQL for 148 of the 204
    BigQuery instances, so this measures whether search_context actually surfaces
    the tables the answer needs, rather than whether it is merely wired up.
    """
    results.reload()
    argv = ["scripts/check_retrieval_recall.py", "--source", source, "-k", str(k)]
    if verbose:
        argv.append("--verbose")
    return _run(argv)


@app.function(image=image, volumes=VOLUMES, secrets=BQ_SECRETS, timeout=60 * 60)
def bq_preflight(source: str = "spider2_lite_bq", limit_dbs: int = 0):
    """Which BigQuery databases can we actually reach? All probes are dry runs,
    so this is free -- and it decides the denominator before any GPU is used."""
    argv = ["scripts/bigquery_preflight.py", "--source", source,
            "--write-unreachable", "/results/bq_unreachable.txt"]
    if limit_dbs:
        argv += ["--limit-dbs", str(limit_dbs)]
    rc = _run(argv)
    results.commit()
    return rc


@app.function(image=image, volumes=VOLUMES, secrets=BQ_SECRETS,
              timeout=24 * 60 * 60)
def bq_rubric(endpoint: str = "", model: str = "Qwen/Qwen3.6-35B-A3B",
              out_dir: str = "/results/rubric_bq", instances: str = ""):
    """The output-shape rubric for every BigQuery question (nl2sql/rubric.py).

    Free of warehouse cost: list_tables/describe_table read the catalog spider2-lite
    ships as JSON, and rubric.py withholds get_column_values and find_value from
    non-SQLite dialects. run_rubric.py prints the scan total so the claim is checked
    rather than assumed -- it must say 0 B.
    """
    argv = ["scripts/run_rubric.py", "--source", "spider2_lite_bq",
            "--out-dir", out_dir, "--model", model, "--resume",
            "--endpoint", serve_url(model, endpoint)]
    if instances:
        argv += ["--instances", instances]
    rc = _run(argv)
    results.commit()
    return rc


@app.function(image=image, volumes=VOLUMES, secrets=BQ_SECRETS,
              timeout=24 * 60 * 60)
def bq_shard(instances: list, shard_ix: int, tag: str, endpoint: str,
             model: str, max_steps: int, temperature: float,
             rubric_dir: str = "", confident_only: bool = True,
             retrieval: bool = False):
    argv = ["scripts/run_benchmark.py",
            "--source", "spider2_lite_bq",
            "--schema-overview", "--context-mode", "full",
            "--instances", ",".join(instances),
            "--output", f"/results/{tag}/shard{shard_ix:02d}.csv",
            "--trace-dir", f"/results/{tag}/traces",
            "--run-tag", tag,
            "--model", model, "--max-steps", str(max_steps),
            "--temperature", str(temperature), "--resume",
            "--endpoint", serve_url(model, endpoint)]
    if retrieval:
        # additive, not instead of the dump: see run_benchmark.py --retrieval
        argv.append("--retrieval")
    if rubric_dir:
        argv += ["--rubric-dir", rubric_dir]
        if confident_only:
            argv.append("--rubric-confident-only")
    rc = _run(argv)
    results.commit()
    return rc


@app.function(image=image, volumes=VOLUMES, secrets=BQ_SECRETS,
              timeout=24 * 60 * 60)
def bq(endpoint: str = "", model: str = "Qwen/Qwen3.6-35B-A3B",
       tag: str = "bq_run", shards: int = 1, limit: int = 0,
       max_steps: int = 60, temperature: float = 0.0,
       rubric_dir: str = "", confident_only: bool = True,
       retrieval: bool = False):
    """The spider2-lite BigQuery lane (bq###/ga###). `limit` takes a stratified
    slice for calibration; `shards` fans out, split by database so the catalog and
    BigQuery query cache stay warm within a shard."""
    buckets = _shard_by_db("spider2_lite_bq", shards, limit)
    # bq_preflight writes the instances whose GCP project we cannot reach; running
    # them spends a full episode to earn a guaranteed 403, so drop them here and
    # report against the reachable denominator.
    from pathlib import Path as _P
    blocked = set()
    bl = _P("/results/bq_unreachable.txt")
    if bl.exists():
        blocked = {ln.strip() for ln in bl.read_text().splitlines() if ln.strip()}
    if blocked:
        buckets = [[i for i in b if i not in blocked] for b in buckets]
        buckets = [b for b in buckets if b]
        print(f"excluding {len(blocked)} unreachable instance(s): "
              f"{sorted(blocked)}", flush=True)
    total = sum(len(b) for b in buckets)
    print(f"{total} instances in {len(buckets)} shard(s): "
          f"{[len(b) for b in buckets]}", flush=True)
    # 60, not 40: in bq_v2 47 of 204 episodes hit the 40-step cap and NONE of them
    # scored -- 36 ended as 'fallback' and 10 as 'no_sql', 0/46 correct. The cap was
    # a guaranteed-zero bucket, not a budget.
    codes = list(bq_shard.starmap(
        [(b, i, tag, endpoint, model, max_steps, temperature, rubric_dir,
          confident_only, retrieval)
         for i, b in enumerate(buckets)]))
    results.commit()
    print(f"merged {_merge_shards(tag)} rows into /results/{tag}/all.csv", flush=True)
    _run(["scripts/report_spend.py", f"/results/{tag}/all.csv", "--project-to", "205"])
    results.commit()
    return codes


@app.function(image=image, volumes=VOLUMES, secrets=SNOW_SECRETS, timeout=30 * 60)
def preflight(source: str = "spider2_snow_new", set_warehouse: bool = False):
    """Credentials, grants, warehouse and cost guards -- before any GPU is allocated."""
    argv = ["scripts/snowflake_preflight.py", "--source", source]
    if set_warehouse:
        argv.append("--set-warehouse")
    return _run(argv)


def _shard_by_db(source: str, shards: int, limit: int = 0) -> list[list[str]]:
    """Delegates to scripts/shard_plan.py, which check_sources.py covers."""
    import sys
    sys.path.insert(0, f"{REPO}/src")
    sys.path.insert(0, f"{REPO}/scripts")
    from shard_plan import plan
    return plan(source, shards, limit)


@app.function(image=image, volumes=VOLUMES, secrets=SNOW_SECRETS, timeout=24 * 60 * 60)
def snow_shard(instances: list[str], shard_ix: int, tag: str, endpoint: str,
               model: str, max_steps: int, temperature: float):
    argv = ["scripts/run_benchmark.py",
            "--source", "spider2_snow_new",
            "--schema-overview", "--context-mode", "full",
            "--instances", ",".join(instances),
            "--output", f"/results/{tag}/shard{shard_ix:02d}.csv",
            "--trace-dir", f"/results/{tag}/traces",
            "--describe-cache", "/results/snowflake_cache",
            "--run-tag", tag,
            "--model", model, "--max-steps", str(max_steps),
            "--temperature", str(temperature), "--resume",
            "--endpoint", serve_url(model, endpoint)]
    rc = _run(argv)
    results.commit()          # make this shard's rows visible to the merge step
    return rc


@app.function(image=image, volumes=VOLUMES, secrets=SNOW_SECRETS, timeout=24 * 60 * 60)
def snow(endpoint: str = "", model: str = "Qwen/Qwen3.6-35B-A3B",
         tag: str = "snow_run", shards: int = 1, limit: int = 0,
         max_steps: int = 30, temperature: float = 0.0,
         source: str = "spider2_snow_new"):
    """The Snowflake lane. `limit` takes a stratified slice (the calibration run);
    `shards` fans out across containers, split by database."""
    buckets = _shard_by_db(source, shards, limit)
    total = sum(len(b) for b in buckets)
    print(f"{total} instances in {len(buckets)} shard(s): "
          f"{[len(b) for b in buckets]}", flush=True)

    codes = list(snow_shard.starmap(
        [(b, i, tag, endpoint, model, max_steps, temperature)
         for i, b in enumerate(buckets)]))
    results.commit()

    merged = _merge_shards(tag)
    print(f"merged {merged} rows into /results/{tag}/all.csv", flush=True)
    _run(["scripts/report_spend.py", f"/results/{tag}/all.csv"])
    results.commit()
    return codes


def _merge_shards(tag: str) -> int:
    import csv
    from pathlib import Path
    # reload(), not just commit(): a Modal volume mount is a snapshot from when the
    # container started, so the orchestrator cannot see what the shard containers
    # committed while it waited. Without this the bq_v3 merge read 0 rows from six
    # shard CSVs that were all sitting on the volume.
    results.reload()
    d = Path("/results") / tag
    shard_files = sorted(d.glob("shard*.csv"))
    rows, fieldnames = [], None
    for p in shard_files:
        with open(p, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            fieldnames = fieldnames or r.fieldnames
            rows.extend(list(r))
    if not rows:
        return 0
    with open(d / "all.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


# ─────────────────────────── dbt ─────────────────────────────────────────
@app.function(image=image, volumes=VOLUMES, secrets=VLLM_SECRET, timeout=24 * 60 * 60)
def dbt(endpoint: str = "", model: str = "Qwen/Qwen3.6-35B-A3B",
        tag: str = "dbt_run", smallest: int = 0, instances: str = "",
        max_steps: int = 40, score: bool = True,
        only_scoreable: bool = False):
    """The dbt lane. Needs no Snowflake credentials, so it can run while access
    to the warehouse is still pending."""
    argv = ["scripts/run_dbt_benchmark.py",
            "--submission", f"/results/{tag}",
            "--trace-dir", f"/results/{tag}/traces",
            "--run-tag", tag, "--model", model,
            "--max-steps", str(max_steps), "--resume",
            "--endpoint", serve_url(model, endpoint)]
    if only_scoreable:
        argv += ["--only-scoreable"]
    if smallest:
        argv += ["--smallest", str(smallest)]
    if instances:
        argv += ["--instances", instances]
    rc = _run(argv)
    results.commit()
    if score:
        _run(["scripts/score_dbt.py", f"/results/{tag}"])
        results.commit()
    return rc


@app.function(image=image, volumes=VOLUMES, timeout=60 * 60)
def dbt_gate():
    """The environment gate: Spider2's own evaluator must score its own gold.
    If gold does not self-score, nothing we produce can be trusted."""
    code = _run(["scripts/check_all.py"])
    code |= _run(["scripts/score_dbt.py", "/results/unused", "--self-test"])
    return code


@app.local_entrypoint()
def main():
    print(__doc__)
