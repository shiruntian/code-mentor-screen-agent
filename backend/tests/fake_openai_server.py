"""一个极小的 OpenAI 兼容假服务，用于验证「任意模型名」与「动态模型列表」链路。

用途（测试用，不参与生产）：
    python tests/fake_openai_server.py 8899
然后把它当成「自定义 OpenAI 兼容端点」接入：Base URL = http://127.0.0.1:8899/v1

支持：
    GET  /v1/models            返回一组"未来才发布"的模型名
    POST /v1/chat/completions  非流式 JSON + 流式 SSE
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = [
    {"id": "deepseek-v4-pro", "object": "model", "owned_by": "deepseek"},
    {"id": "deepseek-v4.1-flash", "object": "model", "owned_by": "deepseek"},
    {"id": "qwen3-vl-plus", "object": "model", "owned_by": "qwen"},
]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        print(f"[fake] {fmt % args}", flush=True)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            self._json({"object": "list", "data": MODELS})
        else:
            self._json({"error": {"message": "not found"}}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        model = payload.get("model", "deepseek-v4.1-flash")
        stream = bool(payload.get("stream"))

        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            chunks = [
                "### 先说结论\n\n",
                f"这是本地假服务（模型 {model}）返回的流式内容。\n\n",
                "```python\nprint('hello from fake model')\n```\n\n",
                "### 下一步\n\n1. 打开编辑器新建 demo.py\n2. 粘贴上面的代码并运行\n3. 观察终端输出\n",
            ]
            for text in chunks:
                event = {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                }
                data = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
                self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()
                time.sleep(0.02)
            done = b"data: [DONE]\n\n"
            self.wfile.write(f"{len(done):X}\r\n".encode() + done + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return

        self._json(
            {
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": f"fake reply from {model}"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    print(f"[fake] OpenAI 兼容假服务已启动: http://127.0.0.1:{port}/v1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()