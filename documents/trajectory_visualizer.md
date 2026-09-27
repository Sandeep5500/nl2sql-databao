# Viewing episodes in the OpenHands trajectory-visualizer

An alternative to `inspect view` for reading a single episode closely: a timeline with
collapsible tool calls, syntax-highlighted SQL, dark mode and keyboard navigation.
Two scripts convert our traces into the format it expects and serve them.

Repo: https://github.com/All-Hands-AI/trajectory-visualizer
(the `OpenHands/trajectory-visualizer` URL redirects here).

## One-time setup

The dev server needs **Node 20.19+ or 22.12+**. Node 20.10 fails with
`node:util does not provide an export named 'styleText'`. A self-contained Node avoids
touching anything global:

```
cd <somewhere outside the repo>            # e.g. Capstone/tools
V=$(curl -sSL https://nodejs.org/dist/index.json \
    | python3 -c "import json,sys;print([x['version'] for x in json.load(sys.stdin) if x['version'].startswith('v22.') and x.get('lts')][0])")
curl -sSL "https://nodejs.org/dist/$V/node-$V-darwin-arm64.tar.xz" | tar -xJ
ln -sfn "node-$V-darwin-arm64" node
export PATH="$PWD/node/bin:$PATH"          # needed in every shell that runs npm
```

Then clone and install **with that Node on PATH**:

```
git clone https://github.com/All-Hands-AI/trajectory-visualizer.git
cd trajectory-visualizer && npm install
```

Installing with an older npm first leaves a broken optional dependency
(`Cannot find module '@rolldown/binding-darwin-arm64'`). If that happens,
`rm -rf node_modules package-lock.json && npm install` with the new Node fixes it.

## Each session

Three commands, in three shells (or background the first two):

```
# 1. the viewer  -- NB it serves on 12000, not the 3000 the README claims
cd trajectory-visualizer && export PATH=.../node/bin:$PATH && npm start

# 2. convert the episodes you want to read
cd nl2sql-v2
uv run python scripts/analysis/to_openhands.py --runs 'q36_pass4_k*' --out ../logs/openhands
uv run python scripts/analysis/to_openhands.py --runs q36_pass4_k4 --failures-only
uv run python scripts/analysis/to_openhands.py --runs v2_pass4_k1,teacher_p1_* --instances local031

# 3. serve them with CORS, and get a clickable index
uv run python scripts/serve_trajectories.py --dir ../logs/openhands --port 8008
```

Open **http://localhost:8008** for the index: one row per episode with its outcome,
status and question, each linking into the viewer. Direct link form:

```
http://localhost:12000/?fileUrl=http://localhost:8008/q36_pass4_k4/local031.json
```

`logs/openhands/` is gitignored and regenerable, so it is never committed.

## How our traces are mapped

The viewer dispatches on `(source, action|observation)` and only the handlers wired
into `trajectory-list.tsx` render specially -- anything else becomes a raw-JSON card.
So each of our tools is mapped onto a handler that exists:

| ours | becomes | renders as |
|---|---|---|
| the question | user message | conversation opener |
| `system` prompt | a plain item, `source: "system"` | raw-JSON card, collapsed by default |
| `run_sql_query` | `run_ipython`, `args.code` | syntax-highlighted SQL block |
| every other tool | `run`, `args.command = "tool(arg=value)"` | command block |
| a result starting `ERROR` | `observation: "error"` | red error card |
| assistant prose | assistant message | speech bubble |
| `reasoning`, when present | assistant message prefixed `[reasoning]` | speech bubble |
| final SQL + score | `finish` action | outcome card |

Verified against the app's own type guards: of 2,853 events across 60 episodes, the
only ones that fall back to a raw-JSON card are the 60 system prompts (one each).

Two deliberate choices:

- **Reasoning is folded into assistant messages.** `think` actions exist in the
  viewer's types and have a component, but `trajectory-list.tsx` never dispatches
  them, so a real `action: "think"` would render as raw JSON. Only matters for runs
  that captured reasoning -- see below.
- **Timestamps are synthesised** one second apart, because our traces carry none.
  Ordering is meaningful, durations are not.

## Which runs have reasoning

Only runs made from a branch whose `agent.py` stores it, and with `--thinking` on.
`origin/main`'s `agent.py` does not capture reasoning at all, so the `q36_pass4_k*`
(35B) traces contain none -- 0 of 18,632 events. `think_k*` has it; the rest do not.
