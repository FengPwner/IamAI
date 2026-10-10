import pytest
import threading
from snippets.priority_queue import PriorityQueue


class TestPriorityQueue:
    def test_push_pop_order(self):
        pq = PriorityQueue()
        pq.push("low", 10)
        pq.push("high", 1)
        pq.push("mid", 5)
        assert pq.pop() == "high"
        assert pq.pop() == "mid"
        assert pq.pop() == "low"

    def test_stable_fifo_same_priority(self):
        pq = PriorityQueue()
        pq.push("a", 0)
        pq.push("b", 0)
        pq.push("c", 0)
        assert pq.pop() == "a"
        assert pq.pop() == "b"
        assert pq.pop() == "c"

    def test_pop_empty_raises(self):
        pq = PriorityQueue()
        with pytest.raises(IndexError):
            pq.pop()

    def test_peek_empty_raises(self):
        pq = PriorityQueue()
        with pytest.raises(IndexError):
            pq.peek()

    def test_peek_returns_top(self):
        pq = PriorityQueue()
        pq.push("low", 10)
        pq.push("high", 1)
        assert pq.peek() == "high"
        assert len(pq) == 2

    def test_len(self):
        pq = PriorityQueue()
        assert len(pq) == 0
        pq.push("a", 0)
        assert len(pq) == 1
        pq.pop()
        assert len(pq) == 0

    def test_is_empty(self):
        pq = PriorityQueue()
        assert pq.is_empty()
        pq.push("x", 0)
        assert not pq.is_empty()

    def test_push_many(self):
        pq = PriorityQueue()
        pq.push_many([("a", 3), ("b", 1), ("c", 2)])
        assert pq.pop() == "b"
        assert pq.pop() == "c"
        assert pq.pop() == "a"

    def test_drain_partial(self):
        pq = PriorityQueue()
        pq.push_many([("a", 5), ("b", 3), ("c", 1), ("d", 4)])
        result = pq.drain(2)
        assert result == ["c", "b"]
        assert len(pq) == 2

    def test_drain_all(self):
        pq = PriorityQueue()
        pq.push_many([("a", 2), ("b", 1)])
        result = pq.drain()
        assert result == ["b", "a"]
        assert pq.is_empty()

    def test_negative_priority(self):
        pq = PriorityQueue()
        pq.push("a", -1)
        pq.push("b", 0)
        pq.push("c", 1)
        assert pq.pop() == "a"

    def test_thread_safety(self):
        pq = PriorityQueue()
        errors = []

        def pusher(start, count):
            try:
                for i in range(start, start + count):
                    pq.push(i, priority=i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=pusher, args=(i * 100, 100)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(pq) == 400
        prev = pq.pop()
        for _ in range(399):
            curr = pq.pop()
            assert curr > prev
            prev = curr
