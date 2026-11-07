"""端到端冒烟测试：直接打真实 HTTP 接口，验证全链路。

用法（后端需已启动）：
    python scripts/smoke_test.py
    python scripts/smoke_test.py --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import httpx

BASE = "http://127.0.0.1:8000"
PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    icon = "✅" if cond else "❌"
    print(f"{icon} {name}" + (f"  → {detail}" if detail and not cond else ""))


def sse_events(response: httpx.Response) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in response.iter_lines():
        if not line or not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload == "[DONE]":
            break
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return events


def main() -> int:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    BASE = args.base.rstrip("/")

    client = httpx.Client(base_url=BASE, timeout=120.0)

    # ---------- 1. 健康检查 ----------
    health = client.get("/api/health").json()
    check("健康检查", health.get("ok") is True, str(health)[:200])
    check("数据库已连接", health["database"]["ok"] is True)
    check("向量库已就绪", health["vector"].get("knowledge_points", 0) >= 0)

    # ---------- 2. 模型接入 ----------
    providers = client.get("/api/providers").json()
    # mock 已按设计移除（它只会返回写死的假回答），这里验证真实供应商目录
    check("模型目录包含 DeepSeek/千问/本地/自定义", {
        "deepseek", "qwen", "ollama", "custom"
    }.issubset({c["id"] for c in providers["catalog"]}))
    check("存在激活模型", providers.get("active") is not None, str(providers.get("active")))

    # 保存一个假的 DeepSeek Key 验证加密存储与脱敏
    saved = client.put(
        "/api/providers/openai",
        json={"api_key": "sk-test-1234567890abcdef", "is_active": False},
    ).json()
    check("API Key 已加密脱敏保存", saved["has_key"] and "1234567890" not in saved["api_key_mask"],
          saved.get("api_key_mask", ""))
    cleared = client.delete("/api/providers/openai/key").json()
    check("API Key 可清除", cleared["has_key"] is False)

    # ---------- 2.5 环境管家 ----------
    probe = client.get("/api/env/probe").json()
    check("环境检测返回 ok", probe.get("ok") is True, str(probe)[:200])
    check("检测到 20+ 个工具", probe.get("total", 0) >= 20, str(probe.get("total")))
    check(
        "每张卡片带安装方式",
        all(("auto_install" in i and "manual_cmd" in i and "recommend" in i) for i in probe["items"]),
    )

    bad = client.post("/api/env/install", json={})
    check(
        "安装入参缺失 → 422 且带 ok:false",
        bad.status_code == 422 and bad.json().get("ok") is False,
        f"{bad.status_code} {str(bad.json())[:120]}",
    )
    unknown = client.post("/api/env/install", json={"tool_id": "no_such_tool"})
    check(
        "未知工具被拒绝且带 ok:false",
        unknown.status_code in (400, 422) and unknown.json().get("ok") is False,
        str(unknown.json())[:120],
    )
    jobs = client.get("/api/env/installs").json()
    check("安装任务列表可读", jobs.get("ok") is True and isinstance(jobs.get("items"), list))

    assoc = client.get("/api/env/default-apps").json()
    check("默认打开方式可识别", assoc.get("ok") is True and len(assoc.get("items", [])) > 0)
    applied = client.post("/api/env/default-apps/apply", json={}).json()
    check(
        "关联可写入编辑器库（幂等）",
        applied.get("ok") is True and isinstance(applied.get("editors"), list),
        str(applied.get("summary")),
    )

    # ---------- 3. 知识库 / RAG ----------
    reindex = client.post("/api/knowledge/reindex").json()
    check("知识库重建索引", reindex.get("ok") is True, str(reindex))
    stats = client.get("/api/knowledge/stats").json()
    check("知识库有文档", stats["documents"] >= 5, f"docs={stats['documents']}")
    check("切片数量合理", stats["chunks"] >= stats["documents"], f"chunks={stats['chunks']}")

    search = client.post(
        "/api/knowledge/search", json={"query": "Python 装饰器怎么写", "top_k": 3}
    ).json()
    check("向量检索命中", search["count"] > 0, str(search)[:200])
    if search["hits"]:
        top = search["hits"][0]
        check("检索结果带来源", bool(top.get("title")), str(top)[:200])

    # ---------- 4. 对话（Agent 全流程 + SSE） ----------
    start = time.time()
    with client.stream(
        "POST",
        "/api/chat",
        json={"content": "Python 装饰器是什么？给我一个能跑的示例", "mode": "agent"},
    ) as resp:
        check("聊天接口返回 200", resp.status_code == 200, str(resp.status_code))
        events = sse_events(resp)
    elapsed = time.time() - start

    types = [e["type"] for e in events]
    check("SSE 事件流完整", {"start", "plan", "token", "done"}.issubset(set(types)), str(types[:12]))
    check("输出了规划步骤", any(e["type"] == "plan" and e.get("steps") for e in events))
    check("调用了工具", "tool_start" in types and "tool_end" in types)
    check("工具有成功返回", any(e["type"] == "tool_end" and e["ok"] for e in events))
    answer = "".join(e.get("text", "") for e in events if e["type"] == "token")
    check("回答非空", len(answer) > 80, answer[:120])
    demo = next((e for e in events if e["type"] == "demo"), None)
    check("演示可用性已判定", demo is not None and "available" in demo, str(demo)[:200])
    done = next((e for e in events if e["type"] == "done"), None)
    check("返回会话与消息 id", bool(done and done.get("conversation_id") and done.get("message_id")))
    conv_id = done["conversation_id"] if done else None
    print(f"   ⏱ 本轮耗时 {elapsed:.1f}s，事件 {len(events)} 条，回答 {len(answer)} 字")

    # ---------- 5. 会话隔离与多轮记忆 ----------
    with client.stream(
        "POST",
        "/api/chat",
        json={"conversation_id": conv_id, "content": "那它和闭包有什么关系？", "mode": "agent"},
    ) as resp:
        events2 = sse_events(resp)
    check("同一会话第二轮成功", any(e["type"] == "done" for e in events2))

    with client.stream(
        "POST", "/api/chat", json={"content": "我更喜欢用 Vue3 组合式 API", "mode": "agent"}
    ) as resp:
        events3 = sse_events(resp)
    conv2 = next((e["conversation_id"] for e in events3 if e["type"] == "done"), None)
    check("新会话独立创建", bool(conv2) and conv2 != conv_id, f"{conv2} vs {conv_id}")

    convs = client.get("/api/conversations").json()
    check("会话列表 ≥ 2", convs["total"] >= 2, str(convs["total"]))
    detail = client.get(f"/api/conversations/{conv_id}").json()
    check("会话详情含多轮消息", len(detail["messages"]) >= 4, str(len(detail.get("messages", []))))
    check("消息带 Agent 计划", any(m.get("plan") for m in detail["messages"]))

    runs = client.get(f"/api/conversations/{conv_id}/runs").json()
    check("Agent 运行轨迹已落库", len(runs["items"]) >= 1)

    memories = client.get("/api/memory").json()
    check("长期记忆已写入", memories["stats"]["total"] >= 1, str(memories["stats"]))
    recall = client.post("/api/memory/recall", json={"query": "我喜欢用什么技术"}).json()
    check("长期记忆可召回", recall["count"] >= 1, str(recall)[:200])

    # ---------- 6. 工具异常处理 ----------
    with client.stream(
        "POST",
        "/api/chat",
        json={
            "content": "帮我运行这段代码：\n```python\nimport os\nos.system('echo hi')\n```",
            "mode": "agent",
        },
    ) as resp:
        events4 = sse_events(resp)
    sandbox = [e for e in events4 if e["type"] == "tool_end" and e["name"] == "python_sandbox"]
    check("危险代码被沙箱拒绝且不崩溃", bool(sandbox) and sandbox[0]["ok"] is False,
          str(sandbox)[:200])
    check("异常后仍能产出回答", any(e["type"] == "done" for e in events4))

    # ---------- 7. 多模态上传 ----------
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000050001"
        "0d0a2db40000000049454e44ae426082"
    )
    up = client.post(
        "/api/files/upload", files={"file": ("t.png", png, "image/png")}
    ).json()
    check("图片上传成功", up.get("ok") and up["attachment"]["url"].startswith("/static/"),
          str(up)[:200])

    # ---------- 8. 屏幕演示（dry-run，不会真的动鼠标） ----------
    caps = client.get("/api/screen/capabilities").json()
    check("屏幕能力可读", "gui_available" in caps, str(caps))
    session = client.post(
        "/api/screen/sessions",
        json={
            "conversation_id": conv_id,
            "goal": "演示新建 Python 文件并运行",
            "steps": ["打开编辑器", "新建文件", "运行程序"],
            "interval_ms": 1500,
            "max_steps": 3,
            "dry_run": True,
        },
    ).json()
    check("屏幕会话创建", bool(session.get("id")), str(session)[:200])
    sid = session["id"]
    started = client.post(f"/api/screen/sessions/{sid}/start").json()
    check("屏幕会话已启动", started["status"] in ("running", "paused"), started["status"])
    time.sleep(4)
    paused = client.post(f"/api/screen/sessions/{sid}/pause").json()
    check("可暂停并记录当前步骤", paused["status"] == "paused", str(paused)[:200])
    step_at_pause = paused["current_step"]
    check("暂停点已持久化", step_at_pause >= 0, str(step_at_pause))
    resumed = client.post(f"/api/screen/sessions/{sid}/resume").json()
    check("可从暂停点恢复", resumed["status"] in ("running", "paused"), resumed["status"])
    time.sleep(2)
    client.post(f"/api/screen/sessions/{sid}/stop")
    final = client.get(f"/api/screen/sessions/{sid}").json()
    check("屏幕会话有步骤日志", len(final.get("steps_log", [])) >= 1,
          str(len(final.get("steps_log", []))))
    check("屏幕会话已结束", final["status"] == "completed", final["status"])

    # ---------- 9. 清理 ----------
    client.delete(f"/api/conversations/{conv2}")
    check("会话可删除", client.get(f"/api/conversations/{conv2}").status_code == 404)

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：", "，".join(FAIL))
    print("=" * 56)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())