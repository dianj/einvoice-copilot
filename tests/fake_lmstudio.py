"""A scripted, in-process stand-in for LM Studio's OpenAI-compatible API with structured outputs.

Tests queue the model's next JSON answer per schema name (`script("route", {...})`), or a function of the request
for answers that depend on the prompt. Like LM Studio's grammar-constrained output, the fake only returns JSON that
matches the request's `json_schema`: a scripted answer that does not is reported as a test error (HTTP 500).
Every request is recorded for assertions.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def schema_errors(value, schema: dict, path: str = "$") -> list[str]:
    """Just enough JSON Schema for this project's schemas: type, enum, properties, required, items, maxItems."""
    errors = []
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float)}
    if kind and not isinstance(value, types[kind]):
        return [f"{path}: expected {kind}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if kind == "object":
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errors += [f"{path}: unexpected {key}" for key in value if key not in props]
        for key, sub in props.items():
            if key in value:
                errors += schema_errors(value[key], sub, f"{path}.{key}")
    if kind == "array":
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        for i, item in enumerate(value):
            errors += schema_errors(item, schema.get("items", {}), f"{path}[{i}]")
    return errors


class FakeLMStudio:
    def __init__(self):
        self.queues: dict[str, list] = {}
        self.requests: list[dict] = []
        self.errors: list[str] = []
        self.fail_count = 0              # answer the next N completions with HTTP 500 (an outage)
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}/v1"

    def reset(self):
        with self.lock:
            self.queues.clear()
            self.requests.clear()
            self.errors.clear()
            self.fail_count = 0

    def script(self, name: str, *answers):
        """Queue answers for the schema `name`: dicts, or functions (request payload -> dict)."""
        with self.lock:
            self.queues.setdefault(name, []).extend(answers)

    def calls(self, name: str) -> list[dict]:
        return [r for r in self.requests if r.get("response_format", {}).get("json_schema", {}).get("name") == name]

    def pending(self) -> dict:
        return {name: len(q) for name, q in self.queues.items() if q}

    def _answer(self, payload: dict) -> tuple[int, dict]:
        with self.lock:
            self.requests.append(payload)
            if self.fail_count > 0:
                self.fail_count -= 1
                return 500, {"error": "simulated outage"}
            spec = payload.get("response_format", {}).get("json_schema", {})
            name = spec.get("name", "")
            queue = self.queues.get(name) or []
            if not queue:
                self.errors.append(f"no scripted answer for '{name}'")
                return 500, {"error": f"no scripted answer for '{name}'"}
            answer = queue.pop(0)
        data = answer(payload) if callable(answer) else answer
        problems = schema_errors(data, spec.get("schema", {}))
        if problems:
            with self.lock:
                self.errors.append(f"{name}: {problems}")
            return 500, {"error": f"scripted answer does not match the schema: {problems}"}
        return 200, {"id": "chatcmpl-fake", "object": "chat.completion", "model": payload.get("model"),
                     "choices": [{"index": 0, "finish_reason": "stop",
                                  "message": {"role": "assistant", "content": json.dumps(data)}}],
                     "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802 (http.server API)
                if self.path.endswith("/models"):
                    self._send(200, {"object": "list", "data": [{"id": "gemma-4-26b-a4b-it"}]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):  # noqa: N802
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if self.path.endswith("/chat/completions"):
                    self._send(*fake._answer(payload))
                else:
                    self._send(404, {"error": "not found"})

            def log_message(self, *args):
                pass

        return Handler


# --- helpers for scripting answers that depend on the prompt ---------------------------------------------------

def enum_of(payload: dict, *path: str) -> list:
    """The enum at a path of the request's schema, e.g. enum_of(p, "explanations", "rule_id")."""
    node = payload["response_format"]["json_schema"]["schema"]
    for key in path:
        node = node["properties"][key]
        if node.get("type") == "array":
            node = node["items"]
    return node["enum"]


def user_prompt(payload: dict) -> str:
    return payload["messages"][-1]["content"]


def system_prompt(payload: dict) -> str:
    return payload["messages"][0]["content"]
