"""
Priority queue backed by heapq with stable ordering via insertion counter.
"""
import heapq
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass(order=True)
class _Item:
    priority: float
    seq: int = field(compare=True)
    payload: Any = field(compare=False)


class PriorityQueue:
    def __init__(self):
        self._heap: list[_Item] = []
        self._counter = 0
        self._lock = threading.Lock()

    def push(self, item: Any, priority: float = 0) -> None:
        with self._lock:
            heapq.heappush(self._heap, _Item(priority, self._counter, item))
            self._counter += 1

    def pop(self) -> Any:
        with self._lock:
            if not self._heap:
                raise IndexError("pop from empty PriorityQueue")
            return heapq.heappop(self._heap).payload

    def peek(self) -> Any:
        with self._lock:
            if not self._heap:
                raise IndexError("peek on empty PriorityQueue")
            return self._heap[0].payload

    def __len__(self) -> int:
        with self._lock:
            return len(self._heap)

    def is_empty(self) -> bool:
        return len(self) == 0

    def push_many(self, items: list[tuple[Any, float]]) -> None:
        with self._lock:
            for payload, priority in items:
                heapq.heappush(self._heap, _Item(priority, self._counter, payload))
                self._counter += 1

    def drain(self, n: int | None = None) -> list[Any]:
        with self._lock:
            k = n if n is not None else len(self._heap)
            result = []
            for _ in range(min(k, len(self._heap))):
                result.append(heapq.heappop(self._heap).payload)
            return result
