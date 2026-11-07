"""兼容旧式 XML 工具调用。

有些模型（尤其是 Qwen 系在部分 OpenAI 兼容端点上）会退化成下面这种**纯文本**格式，
而不是标准的 `tool_calls` 字段：

    <tool_call>
    <function=list_dir>
    <parameter=path>
    E:\\项目\\demo
    </parameter>
    <parameter=depth>
    3
    </parameter>
    </function>
    </tool_call>

后果有两个：
1. 这段 XML 会被当成答案流式输出，学习者看到一堆乱码标签；
2. 本来该执行的工具不会执行。

这里提供两件东西：
- `parse_legacy_tool_calls()`：把这种文本解析成结构化调用，让工具照常执行；
- `LegacyTagFilter`：流式过滤，把未解析/未闭合的标签块从答案里抹掉。
"""

from __future__ import annotations

import json
import re
from typing import Any

_OPEN = "<tool_call>"
_CLOSE = "</tool_call>"

_FUNC_RE = re.compile(r"<function\s*=\s*([A-Za-z_][\w.]*)\s*>(.*?)</function>", re.S)
_PARAM_RE = re.compile(r"<parameter\s*=\s*([A-Za-z_][\w.]*)\s*>(.*?)</parameter>", re.S)
_LOOSE_PARAM_RE = re.compile(r"<parameter\s*=\s*([A-Za-z_][\w.]*)\s*>\s*([^<]*?)\s*$", re.M)


def _coerce(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        return ""
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    if text.lower() in ("null", "none"):
        return None
    try:
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        if re.fullmatch(r"-?\d+\.\d+", text):
            return float(text)
    except Exception:  # noqa: BLE001
        pass
    if text[:1] in "[{" and text[-1:] in "]}":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


def has_legacy_calls(text: str) -> bool:
    if not text:
        return False
    return _OPEN in text or "<function=" in text


def parse_legacy_tool_calls(text: str) -> list[dict[str, Any]]:
    """把 `<tool_call>` 文本解析成 [{name, args, id}]；解析不出就返回空列表。"""
    if not has_legacy_calls(text or ""):
        return []

    calls: list[dict[str, Any]] = []
    blocks = re.findall(r"<tool_call>(.*?)</tool_call>", text, re.S) or [text]
    for block in blocks:
        for match in _FUNC_RE.finditer(block):
            name = match.group(1).strip()
            body = match.group(2)
            args: dict[str, Any] = {}
            for pname, pvalue in _PARAM_RE.findall(body):
                args[pname.strip()] = _coerce(pvalue)
            if not args:
                # 兜底：有的模型漏写 </parameter>
                for pname, pvalue in _LOOSE_PARAM_RE.findall(body):
                    args.setdefault(pname.strip(), _coerce(pvalue))
            calls.append(
                {
                    "name": name,
                    "args": args,
                    "id": f"legacy_{len(calls)}",
                    "type": "tool_call",
                }
            )
    return calls


class LegacyTagFilter:
    """流式过滤：把 `<tool_call>…</tool_call>` 与 `<function=…>` 段从可见文本里去掉。"""

    STARTS = (_OPEN, "<function=")

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._buf += chunk
        out: list[str] = []
        guard = 0
        while guard < 64:
            guard += 1
            if self._inside:
                index = self._buf.find(_CLOSE)
                if index < 0:
                    # 仍未闭合：先压着，等后续片段
                    return "".join(out)
                self._buf = self._buf[index + len(_CLOSE) :]
                self._inside = False
                continue

            hits = [(self._buf.find(token), token) for token in self.STARTS]
            hits = [(pos, token) for pos, token in hits if pos >= 0]
            if not hits:
                # 末尾可能是半个标签，先扣着
                keep = 0
                for token in self.STARTS:
                    for size in range(1, len(token)):
                        if self._buf.endswith(token[:size]):
                            keep = max(keep, size)
                if keep:
                    out.append(self._buf[:-keep])
                    self._buf = self._buf[-keep:]
                else:
                    out.append(self._buf)
                    self._buf = ""
                break

            pos, _token = min(hits)
            out.append(self._buf[:pos])
            self._buf = self._buf[pos:]
            self._inside = True
        return "".join(out)

    def flush(self) -> str:
        """结束时把残留吐出来（未闭合的标签块直接丢弃）。"""
        if self._inside:
            self._buf = ""
            self._inside = False
            return ""
        rest, self._buf = self._buf, ""
        return rest