"""系统状态工具（前台窗口 / 进程列表）的单元测试：只测纯解析逻辑，不动真实进程表。"""

from __future__ import annotations

from app.agent.tools import sysinfo

# 中文系统上 tasklist /FO CSV /NH 的真实输出形状
SAMPLE = (
    '"System Idle Process","0","Services","0","8 K"\r\n'
    '"chrome.exe","1234","Console","1","1,234,568 K"\r\n'
    '"mysqld.exe","10112","Services","0","416,000 K"\r\n'
    '"Notepad.exe","5678","Console","1","12,345 K"\r\n'
)

# ------------------------------------------------------------------ 内存解析


def test_parse_mem_kb_handles_thousand_separators():
    assert sysinfo.parse_mem_kb("1,234,568 K") == 1234568
    assert sysinfo.parse_mem_kb("12,345 K") == 12345
    assert sysinfo.parse_mem_kb("8 K") == 8


def test_parse_mem_kb_handles_other_separators():
    # 某些语言环境用空格或点做千分位
    assert sysinfo.parse_mem_kb("1 234 K") == 1234
    assert sysinfo.parse_mem_kb("1.234 K") == 1234


def test_parse_mem_kb_returns_minus_one_when_unparsable():
    assert sysinfo.parse_mem_kb("") == -1
    assert sysinfo.parse_mem_kb("N/A") == -1
    assert sysinfo.parse_mem_kb(None) == -1  # type: ignore[arg-type]


# ------------------------------------------------------------------ 进程表解析


def test_parse_tasklist_reads_name_pid_mem():
    items = sysinfo.parse_tasklist(SAMPLE)
    assert len(items) == 4
    assert items[1] == {"name": "chrome.exe", "pid": 1234, "mem_kb": 1234568}


def test_parse_tasklist_skips_header_and_broken_rows():
    text = '"Image Name","PID","Session Name","Session#","Mem Usage"\r\n' + SAMPLE
    items = sysinfo.parse_tasklist(text)
    assert all(i["name"].lower() != "image name" for i in items)
    assert len(items) == 4

    broken = '"good.exe","42","Console","1","100 K"\r\n"nopid.exe","abc","Console","1","1 K"\r\n'
    rows = sysinfo.parse_tasklist(broken)
    assert [r["name"] for r in rows] == ["good.exe"]


def test_parse_tasklist_empty_input():
    assert sysinfo.parse_tasklist("") == []
    assert sysinfo.parse_tasklist(None) == []  # type: ignore[arg-type]


# ------------------------------------------------------------------ 过滤 / 排序


def _items():
    return sysinfo.parse_tasklist(SAMPLE)


def test_select_processes_filters_by_name_substring():
    picked, total = sysinfo.select_processes(_items(), keyword="sql")
    assert total == 1
    assert picked[0]["name"] == "mysqld.exe"


def test_select_processes_filters_by_pid():
    picked, total = sysinfo.select_processes(_items(), keyword="5678")
    assert total == 1
    assert picked[0]["name"] == "Notepad.exe"


def test_select_processes_case_insensitive():
    assert sysinfo.select_processes(_items(), keyword="CHROME")[1] == 1


def test_select_processes_sorts_by_memory_desc():
    picked, _ = sysinfo.select_processes(_items(), sort="memory", limit=2)
    assert [p["name"] for p in picked] == ["chrome.exe", "mysqld.exe"]


def test_select_processes_sorts_by_name_and_pid():
    by_name, _ = sysinfo.select_processes(_items(), sort="name")
    assert [p["name"] for p in by_name] == ["chrome.exe", "mysqld.exe", "Notepad.exe", "System Idle Process"]
    by_pid, _ = sysinfo.select_processes(_items(), sort="pid")
    assert [p["pid"] for p in by_pid] == [0, 1234, 5678, 10112]


def test_select_processes_respects_limit_and_floor():
    assert len(sysinfo.select_processes(_items(), limit=3)[0]) == 3
    # limit 传 0 / 负数也要返回 1 条，不能变成空
    assert len(sysinfo.select_processes(_items(), limit=0)[0]) == 1


def test_select_processes_unknown_sort_falls_back_to_memory():
    picked, _ = sysinfo.select_processes(_items(), sort="bogus", limit=1)
    assert picked[0]["name"] == "chrome.exe"


def test_select_processes_no_match_returns_zero():
    picked, total = sysinfo.select_processes(_items(), keyword="definitely-not-running")
    assert picked == []
    assert total == 0


# ------------------------------------------------------------------ 展示


def test_human_mb_formats():
    assert sysinfo.human_mb(-1) == "?"
    assert sysinfo.human_mb(0) == "0.0 MB"
    assert sysinfo.human_mb(512) == "0.5 MB"
    assert sysinfo.human_mb(12 * 1024) == "12 MB"
    assert sysinfo.human_mb(1024 * 1024) == "1.0 GB"
    assert sysinfo.human_mb(1536 * 1024) == "1.5 GB"