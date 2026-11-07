"""联网搜索与网页读取。

不依赖任何 API Key：直接抓搜索引擎的结果页（cn.bing.com 可用性最好），
解析出「标题 / 链接 / 摘要」，模型再按需 web_fetch 深读某一页。

安全约束：
- 只允许 http/https；
- 拒绝内网地址（localhost / 127.x / 10.x / 192.168.x / 172.16-31.x / ::1），防止被诱导去扫本机；
- 返回内容截断，避免把整页 HTML 灌进上下文。
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
}
_TIMEOUT = 12.0
_MAX_FETCH_CHARS = 6000


# ---------------------------------------------------------------- 安全
def _is_private_host(host: str) -> bool:
    host = (host or "").strip().lower()
    if not host:
        return True
    if host in ("localhost", "localhost.localdomain", "ip6-localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        pass
    try:
        resolved = socket.getaddrinfo(host, None)
        for info in resolved:
            addr = info[4][0]
            ip = ipaddress.ip_address(addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _safe_url(url: str) -> tuple[str | None, str]:
    raw = (url or "").strip()
    if not raw:
        return None, "URL 为空"
    # 已经带了协议但不是 http/https（ftp、file、javascript…）直接拒绝
    m = re.match(r"^([a-zA-Z][\w+.-]*)://", raw)
    if m and m.group(1).lower() not in ("http", "https"):
        return None, f"只允许 http/https，收到 {m.group(1)}://"
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return None, "只允许 http/https"
    if _is_private_host(parsed.hostname or ""):
        return None, "拒绝访问内网/本机地址（安全检查）"
    return raw, ""


# ---------------------------------------------------------------- 解析
def _strip_tags(text: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_bing(page: str, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for chunk in page.split('<li class="b_algo"')[1:]:
        chunk = chunk.split("</li>")[0]
        m = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.S)
        if not m:
            continue
        url = html.unescape(m.group(1))
        title = _strip_tags(m.group(2))
        snippet = ""
        sm = re.search(r"<p[^>]*>(.*?)</p>", chunk, re.S)
        if sm:
            snippet = _strip_tags(sm.group(1))
        if not title:
            continue
        results.append({"title": title[:120], "url": url[:300], "snippet": snippet[:240]})
        if len(results) >= limit:
            break
    return results


def _parse_sogou(page: str, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for chunk in page.split('<div class="vrwrap"')[1:]:
        chunk = chunk.split('<div class="rb"></div>')[0]
        m = re.search(r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.S)
        if not m:
            continue
        url = html.unescape(m.group(1))
        if url.startswith("/"):
            url = "https://www.sogou.com" + url
        title = _strip_tags(m.group(2))
        snippet = ""
        sm = re.search(r'<p[^>]*class="star-wiki"[^>]*>(.*?)</p>|<p[^>]*>(.*?)</p>', chunk, re.S)
        if sm:
            snippet = _strip_tags(sm.group(1) or sm.group(2) or "")
        if title:
            results.append({"title": title[:120], "url": url[:300], "snippet": snippet[:240]})
        if len(results) >= limit:
            break
    return results


# ---------------------------------------------------------------- 对外
async def web_search(query: str, count: int = 5) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "查询词为空"}
    limit = max(1, min(int(count or 5), 8))

    engines = [
        ("bing", f"https://cn.bing.com/search?q={quote(q)}&setlang=zh-CN&ensearch=0", _parse_bing),
        ("sogou", f"https://www.sogou.com/web?query={quote(q)}", _parse_sogou),
    ]
    errors: list[str] = []
    async with httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True) as client:
        for name, url, parser in engines:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    errors.append(f"{name}: HTTP {resp.status_code}")
                    continue
                items = parser(resp.text, limit)
                if items:
                    return {
                        "ok": True,
                        "engine": name,
                        "query": q,
                        "count": len(items),
                        "results": items,
                        "note": "需要看某条详情时用 web_fetch 打开它的 url",
                    }
                errors.append(f"{name}: 没解析到结果")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {type(exc).__name__}")
                logger.debug("搜索失败 %s: %s", name, exc)

    return {
        "ok": False,
        "error": "联网搜索暂时不可用：" + "；".join(errors),
        "hint": "先用你自己的知识回答，并说明这部分没联网核实",
    }


async def web_fetch(url: str, max_chars: int = 0) -> dict[str, Any]:
    safe, err = _safe_url(url)
    if safe is None:
        return {"ok": False, "error": err}
    limit = max(800, min(int(max_chars or _MAX_FETCH_CHARS), 12000))
    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(safe)
            ctype = resp.headers.get("content-type", "")
            if "html" not in ctype and "text" not in ctype and "json" not in ctype:
                return {"ok": False, "error": f"不是文本内容（{ctype}），不读"}
            text = resp.text
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"抓取失败：{type(exc).__name__} {exc}"}

    body = _strip_tags(text) if "html" in (resp.headers.get("content-type", "") or "") else text
    truncated = len(body) > limit
    return {
        "ok": True,
        "url": safe,
        "status": resp.status_code,
        "chars": len(body),
        "truncated": truncated,
        "content": body[:limit],
    }