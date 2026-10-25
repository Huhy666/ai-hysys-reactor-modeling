import threading
import time

import pytest

from app.hysys import com_worker
from app.hysys.com_worker import ComWorker


class FakePythonCom:
    COINIT_APARTMENTTHREADED = 2

    def __init__(self) -> None:
        self.initialized_thread = None
        self.uninitialized_thread = None
        self.flags = None

    def CoInitializeEx(self, flags):
        self.flags = flags
        self.initialized_thread = threading.get_ident()

    def CoUninitialize(self):
        self.uninitialized_thread = threading.get_ident()


def test_com_worker_initializes_one_sta_thread_and_serializes_calls(monkeypatch):
    api = FakePythonCom()
    monkeypatch.setattr(com_worker, "_load_pythoncom", lambda: api)
    worker = ComWorker()
    order: list[tuple[str, int]] = []

    worker.start()

    def first():
        order.append(("first-start", threading.get_ident()))
        time.sleep(0.01)
        order.append(("first-end", threading.get_ident()))
        return 1

    def second():
        order.append(("second", threading.get_ident()))
        return 2

    first_future = worker.submit(first)
    second_future = worker.submit(second)

    assert first_future.result(timeout=1) == 1
    assert second_future.result(timeout=1) == 2
    worker.stop()

    assert [item[0] for item in order] == ["first-start", "first-end", "second"]
    assert {item[1] for item in order} == {api.initialized_thread}
    assert api.flags == api.COINIT_APARTMENTTHREADED
    assert api.uninitialized_thread == api.initialized_thread


def test_com_worker_returns_exceptions_through_future(monkeypatch):
    api = FakePythonCom()
    monkeypatch.setattr(com_worker, "_load_pythoncom", lambda: api)
    worker = ComWorker()
    worker.start()

    def fail():
        raise RuntimeError("COM failure")

    future = worker.submit(fail)

    with pytest.raises(RuntimeError, match="COM failure"):
        future.result(timeout=1)
    worker.stop()

