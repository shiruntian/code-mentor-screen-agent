"""进程内事件总线：给屏幕控制会话提供 SSE 广播 + 新订阅者回放。"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class EventBus:
    def __init__(self, history_size: int = 120):
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=history_size))

    def subscribe(self, channel: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subs[channel].add(queue)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue) -> None:
        self._subs[channel].discard(queue)

    def history(self, channel: str) -> list[dict[str, Any]]:
        return list(self._history[channel])

    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        self._history[channel].append(event)
        for queue in list(self._subs[channel]):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover
                logger.warning("事件队列已满，丢弃一条事件: %s", channel)

    def clear(self, channel: str) -> None:
        self._history.pop(channel, None)
        self._subs.pop(channel, None)


bus = EventBus()