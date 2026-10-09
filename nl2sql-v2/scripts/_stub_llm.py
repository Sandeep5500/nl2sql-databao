"""A scripted OpenAI-compatible endpoint, so an episode can be driven without a GPU.

Used by check_sqlite_episode.py and check_dbt_episode.py: both run the real
agent.run_episode, which is the only way to verify the loop's integration points
(the tool list it advertises, the system prompt it builds, the submit path).
"""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Captured:
    """What the harness sent on its first call, for assertions."""

    def __init__(self):
        self.system = None
        self.tools = []
        self.calls = 0


@contextmanager
def scripted_llm(script):
    """Serve `script` -- a list of (tool_name, args) -- one tool call per request.

    Yields (base_url, captured). After the script is exhausted the stub replies with
    plain content so the loop terminates instead of hanging.
    """
    cap = Captured()
    state = {"step": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            cap.calls += 1
            if cap.system is None:
                cap.system = body["messages"][0]["content"]
                cap.tools = [t["function"]["name"] for t in body.get("tools", [])]

            ix = state["step"]
            state["step"] += 1
            if ix < len(script):
                name, args = script[ix]
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": f"call_{ix}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)}}]}
                finish = "tool_calls"
            else:
                message, finish = {"role": "assistant", "content": "done"}, "stop"

            raw = json.dumps({
                "id": "stub", "object": "chat.completion", "created": 0,
                "model": "stub",
                "choices": [{"index": 0, "message": message,
                             "finish_reason": finish}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                          "total_tokens": 2}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/v1", cap
    finally:
        srv.shutdown()
        srv.server_close()
