"""进程级单例：向量库、屏幕控制器、启动时间。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppState:
    store: Any = None
    screen: Any = None
    started_at: float = field(default_factory=time.time)

    def uptime(self) -> float:
        return round(time.time() - self.started_at, 1)


state = AppState()