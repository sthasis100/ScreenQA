"""
fake_ai_server.py - a pretend AI service running on this PC (127.0.0.1).

It speaks the same "OpenAI-compatible" language as Groq, so ScreenQA's real
code can talk to it. Tests tell it what to answer - including errors such as
"rate limit reached" or "server error" - without contacting any real service.
"""

import dataclasses
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from screenqa.providers import GROQ


class FakeAIServer:
    def __init__(self) -> None:
        self.responses: list[tuple] = []  # (status, body, headers, delay); the last one repeats
        self.requests: list[dict] = []  # every request body received, for checking
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())  # port 0 = any free port
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        port = self._server.server_address[1]
        # A copy of the Groq provider that points at this fake server instead.
        self.provider = dataclasses.replace(GROQ, base_url=f"http://127.0.0.1:{port}/v1")

    def respond(self, *responses: tuple) -> None:
        """Set the next answer(s). Each is (status, body, headers, delay_seconds)."""
        self.responses = list(responses)
        self.requests = []

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _handler_class(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output quiet
                pass

            def do_POST(self):
                fake.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                status, body, headers, delay = fake.responses.pop(0) if len(fake.responses) > 1 else fake.responses[0]
                time.sleep(delay)
                data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    for key, value in headers.items():
                        self.send_header(key, value)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # ScreenQA gave up waiting (timeout test) - that's fine

        return Handler


def reply(text: str, finish: str = "stop") -> tuple:
    """A normal successful answer."""
    body = {"id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}]}
    return 200, body, {}, 0


def error(status: int, message: str, code: str = "some_error", headers: dict | None = None, delay: float = 0) -> tuple:
    """An error answer, shaped like the ones real services send."""
    body = {"error": {"message": message, "type": "invalid_request_error", "code": code}}
    return status, body, headers or {}, delay
