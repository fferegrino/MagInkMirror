"""Scheduler – background fetch loop for all plugins."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from maginkmirror.plugins import BasePlugin, PluginData

log = logging.getLogger(__name__)

RenderCallback = Callable[[str, PluginData], None]


class Scheduler:
    """
    Runs each plugin's fetch() on a thread pool at its own interval.

    When new data arrives it calls render_cb(plugin_name, data) on the
    calling thread (i.e. the scheduler loop) – the layout engine then
    decides whether to do a full or partial refresh.
    """

    def __init__(
        self,
        plugins: dict[str, BasePlugin],
        render_cb: RenderCallback,
        max_workers: int = 4,
    ) -> None:
        self._plugins = plugins
        self._render_cb = render_cb
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="plugin")
        self._next_run: dict[str, float] = dict.fromkeys(plugins, 0.0)
        self._futures: dict[str, Future] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler."""
        log.info("Starting scheduler (%d plugins)", len(self._plugins))
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()
        log.info("Scheduler started (%d plugins)", len(self._plugins))

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the scheduler."""
        log.info("Stopping scheduler...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout)
        self._executor.shutdown(wait=False)
        log.info("Scheduler stopped")

    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.monotonic()
            for name, plugin in self._plugins.items():
                # Skip if a fetch is still in-flight
                if name in self._futures and not self._futures[name].done():
                    continue
                if now >= self._next_run[name]:
                    self._next_run[name] = now + plugin.interval
                    self._futures[name] = self._executor.submit(self._fetch_and_notify, name, plugin)
            self._stop_event.wait(timeout=1.0)

    def _fetch_and_notify(self, name: str, plugin: BasePlugin) -> None:
        try:
            data = plugin.fetch()
            result = plugin.on_fetch_success(data)
        except Exception as exc:
            result = plugin.on_fetch_error(exc)

        if result is not None:
            try:
                self._render_cb(name, result)
            except Exception as exc:
                log.error("[%s] render callback raised: %s", name, exc)
