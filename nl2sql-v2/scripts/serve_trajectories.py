#!/usr/bin/env python3
"""Serve converted trajectories with CORS so the trajectory-visualizer can fetch
them by URL (?fileUrl=...). Python's http.server sends no CORS header, and the
visualizer runs on a different port, so a plain static server fails the fetch.

The "gold" column says what comparison material each episode carries: "diff" for the
expected-vs-submitted diff, "+ SQL" when the benchmark also ships official gold SQL
for that question (only 24 of the 135 locals do).

Also serves a clickable index at / listing every converted episode, so you can
jump straight to a question instead of hunting for filenames.

Usage (from nl2sql-v2/):
    uv run python scripts/serve_trajectories.py --dir ../logs/openhands --port 8008
"""

import argparse
import html
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VIEWER = "http://localhost:12000"


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._index()
        return super().do_GET()

    def _index(self):
        root = Path(self.directory)
        try:
            rows = json.loads((root / "index.json").read_text())
        except (OSError, ValueError):
            rows = []
        host = self.headers.get("Host", f"localhost:{self.server.server_port}")
        parts = [
            "<!doctype html><meta charset=utf-8><title>Trajectories</title>",
            "<style>body{font:14px system-ui;margin:2rem;max-width:1100px}"
            "table{border-collapse:collapse;width:100%}td,th{padding:4px 8px;"
            "border-bottom:1px solid #ddd;text-align:left;vertical-align:top}"
            "tr:hover{background:#f6f6f6}.f{color:#b00}.p{color:#070}"
            "code{font:12px ui-monospace}</style>",
            f"<h2>{len(rows)} trajectories"
            f" &middot; {sum(1 for r in rows if r.get('score') != 1)} failed</h2>",
            "<p>Viewer must be running: <code>npm start</code> in trajectory-visualizer "
            f"(<a href='{VIEWER}'>{VIEWER}</a>).</p>",
            "<table><tr><th>run<th>question<th>outcome<th>detail<th>gold<th>text",
        ]
        for r in rows:
            url = f"http://{host}/{r['path']}"
            ok = r.get("score") == 1
            parts.append(
                f"<tr><td>{html.escape(r['run'])}"
                f"<td><a href=\"{VIEWER}/?fileUrl={url}\">{html.escape(r['instance'])}</a>"
                f"<td class={'p' if ok else 'f'}>{'correct' if ok else 'FAILED'}"
                f" {html.escape(str(r.get('status') or ''))}"
                f"<td>{html.escape(str(r.get('detail') or ''))}"
                f"<td>{'diff' if r.get('has_gold_diff') else ''}"
                f"{' + SQL' if r.get('has_gold_sql') else ''}"
                f"<td>{html.escape(r.get('question') or '')}")
        body = "\n".join(parts).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
    print(f"serving {root} at http://localhost:{args.port}  (index at /)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
