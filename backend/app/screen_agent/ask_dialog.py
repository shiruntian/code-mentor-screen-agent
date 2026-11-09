"""屏幕演示的置顶提问窗口。

设计要点（都是踩过坑总结的）：

1. **无系统标题栏**：`overrideredirect(True)` + 自绘标题区（可拖动、带关闭按钮）；
2. **平滑圆角**：用 PIL 画带抗锯齿的圆角卡片，再用 `-transparentcolor` 抠掉四角。
   抠色键取"卡片色 + 1"这种几乎一样的颜色，边缘抗锯齿只会混到相近色，不会出现彩边；
3. **半透明**：`-alpha` 由设置里的透明度控制（设置 → 外观 → 演示问答弹窗）；
4. **尺寸自适应**：宽度按屏幕比例（约 40%），高度按内容算，文字多就长高，封顶 80% 屏高；
5. **选项自动换行**：一行放不下就换行；选项太多时列表区域变成可滚动，不会把输入框挤出去。

命令行参数由 `ScreenController._spawn_ask_dialog()` 传入，改了别忘同步那边。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tkinter as tk
import urllib.error
import urllib.request

POLL_MS = 2000

# 两套配色：深色 / 浅色。accent 会由设置覆盖
THEMES = {
    "dark": {
        "card": "#0f172a",
        "card2": "#131c31",
        "line": "#1e2b45",
        "fg": "#e8eefb",
        "sub": "#8b9bb4",
        "field": "#1b2740",
        "field_fg": "#ffffff",
        "warn": "#fbbf24",
        "ok": "#34d399",
        "err": "#f87171",
    },
    "light": {
        "card": "#ffffff",
        "card2": "#f6f8fc",
        "line": "#e2e8f0",
        "fg": "#0f172a",
        "sub": "#64748b",
        "field": "#f1f5f9",
        "field_fg": "#0f172a",
        "warn": "#b45309",
        "ok": "#059669",
        "err": "#dc2626",
    },
}


def _pick_chroma_key(palette: dict[str, str]) -> str:
    """挑一个"和卡片色几乎一样、又绝不出现在界面里"的颜色当抠色键。

    必须避开卡片本身：#ffffff 这种纯白加 1 会被夹回原值，一旦和卡片同色，
    整块卡片都会被抠成透明（浅色主题下踩过这个坑）。
    """
    card = palette["card"].lower()
    used = {v.lower() for v in palette.values()} | {card}
    base = [int(card[1:3], 16), int(card[3:5], 16), int(card[5:7], 16)]
    for delta in (1, -1, 2, -2, 3, -3, 4, -4, 5, -5):
        for idx in (2, 1, 0):  # 先动蓝、再绿、再红，视觉上最不显眼
            cand = list(base)
            cand[idx] = max(0, min(255, base[idx] + delta))
            value = "#{:02x}{:02x}{:02x}".format(*cand)
            if value != card and value not in used:
                return value
    return "#fe01fe"  # 兜底：洋红，正常配色里不可能出现


def _shift(color: str, delta: int) -> str:
    """把 #rrggbb 整体加亮（delta>0）或压暗（delta<0）。"""
    try:
        r = max(0, min(255, int(color[1:3], 16) + delta))
        g = max(0, min(255, int(color[3:5], 16) + delta))
        b = max(0, min(255, int(color[5:7], 16) + delta))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:  # noqa: BLE001
        return color


# ------------------------------------------------------------------ 后端交互
def _post_answer(base: str, session_id: str, answer: str) -> tuple[bool, str]:
    url = f"{base.rstrip('/')}/api/screen/sessions/{session_id}/answer"
    body = json.dumps({"answer": answer}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
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


# ------------------------------------------------------------------ Win32
def _norm_question(text: str) -> str:
    """去掉空白再比，避免"存的时候和传的时候空格不一样"导致窗口秒关。"""
    return "".join((text or "").split())


def _force_show(root) -> None:  # noqa: ANN001
    """把窗口真的顶到最前面（CREATE_NO_WINDOW 启动的子进程会继承 SW_HIDE）。"""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        SW_SHOWNORMAL, HWND_TOPMOST = 1, -1
        SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
        user32.ShowWindow(hwnd, SW_SHOWNORMAL)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ 文本测量
def _font(root, family: str, size: int, bold: bool = False):  # noqa: ANN001
    import tkinter.font as tkfont

    return tkfont.Font(root=root, family=family, size=size, weight="bold" if bold else "normal")


def _wrap_px(text: str, font, limit: int) -> list[str]:  # noqa: ANN001
    """按像素宽度折行：中文按字切，英文尽量按词切。"""
    lines: list[str] = []
    for raw in (text or "").split("\n"):
        if not raw:
            lines.append("")
            continue
        line = ""
        for ch in raw:
            if font.measure(line + ch) <= limit:
                line += ch
            else:
                lines.append(line)
                line = ch
        lines.append(line)
    return lines


def _rounded_card(width: int, height: int, bg: str, key: str, radius: int, border: str = ""):
    """画一张带抗锯齿圆角的卡片；四角填 key 色，交给 -transparentcolor 抠掉。"""
    from PIL import Image, ImageDraw

    scale = 4
    img = Image.new("RGB", (width * scale, height * scale), key)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, width * scale - 1, height * scale - 1),
        radius=radius * scale,
        fill=bg,
        outline=border,
        width=max(1, scale),
    )
    return img.resize((width, height), Image.LANCZOS)


# ------------------------------------------------------------------ 主窗口
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="屏幕演示置顶提问窗口")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--session", required=True)
    ap.add_argument("--question", required=True)
    ap.add_argument("--options", action="append", default=[])
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    ap.add_argument("--opacity", type=float, default=0.95)
    ap.add_argument("--tint", type=int, default=0, help="负值更暗、正值更亮")
    ap.add_argument("--accent", default="#6366f1")
    ap.add_argument("--font", default="", help="字体族，空=微软雅黑")
    args = ap.parse_args(argv)

    try:
        import tkinter as tk
    except Exception as exc:  # noqa: BLE001
        print(f"tkinter 不可用：{exc}", file=sys.stderr)
        return 2

    # 高 DPI：不声明感知会被 Windows 放大成模糊位图，坐标也和真实像素对不上
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass

    palette = dict(THEMES[args.theme if args.theme in THEMES else "dark"])
    for key in ("card", "card2", "field"):
        palette[key] = _shift(palette[key], int(args.tint))
    accent = args.accent if args.accent.startswith("#") and len(args.accent) == 7 else "#6366f1"
    key_color = _pick_chroma_key(palette)  # 抠色键：和卡片色几乎一样，抗锯齿不会有彩边

    root = tk.Tk()
    root.withdraw()
    root.title("屏幕演示 · 需要你补充信息")
    root.overrideredirect(True)                 # 去掉系统标题栏
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
        root.attributes("-alpha", max(0.35, min(1.0, float(args.opacity))))
        root.attributes("-transparentcolor", key_color)
    except Exception:  # noqa: BLE001
        pass
    root.configure(bg=key_color)
    try:
        root.tk.call("tk", "scaling", max(1.0, float(root.winfo_fpixels("1i")) / 72.0))
    except Exception:  # noqa: BLE001
        pass

    exists = root.tk.call("font", "families")
    family = "Microsoft YaHei UI" if "Microsoft YaHei UI" in exists else "Microsoft YaHei"
    # 设置里选了字体就按它画（如 楷体 KaiTi）；没装就退回雅黑
    if args.font:
        wanted = args.font.strip()
        if wanted and any(str(f).lower() == wanted.lower() for f in exists):
            family = wanted
    f_title = _font(root, family, 12, bold=True)
    f_q = _font(root, family, 11)
    f_opt = _font(root, family, 10)
    f_small = _font(root, family, 9)

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    # 宽度：约 40% 屏宽，夹在 760~1240 之间（比之前大一圈）
    width = int(max(760, min(1240, sw * 0.40)))
    radius = 18
    pad = 26
    inner = width - pad * 2

    # ---------------- 先算内容高度，再决定窗口多高 ----------------
    q_lines = _wrap_px(args.question, f_q, inner)
    q_height = max(1, len(q_lines)) * (f_q.metrics("linespace") + 3)

    options = [str(o) for o in args.options if str(o).strip()]
    # 选项按 pill 排版：宽度 = 文字 + 内边距，放不下就换行
    pill_pad_x, pill_pad_y = 16, 9
    rows: list[list[tuple[str, int]]] = []
    cur: list[tuple[str, int]] = []
    cur_w = 0
    for opt in options:
        w = f_opt.measure(opt) + pill_pad_x * 2
        w = min(w, inner)
        if cur and cur_w + w + 10 > inner:
            rows.append(cur)
            cur, cur_w = [], 0
        cur.append((opt, w))
        cur_w += w + 10
    if cur:
        rows.append(cur)
    pill_h = f_opt.metrics("linespace") + pill_pad_y * 2
    options_h = len(rows) * (pill_h + 10) if rows else 0

    head_h = f_title.metrics("linespace") + 18
    # 先按估算给个高度，控件建完再按实际内容重新定（手算经常漏掉一两行）
    height = int(min(24 + head_h + 60 + q_height + options_h + 140, sh * 0.80))
    root.geometry(f"{width}x{height}+{int((sw - width) / 2)}+{int(sh * 0.14)}")

    # ---------------- 卡片 ----------------
    canvas = tk.Canvas(root, width=width, height=height, bg=key_color, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    card_item = {"id": None}

    def paint_card(w: int, h: int) -> None:
        """按最终尺寸重画圆角卡片。"""
        try:
            from PIL import ImageTk

            photo = ImageTk.PhotoImage(
                _rounded_card(w, h, palette["card"], key_color, radius, palette["line"])
            )
            if card_item["id"] is None:
                card_item["id"] = canvas.create_image(0, 0, anchor="nw", image=photo)
            else:
                canvas.itemconfigure(card_item["id"], image=photo)
            canvas.image = photo  # 防止被回收
        except Exception:  # noqa: BLE001
            canvas.configure(bg=palette["card"])

    paint_card(width, height)

    body = tk.Frame(root, bg=palette["card"])
    body_win = canvas.create_window(pad, 22, anchor="nw", window=body, width=inner)

    # ---------------- 头部（可拖动 + 关闭） ----------------
    head = tk.Frame(body, bg=palette["card"])
    head.pack(fill="x", pady=(0, 0))

    tk.Label(
        head, text="◆", bg=palette["card"], fg=palette["warn"], font=(family, 12, "bold")
    ).pack(side="left")
    tk.Label(
        head, text=" 演示暂停，需要你回答", bg=palette["card"], fg=palette["warn"],
        font=(family, 12, "bold"),
    ).pack(side="left")
    close = tk.Label(head, text="✕", bg=palette["card"], fg=palette["sub"], font=(family, 12),
                     cursor="hand2")
    close.pack(side="right")
    close.bind("<Button-1>", lambda _e: (root.destroy(), sys.exit(0)))
    tk.Label(
        head, text="置顶 · 拖动标题可移动", bg=palette["card"], fg=palette["sub"], font=f_small
    ).pack(side="right", padx=(0, 14))

    sub = tk.Label(
        body, text="填完点提交，演示会接着跑；按 ✕ 或 Esc 等于放弃这次提问",
        bg=palette["card"], fg=palette["sub"], font=f_small, justify="left",
    )
    sub.pack(fill="x", pady=(6, 0))

    # ---------------- 问题 ----------------
    tk.Label(
        body, text=args.question, bg=palette["card"], fg=palette["fg"], font=f_q,
        justify="left", wraplength=inner, anchor="w",
    ).pack(fill="x", pady=(14, 0))

    # ---------------- 选项（自动换行；太多就滚动） ----------------
    selected = tk.StringVar(value="")
    status = tk.Label(body, text="", bg=palette["card"], fg=palette["sub"], font=f_small)

    def pick(value: str) -> None:
        selected.set(value)
        entry_var.set(value)
        for btn, val in pill_widgets:
            btn.configure(
                bg=accent if val == value else palette["field"],
                fg="#ffffff" if val == value else palette["field_fg"],
            )

    pill_widgets: list[tuple[tk.Widget, str]] = []
    if rows:
        list_h = min(options_h, max(pill_h + 12, int(sh * 0.30)))
        holder = tk.Frame(body, bg=palette["card"])
        holder.pack(fill="x", pady=(14, 0))
        scrollable = options_h > list_h
        if scrollable:
            sub_canvas = tk.Canvas(holder, bg=palette["card"], highlightthickness=0,
                                   height=list_h, width=inner)
            bar = tk.Scrollbar(holder, orient="vertical", command=sub_canvas.yview)
            sub_canvas.configure(yscrollcommand=bar.set)
            sub_canvas.pack(side="left", fill="x", expand=True)
            bar.pack(side="right", fill="y")
            pills = tk.Frame(sub_canvas, bg=palette["card"])
            sub_canvas.create_window((0, 0), window=pills, anchor="nw", width=inner)
            pills.bind(
                "<Configure>",
                lambda _e: sub_canvas.configure(scrollregion=sub_canvas.bbox("all")),
            )
        else:
            pills = holder

        for row in rows:
            line = tk.Frame(pills, bg=palette["card"])
            line.pack(fill="x", pady=(0, 10))
            for text, w in row:
                btn = tk.Label(
                    line, text=text, bg=palette["field"], fg=palette["field_fg"],
                    font=f_opt, padx=pill_pad_x, pady=pill_pad_y, cursor="hand2",
                    wraplength=max(120, w - pill_pad_x * 2), justify="left",
                )
                btn.pack(side="left", padx=(0, 10))
                btn.bind("<Button-1>", lambda _e, v=text: pick(v))
                btn.bind("<Enter>", lambda _e, b=btn, v=text: b.configure(
                    bg=accent if selected.get() == v else _shift(palette["field"], 12)))
                btn.bind("<Leave>", lambda _e, b=btn, v=text: b.configure(
                    bg=accent if selected.get() == v else palette["field"]))
                pill_widgets.append((btn, text))

    # ---------------- 输入行（和选项并列，不重叠） ----------------
    row = tk.Frame(body, bg=palette["card"])
    row.pack(fill="x", pady=(16, 0))
    entry_var = tk.StringVar()
    entry = tk.Entry(
        row, textvariable=entry_var, bg=palette["field"], fg=palette["field_fg"],
        insertbackground=palette["fg"], relief="flat", font=f_q,
        highlightthickness=1, highlightbackground=palette["line"],
        highlightcolor=accent,
    )
    entry.pack(side="left", fill="x", expand=True, ipady=9)

    def submit(text: str) -> None:
        value = (text or "").strip()
        if not value:
            status.configure(text="先写点什么，或者点上面的选项", fg=palette["err"])
            return
        ok, msg = _post_answer(args.base, args.session, value)
        if ok:
            status.configure(text="已提交，演示继续…", fg=palette["ok"])
            btn_submit.configure(state="disabled", bg=palette["line"], text="已提交")
            entry.configure(state="disabled")
        else:
            status.configure(text=f"提交失败：{msg[:60]}", fg=palette["err"])

    btn_submit = tk.Label(
        row, text="提交", bg=accent, fg="#ffffff", font=(family, 11, "bold"),
        padx=26, pady=9, cursor="hand2",
    )
    btn_submit.pack(side="left", padx=(12, 0))
    btn_submit.bind("<Button-1>", lambda _e: submit(entry_var.get()))
    btn_submit.bind("<Enter>", lambda _e: btn_submit.configure(bg=_shift(accent, -18)))
    btn_submit.bind("<Leave>", lambda _e: btn_submit.configure(bg=accent))

    status.pack(fill="x", pady=(10, 0))
    tk.Frame(body, bg=palette["card"], height=8).pack(fill="x")

    # ---------------- 交互 ----------------
    def on_escape(_event=None):
        root.destroy()
        sys.exit(0)

    def on_close():
        root.destroy()
        sys.exit(0)

    root.bind("<Escape>", on_escape)
    entry.bind("<Return>", lambda _e: submit(entry_var.get()))

    # 拖动：按住头部空白处移动窗口
    drag = {"x": 0, "y": 0}

    def start_drag(event):
        drag["x"], drag["y"] = event.x_root, event.y_root

    def do_drag(event):
        dx = event.x_root - drag["x"]
        dy = event.y_root - drag["y"]
        root.geometry(f"+{root.winfo_x() + dx}+{root.winfo_y() + dy}")
        drag["x"], drag["y"] = event.x_root, event.y_root

    for widget in (head, body):
        widget.bind("<Button-1>", start_drag)
        widget.bind("<B1-Motion>", do_drag)

    # 会话结束后自己关掉
    def watch() -> None:
        state = _session_state(args.base, args.session)
        if state is None:
            root.after(POLL_MS, watch)
            return
        pending = state.get("pending_question") or {}
        mine = _norm_question(args.question)
        theirs = _norm_question(str(pending.get("question") or ""))
        done = (
            not pending
            or not theirs
            or not mine.startswith(theirs[:80])
            and not theirs.startswith(mine[:80])
            or state.get("status") not in ("waiting", "paused", "running")
        )
        if done:
            try:
                root.destroy()
            except Exception:  # noqa: BLE001
                pass
            return
        root.after(POLL_MS, watch)

    # ---- 按实际内容高度定窗口大小 ----
    # 注意：body 挂在 canvas 里，只调 root.update_idletasks() 拿到的 reqheight 会是 1，
    # 必须再对 body 自己 update 一次，布局才算完（踩过：窗口被压成 240 高，输入框被裁掉）。
    root.update_idletasks()
    body.update_idletasks()
    need = int(body.winfo_reqheight()) + 22 + 34
    max_h = int(sh * 0.82)
    final_h = int(max(260, min(need, max_h)))
    if final_h != height:
        height = final_h
        root.geometry(f"{width}x{height}+{int((sw - width) / 2)}+{int(sh * 0.14)}")
        canvas.configure(width=width, height=height)
        paint_card(width, height)
        canvas.itemconfigure(body_win, width=inner)
    root.deiconify()
    _force_show(root)
    for delay in (60, 220, 800):
        root.after(delay, lambda: _force_show(root))
    root.after(120, lambda: entry.focus_force())
    root.after(POLL_MS, watch)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())