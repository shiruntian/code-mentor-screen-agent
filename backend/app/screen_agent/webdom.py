"""读网页 DOM：通过 Chrome DevTools Protocol 直接拿页面结构。

为什么需要它：截图识别小控件天生不稳。浏览器开着调试端口时，一句 JS 就能拿到
"第几题、选项文字、哪个被选中、按钮在哪"——比让视觉模型去数像素可靠得多。

注意：Edge/Chrome 只在**启动时**带 `--remote-debugging-port` 才会开放这个口，
已经开着的浏览器无法事后挂上。所以这里做了三层降级：

1. 探测常见端口（9222/9223）和 `--remote-debugging-port` 写下的 DevToolsActivePort 文件；
2. 探不到就返回 None，调用方继续用截图；
3. 全程只读，不点、不改页面。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_PORTS = (9222, 9223, 9333)

# 一个通用探针：把"题目/选项/勾选状态/按钮"这些通用结构捞出来。
# 只读 DOM，不点击。字段尽量宽松，适配超星/学习通/雨课堂/问卷星这类站点。
QUIZ_PROBE_JS = r"""
(() => {
  const pick = (el) => (el && (el.innerText || el.textContent) || '').trim();
  const visible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && st.visibility !== 'hidden' && st.display !== 'none';
  };

  // 1) 所有"看起来是选项"的可点元素：含单个大写字母标签的方块，或带 checkbox 语义的
  const candidates = [];
  document.querySelectorAll('label, li, div, a, span, button').forEach((el) => {
    if (!visible(el)) return;
    const text = pick(el);
    if (!text || text.length > 200) return;
    const rect = el.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) return;
    // 形如 "A 获取消费者需求" 或 "A. 获取消费者需求"
    const m = text.match(/^([A-H])[\.\s、:：]/);
    const input = el.querySelector('input[type=radio],input[type=checkbox]');
    const cls = (el.className || '') + ' ' + (el.parentElement?.className || '');
    const looksSelected =
      /(is-checked|checked|selected|active|current)/i.test(cls) ||
      (input && input.checked) ||
      /rgb\(3[0-9], *9[0-9], *2[0-9][0-9]\)/.test(getComputedStyle(el).backgroundColor) ||
      /rgb\(2[0-9], *1[0-9][0-9], *2[0-9][0-9]\)/.test(getComputedStyle(el).backgroundColor);
    if (m) {
      candidates.push({
        阵营: 'option',
        letter: m[1],
        text: text.slice(0, 120),
        selected: !!looksSelected,
        x: Math.round(rect.left + rect.width / 2),
        y: Math.round(rect.top + rect.height / 2),
      });
    }
  });

  // 2) 题干：包含"（）"或"?"的、字号偏大的块
  const heads = [];
  document.querySelectorAll('div,p,span,h3,h4').forEach((el) => {
    if (!visible(el)) return;
    const t = pick(el);
    if (t.length < 8 || t.length > 200) return;
    if (/(\(\)|（\s*）|\?|？)/.test(t) && /题|下列|哪|什么|包括|属于|是/.test(t)) {
      heads.push(t.slice(0, 160));
    }
  });

  // 3) 按钮：提交/下一节/暂时保存
  const buttons = [];
  document.querySelectorAll('a,button,div,span').forEach((el) => {
    if (!visible(el)) return;
    const t = pick(el);
    if (!t || t.length > 12) return;
    if (/^(提交|交卷|下一节|上一节|暂时保存|保存|确定|继续)$/.test(t)) {
      const rect = el.getBoundingClientRect();
      buttons.push({
        text: t,
        x: Math.round(rect.left + rect.width / 2),
        y: Math.round(rect.top + rect.height / 2),
      });
    }
  });

  // 去重（同一个选项常被父子元素重复命中）
  const uniq = [];
  const seen = new Set();
  for (const c of candidates) {
    const key = c.letter + '|' + c.text.slice(0, 20);
    if (seen.has(key)) continue;
    seen.add(key);
    uniq.push(c);
  }
  const uniqBtns = [];
  const seenB = new Set();
  for (const b of buttons) {
    if (seenB.has(b.text)) continue;
    seenB.add(b.text);
    uniqBtns.push(b);
  }

  return {
    url: location.href,
    title: document.title,
    options: uniq.slice(0, 60),
    headings: [...new Set(heads)].slice(0, 6),
    buttons: uniqBtns,
    viewport: { w: innerWidth, h: innerHeight },
  };
})()
"""


class DevTools:
    """一个极简 CDP 客户端：找到页面 → 连 WebSocket → 执行 JS。"""

    def __init__(self, port: int, ws_url: str, page: dict[str, Any]) -> None:
        self.port = port
        self.ws_url = ws_url
        self.page = page
        self._seq = 0

    @property
    def title(self) -> str:
        return str(self.page.get("title") or "")

    @property
    def url(self) -> str:
        return str(self.page.get("url") or "")

    async def evaluate(self, expression: str) -> Any:
        """在页面里跑一段 JS，返回结果（JSON 可序列化）。"""
        try:
            import websockets
        except ImportError:  # pragma: no cover
            raise RuntimeError("缺少 websockets 依赖，无法使用 CDP")

        self._seq += 1
        message = {
            "id": self._seq,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "timeout": 8000,
            },
        }
        async with websockets.connect(self.ws_url, max_size=8 * 1024 * 1024, open_timeout=6) as ws:
            await ws.send(json.dumps(message))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(raw)
                if data.get("id") != self._seq:
                    continue
                if "error" in data:
                    raise RuntimeError(str(data["error"].get("message") or data["error"]))
                result = data.get("result", {})
                if result.get("exceptionDetails"):
                    raise RuntimeError(str(result["exceptionDetails"].get("text"))[:200])
                return result.get("result", {}).get("value")


def _devtools_active_port(port: int) -> int | None:
    """从 Chromium 的 DevToolsActivePort 文件里读真实端口（用户自定义了端口时有用）。"""
    candidates = [
        os.environ.get("LOCALAPPDATA", "") + r"\Microsoft\Edge\User Data\DevToolsActivePort",
        os.environ.get("LOCALAPPDATA", "") + r"\Google\Chrome\User Data\DevToolsActivePort",
    ]
    for path in candidates:
        try:
            first = Path(path).read_text(encoding="utf-8").splitlines()[0].strip()
            if first.isdigit():
                return int(first)
        except Exception:  # noqa: BLE001
            continue
    return None


async def list_pages(ports: tuple[int, ...] = DEFAULT_PORTS) -> list[tuple[int, dict[str, Any]]]:
    """列出所有可调试的页面：(端口, 页面信息)。"""
    found: list[tuple[int, dict[str, Any]]] = []
    active = _devtools_active_port(0)
    tried: list[int] = []
    for port in list(ports) + ([active] if active else []):
        if port in tried:
            continue
        tried.append(port)
        try:
            async with httpx.AsyncClient(timeout=0.6) as client:
                resp = await client.get(f"http://127.0.0.1:{port}/json/list")
                if resp.status_code != 200:
                    continue
                for page in resp.json():
                    if page.get("type") == "page" and page.get("webSocketDebuggerUrl"):
                        found.append((port, page))
        except Exception:  # noqa: BLE001
            continue
    return found


async def connect(keyword: str = "", ports: tuple[int, ...] = DEFAULT_PORTS) -> DevTools | None:
    """连上一个页面；keyword 用于按标题/URL 过滤（比如 "chaoxing" 或 "测验"）。"""
    pages = await list_pages(ports)
    if not pages:
        return None
    keyword = (keyword or "").strip().lower()
    chosen = None
    if keyword:
        for port, page in pages:
            haystack = f"{page.get('title', '')} {page.get('url', '')}".lower()
            if keyword in haystack:
                chosen = (port, page)
                break
    if chosen is None:
        chosen = pages[0]
    port, page = chosen
    return DevTools(port, str(page["webSocketDebuggerUrl"]), page)


async def read_quiz(keyword: str = "") -> dict[str, Any] | None:
    """读当前页面的答题结构；不可用返回 None。"""
    dev = await connect(keyword)
    if dev is None:
        return None
    try:
        data = await dev.evaluate(QUIZ_PROBE_JS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CDP 读取页面失败: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    data["_port"] = dev.port
    return data


def render_quiz(data: dict[str, Any], limit: int = 40) -> str:
    """把 CDP 读到的结构渲染成给模型看的一段文字。"""
    options = data.get("options") or []
    if not options:
        return "网页里没有识别到选项结构"
    lines: list[str] = []
    heads = data.get("headings") or []
    if heads:
        lines.append("题干：" + "；".join(str(h)[:80] for h in heads[:3]))
    chosen = [o for o in options if o.get("selected")]
    rest = [o for o in options if not o.get("selected")]
    lines.append(f"已选中 {len(chosen)} 个，未选中 {len(rest)} 个：")
    for opt in options[:limit]:
        mark = "✅已选" if opt.get("selected") else "⬜未选"
        lines.append(f"  {mark} {opt.get('letter') or '?'} {str(opt.get('text') or '')[:60]}")
    buttons = data.get("buttons") or []
    if buttons:
        lines.append("按钮：" + "、".join(str(b.get("text")) for b in buttons))
    return "\n".join(lines)

_PAGE_CACHE: dict[str, Any] = {"at": 0.0, "dev": None}
_TTL = 10.0        # 找到答题页后缓存 10 秒
_NEG_TTL = 30.0     # 没找到就 30 秒内不再折腾


async def _find_quiz_page(force: bool = False) -> DevTools | None:
    """找出"看起来是答题页"的那个标签页（至少有 2 个选项），结果缓存 10 秒。

    浏览器里常开着一堆标签页，按标题猜不可靠；逐个探一遍最稳。
    """
    import time as _time

    now = _time.time()
    if not force and now - _PAGE_CACHE["at"] < (_TTL if _PAGE_CACHE["dev"] else _NEG_TTL):
        return _PAGE_CACHE["dev"]

    pages = await list_pages()
    for port, page in pages:
        url = str(page.get("url") or "")
        if not url.startswith(("http://", "https://", "file://")):
            continue
        dev = DevTools(int(port), str(page["webSocketDebuggerUrl"]), page)
        try:
            quick = await dev.evaluate(
                "(() => document.querySelectorAll("
                "'input[type=checkbox],input[type=radio],label,li').length)()"
            )
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(quick, int) or quick < 2:
            continue
        _PAGE_CACHE["dev"] = dev
        _PAGE_CACHE["at"] = now
        return dev
    _PAGE_CACHE["dev"] = None
    _PAGE_CACHE["at"] = now
    return None


async def read_quiz_any(ports: tuple[int, ...] = DEFAULT_PORTS) -> dict[str, Any] | None:
    """在**所有**可调试页面里找那个"看起来是答题页"的（至少有 2 个选项）。"""
    dev = await _find_quiz_page()
    if dev is None:
        return None
    try:
        data = await dev.evaluate(QUIZ_PROBE_JS)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    data["_port"] = dev.port
    return data


CLICK_BY_LETTER_JS = r"""
((letter) => {
  const pick = (el) => (el && (el.innerText || el.textContent) || '').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && st.visibility !== 'hidden' && st.display !== 'none';
  };
  const targets = [];
  document.querySelectorAll('label, li, div, a, span, button').forEach((el) => {
    if (!visible(el)) return;
    const t = pick(el);
    if (!t || t.length > 200) return;
    const m = t.match(/^([A-H])[.\s、:：]/);
    if (m && m[1] === letter) {
      const rect = el.getBoundingClientRect();
      targets.push({ el, area: rect.width * rect.height });
    }
  });
  if (!targets.length) return 'not-found';
  targets.sort((a, b) => a.area - b.area);     // 取最小的一块，别点到外层容器
  const node = targets[0].el;
  node.scrollIntoView({ block: 'center' });
  const input = node.querySelector('input[type=checkbox],input[type=radio]');
  if (input) input.click(); else node.click();
  return 'clicked';
})(LETTER)
"""


async def click_option(letter: str, keyword: str = "") -> str:
    """按字母点某个选项（DOM 点击，不受坐标偏差影响）。"""
    dev = await _find_quiz_page()
    if dev is None:
        return "CDP 不可用"
    expr = CLICK_BY_LETTER_JS.replace("LETTER", repr(str(letter).upper()[:1]))
    try:
        result = await dev.evaluate(expr)
    except Exception as exc:  # noqa: BLE001
        return f"DOM 点击失败：{exc}"
    return str(result)


def build_option_selector(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给模型看的"选项 + 是否已选"精简表（测试用，纯函数）。"""
    return [
        {
            "letter": str(o.get("letter") or ""),
            "text": str(o.get("text") or "")[:60],
            "selected": bool(o.get("selected")),
        }
        for o in options
    ]
