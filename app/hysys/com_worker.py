import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, TypeVar

T = TypeVar("T")
_STOP = object()


def _load_pythoncom():
    import pythoncom

    return pythoncom


class ComWorker:
    """Runs every COM call serially on one initialized STA thread."""

    def __init__(self) -> None:
        self._queue: queue.Queue[object] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._run,
            name="hysys-com-sta",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise TimeoutError("COM worker did not initialize")
        if self._startup_error is not None:
            raise RuntimeError("COM worker initialization failed") from self._startup_error

    def submit(self, function: Callable[..., T], *args: Any, **kwargs: Any) -> Future[T]:
        if self._thread is None or not self._thread.is_alive():
            raise RuntimeError("COM worker is not running")
        future: Future[T] = Future()
        self._queue.put((future, function, args, kwargs))
        return future

    def stop(self) -> None:
        if self._thread is None:
            return
        self._queue.put(_STOP)
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            raise TimeoutError("COM worker did not stop")
        self._thread = None

    def _run(self) -> None:
        try:
            pythoncom = _load_pythoncom()
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            return

        self._ready.set()
        try:
            while True:
                item = self._queue.get()
                if item is _STOP:
                    return
                future, function, args, kwargs = item
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    future.set_result(function(*args, **kwargs))
                except BaseException as exc:
                    future.set_exception(exc)
        finally:
            pythoncom.CoUninitialize()
