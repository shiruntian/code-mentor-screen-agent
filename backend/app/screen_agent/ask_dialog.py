"""置顶提问窗口：屏幕演示停下来问问题时，弹一个**始终在最前面**的小窗。

为什么不在网页里做：浏览器没法把窗口钉在最上层，而演示时整屏都被别的程序占着
（有时连本项目的控制面板自己也挡着），网页里的输入框经常看不到。这里用 tkinter
开一个原生窗口，`-topmost` 钉在最上面，填完点「提交」直接把答案 POST 回后端，
后端收到后会自动继续演示。

用法（由后端在需要提问时自动拉起，也可以手动跑）：
    python -m app.screen_agent.ask_dialog \
        --base http://127.0.0.1:8000 --session <id> \
        --question "请选择下一步操作：…" --options A --options B

行为细节：
- 提交后先调接口再关窗；关窗失败也不影响演示（后端已经在跑）
- 每 2 秒查一次会话：如果问题已经被网页那边回答掉了、或演示结束了，自己关掉
- 关窗（✕ / Esc）＝不作答，演示保持暂停
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.error
import urllib.request

POLL_MS = 2000


def _post_answer(base: str, session_id: str, answer: str) -> tuple[bool, str]:
    url = f"{base.rstrip('/')}/api/screen/sessions/{session_id}/answer"
    body = json.dumps({"answer": answer}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
        return True, str(payload.get("answer") or answer)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8") or "{}")
            return False, str(detail.get("message") or detail.get("detail") or exc)
        except Exception:  # noqa: BLE001
            return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _session_state(base: str, session_id: str) -> dict | None:
    url = f"{base.rstrip('/')}/api/screen/sessions/{session_id}"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except Exception:  # noqa: BLE001
        return None


def _force_show(root) -> None:
    """把窗口真的顶到最前面。

    只靠 tkinter 的 -topmost 不一定够：后端是用「隐藏控制台」的父进程拉起的，
    Windows 会让子进程继承 STARTUPINFO 的 SW_HIDE，结果窗口建出来了却处于最小化
    （坐标变成 -32000），看起来就是「没弹」。这里直接用 Win32 强制显示 + 置顶。
    """
    try:
        root.state("normal")
        root.deiconify()
        root.update_idletasks()
        root.lift()
    except Exception:  # noqa: BLE001
        pass
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = int(root.winfo_id())
        # winfo_id 拿到的是 Tk 的内容窗口，真正的顶层窗口是它的父窗口
        parent = user32.GetParent(hwnd)
        if parent:
            hwnd = parent
        SW_SHOWNORMAL = 1
        HWND_TOPMOST = -1
        SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
        user32.ShowWindow(hwnd, SW_SHOWNORMAL)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="屏幕演示置顶提问窗口")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--session", required=True)
    ap.add_argument("--question", required=True)
    ap.add_argument("--options", action="append", default=[])
    args = ap.parse_args(argv)

    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:  # noqa: BLE001
        print(f"tkinter 不可用：{exc}", file=sys.stderr)
        return 2

    # 高 DPI 屏幕上不声明感知的话，Windows 会把窗口按 150% 放大成一个模糊的位图，
    # 而且 Tk 拿到的屏幕尺寸是逻辑值，定位会和真实坐标差一倍多。
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass

    root = tk.Tk()
    root.title("屏幕演示 · 需要你补充信息")
    root.attributes("-topmost", True)  # 钉在最上面
    root.resizable(False, False)
    try:
        root.attributes("-alpha", 0.98)
    except Exception:  # noqa: BLE001
        pass

    bg = "#0f172a"
    fg = "#e2e8f0"
    root.configure(bg=bg)
    # 让文字跟着系统缩放走，150% 屏上不至于糊成一团
    try:
        root.tk.call("tk", "scaling", max(1.0, float(root.winfo_fpixels("1i")) / 72.0))
    except Exception:  # noqa: BLE001
        pass

    head = tk.Frame(root, bg=bg)
    head.pack(fill="x", padx=16, pady=(14, 4))
    tk.Label(head, text="🤔 演示暂停，需要你回答", bg=bg, fg="#fbbf24",
             font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
    tk.Label(head, text="这个窗口会一直保持在最上方", bg=bg, fg="#64748b",
             font=("Microsoft YaHei UI", 8)).pack(side="right")

    q = tk.Label(root, text=args.question, bg=bg, fg=fg, justify="left",
                 wraplength=460, font=("Microsoft YaHei UI", 10))
    q.pack(fill="x", padx=16, pady=(2, 8))

    status = tk.Label(root, text="", bg=bg, fg="#94a3b8", font=("Microsoft YaHei UI", 8))
    status.pack(fill="x", padx=16)

    entry_var = tk.StringVar()

    def submit(text: str) -> None:
        value = (text or "").strip()
        if not value:
            status.configure(text="回答不能为空", fg="#f87171")
            return
        ok, msg = _post_answer(args.base, args.session, value)
        if ok:
            status.configure(text=f"已提交，演示继续…（{msg[:24]}）", fg="#34d399")
            root.after(260, root.destroy)
        else:
            status.configure(text=f"提交失败：{msg[:60]}", fg="#f87171")

    row = tk.Frame(root, bg=bg)
    row.pack(fill="x", padx=16, pady=(10, 12))

    def flat_btn(parent, text, command, primary=False, width=None):
        return tk.Button(
            parent, text=text, command=command, relief="flat", bd=0,
            bg=("#6366f1" if primary else "#1e293b"),
            fg="#ffffff" if primary else "#cbd5e1",
            activebackground=("#4f46e5" if primary else "#334155"),
            activeforeground="#ffffff",
            padx=14 if primary else 10, pady=5,
            width=width or 0,
            highlightthickness=0, cursor="hand2",
            font=("Microsoft YaHei UI", 10, "bold" if primary else "normal"),
        )

    for opt in args.options:
        flat_btn(row, str(opt), lambda o=opt: submit(o), width=3).pack(side="left", padx=(0, 6))

    entry = tk.Entry(row, textvariable=entry_var, bg="#1e293b", fg=fg, insertbackground=fg,
                     relief="flat", highlightthickness=1, highlightbackground="#334155",
                     highlightcolor="#6366f1", font=("Microsoft YaHei UI", 10))
    entry.pack(side="left", fill="x", expand=True, padx=(2, 8), ipady=6)
    flat_btn(row, "提交", lambda: submit(entry_var.get()), primary=True).pack(side="left")

    def on_escape(_event=None):
        root.destroy()

    root.bind("<Escape>", on_escape)
    entry.bind("<Return>", lambda _e: submit(entry_var.get()))

    # 窗口大小跟着问题长短走：文字多的时候不能把输入行挤出去
    root.update_idletasks()
    width = max(520, root.winfo_reqwidth())
    height = root.winfo_reqheight()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = max(0, int((screen_w - width) / 2))
    y = max(0, int(screen_h * 0.16))  # 偏上方，压在常见窗口标题栏下面
    root.geometry(f"{width}x{height}+{x}+{y}")

    # 多次尝试：第一次 map 之后有些窗口管理器会把它再最小化回去
    for delay in (80, 260, 800):
        root.after(delay, lambda: (_force_show(root), entry.focus_force()))

    # 网页那边回答掉、或演示结束/停止时，自己关掉
    stopped = threading.Event()

    def watch() -> None:
        import time

        while not stopped.is_set():
            time.sleep(POLL_MS / 1000)
            if stopped.is_set():
                return
            data = _session_state(args.base, args.session)
            if data is None:
                continue
            if not data.get("pending_question") or data.get("status") not in ("waiting", "paused"):
                # 已经不是「等你回答」的状态了，说明别处处理过了
                try:
                    root.after(0, root.destroy)
                except Exception:  # noqa: BLE001
                    pass
                return

    threading.Thread(target=watch, daemon=True).start()

    def on_close() -> None:
        stopped.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    try:
        root.mainloop()
    finally:
        stopped.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())