#!/usr/bin/env python3
"""Serve converted trajectories with CORS so the trajectory-visualizer can fetch
them by URL (?fileUrl=...). Python's http.server sends no CORS header, and the
visualizer runs on a different port, so a plain static server fails the fetch.

Two tabs:

  /           every converted episode, clickable through to the viewer
  /analysis   the aggregate error analysis for a run

The Analysis tab renders whatever analyze_warehouse_traces.py --json wrote next to
the trajectories, rather than recomputing anything, so the tab and the CLI can never
disagree:

    uv run python scripts/analyze_warehouse_traces.py ../logs/traces/bq_v2 \
        --run ../results/bq_v2_run.csv --json ../logs/openhands/bq_v2.analysis.json

The "search" column says whether semantic retrieval actually worked in that episode:
two runs can be the same model differing only in that, and their episodes otherwise
look identical, so it is easy to read the wrong one. "BROKEN" means every
search_context call in that episode errored; "n/a" means the lane had no retrieval at
all, which is a different thing.

The "gold" column says what comparison material each episode carries: "diff" for the
expected-vs-submitted diff, "+ SQL" when the benchmark also ships official gold SQL
for that question (only 24 of the 135 locals do).

Usage (from nl2sql-v2/):
    uv run python scripts/serve_trajectories.py --dir ../logs/openhands --port 8008
"""

import argparse
import html
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VIEWER = "http://localhost:12000"
GiB = 1024.0 ** 3

CSS = """body{font:14px system-ui;margin:2rem;max-width:1200px}
table{border-collapse:collapse;width:100%;margin-bottom:1.5rem}
td,th{padding:4px 8px;border-bottom:1px solid #ddd;text-align:left;
vertical-align:top}th{background:#fafafa}
tr:hover{background:#f6f6f6}.f{color:#b00}.p{color:#070}
.num{text-align:right;font-variant-numeric:tabular-nums}
code{font:12px ui-monospace}
nav{margin-bottom:1.5rem;border-bottom:2px solid #ddd;padding-bottom:.5rem}
nav a{margin-right:1.2rem;text-decoration:none;color:#555;font-weight:600}
nav a.on{color:#000;border-bottom:2px solid #000;padding-bottom:.5rem}
.old{color:#999;font-size:11px}.note{color:#555;margin:-1rem 0 1.5rem;font-size:13px}
h3{margin-bottom:.4rem}"""


def _nav(active: str, runs: list[str]) -> str:
    tabs = [("/", "Trajectories", "traj"), ("/analysis", "Analysis", "analysis")]
    out = ["<nav>"]
    for href, label, key in tabs:
        cls = " class=on" if key == active else ""
        out.append(f"<a href='{href}'{cls}>{label}</a>")
    out.append("</nav>")
    return "".join(out)


def _page(title: str, active: str, body: str, runs: list[str]) -> bytes:
    return (f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
            f"<style>{CSS}</style>{_nav(active, runs)}{body}").encode()


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # ── helpers ───────────────────────────────────────────────────────────
    @property
    def _root(self) -> Path:
        return Path(self.directory)

    def _index_rows(self) -> list[dict]:
        try:
            return json.loads((self._root / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _reports(self) -> dict:
        """run name -> analysis json path, from *.analysis.json beside the trajectories."""
        return {p.name[: -len(".analysis.json")]: p
                for p in sorted(self._root.glob("*.analysis.json"))}

    def _send(self, body: bytes, ctype="text/html; charset=utf-8"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── routing ───────────────────────────────────────────────────────────
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(self._traj_page())
        if path == "/analysis":
            q = parse_qs(urlparse(self.path).query)
            return self._send(self._analysis_page(q.get("run", [None])[0]))
        return super().do_GET()

    # ── the trajectories tab ──────────────────────────────────────────────
    def _traj_page(self) -> bytes:
        rows = self._index_rows()
        host = self.headers.get("Host", f"localhost:{self.server.server_port}")
        failed = sum(1 for r in rows if r.get("score") != 1)
        parts = [f"<h2>{len(rows)} trajectories &middot; {failed} failed</h2>"]
        if any(r.get("recency") == "superseded" for r in rows):
            parts.append(
                "<p class=note><b>Newest run first.</b> Rows marked "
                "<span class=old>superseded</span> come from an earlier run of the "
                "same model and are kept only for comparison &mdash; check the "
                "<b>search</b> column before reading one.</p>")
        parts.append(
            "<p class=note>Viewer must be running: <code>npm start</code> in "
            f"trajectory-visualizer (<a href='{VIEWER}'>{VIEWER}</a>).</p>")
        parts.append("<table><tr><th>run<th>question<th>outcome<th>detail"
                     "<th class=num>steps<th class=num>calls<th class=num>GiB"
                     "<th>search<th>gold<th>text</tr>")
        for r in rows:
            url = f"http://{host}/{r['path']}"
            ok = r.get("score") == 1
            sup = r.get("recency") == "superseded"
            try:
                scan = f"{float(r.get('scan_bytes') or 0) / GiB:.2f}"
            except (TypeError, ValueError):
                scan = ""
            parts.append(
                f"<tr><td>{html.escape(str(r.get('run', '')))}"
                f"{' <span class=old>superseded</span>' if sup else ''}"
                f"<td><a href=\"{VIEWER}/?fileUrl={url}\">"
                f"{html.escape(str(r.get('instance', '')))}</a>"
                f"<td class={'p' if ok else 'f'}>{'correct' if ok else 'FAILED'}"
                f" {html.escape(str(r.get('status') or ''))}"
                f"<td>{html.escape(str(r.get('detail') or ''))}"
                f"<td class=num>{html.escape(str(r.get('steps') or ''))}"
                f"<td class=num>{html.escape(str(r.get('tool_calls') or ''))}"
                f"<td class=num>{scan}"
                f"<td class={'f' if r.get('search') == 'BROKEN' else ''}>"
                f"{html.escape(str(r.get('search') or ''))}"
                f"<td>{'diff' if r.get('has_gold_diff') else ''}"
                f"{' + SQL' if r.get('has_gold_sql') else ''}"
                f"<td>{html.escape(r.get('question') or '')}</tr>")
        parts.append("</table>")
        return _page("Trajectories", "traj", "\n".join(parts), [])

    # ── the analysis tab ──────────────────────────────────────────────────
    def _analysis_page(self, run: str | None) -> bytes:
        reports = self._reports()
        if not reports:
            return _page("Analysis", "analysis",
                         "<h2>No analysis yet</h2><p class=note>Write one beside the "
                         "trajectories:</p><pre><code>uv run python "
                         "scripts/analyze_warehouse_traces.py ../logs/traces/&lt;run&gt; "
                         "\\\n    --run ../results/&lt;run&gt;_run.csv \\\n    --json "
                         "../logs/openhands/&lt;run&gt;.analysis.json</code></pre>", [])
        run = run if run in reports else next(iter(reports))
        try:
            rep = json.loads(reports[run].read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return _page("Analysis", "analysis",
                         f"<h2>Could not read {html.escape(run)}</h2>"
                         f"<p class=note>{html.escape(str(exc))}</p>", [])

        m = rep.get("meta", {})
        parts = [f"<h2>{html.escape(run)} &middot; {m.get('correct')}/"
                 f"{m.get('episodes')} = {m.get('accuracy_pct')}%</h2>"]
        if len(reports) > 1:
            links = " &middot; ".join(
                f"<a href='/analysis?run={r}'>{html.escape(r)}</a>" if r != run
                else f"<b>{html.escape(r)}</b>" for r in reports)
            parts.append(f"<p class=note>runs: {links}</p>")
        parts.append(f"<p class=note>traces <code>"
                     f"{html.escape(str(m.get('trace_dir')))}</code> &middot; "
                     f"results <code>{html.escape(str(m.get('run_csv')))}</code></p>")

        for s in rep.get("sections", []):
            parts.append(f"<h3>{html.escape(s.get('title', ''))}</h3>")
            cols = s.get("columns", [])
            parts.append("<table><tr>" + "".join(
                f"<th>{html.escape(str(c))}" for c in cols) + "</tr>")
            for row in s.get("rows", []):
                cells = []
                for c in row:
                    num = isinstance(c, (int, float)) or (
                        isinstance(c, str) and c.replace(".", "", 1)
                        .replace("%", "").replace("+/-", "").isdigit())
                    cells.append(f"<td class={'num' if num else ''}>"
                                 f"{html.escape('' if c is None else str(c))}")
                parts.append("<tr>" + "".join(cells) + "</tr>")
            parts.append("</table>")
            if s.get("note"):
                parts.append(f"<p class=note>{html.escape(s['note'])}</p>")
        return _page("Analysis", "analysis", "\n".join(parts), list(reports))

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="../logs/openhands")
    ap.add_argument("--port", type=int, default=8008)
    args = ap.parse_args()
    root = Path(args.dir).resolve()
    if not root.is_dir():
        raise SystemExit(f"{root} does not exist -- run to_openhands.py first")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port),
                              partial(Handler, directory=str(root)))
    print(f"serving {root} at http://localhost:{args.port}")
    print(f"  trajectories  http://localhost:{args.port}/")
    print(f"  analysis      http://localhost:{args.port}/analysis")
    srv.serve_forever()


if __name__ == "__main__":
    main()
