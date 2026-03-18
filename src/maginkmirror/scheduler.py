"""Scheduler – background fetch loop for all plugins."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import as_completed
from concurrent.futures import Future, ThreadPoolExecutor

from maginkmirror.plugins import BasePlugin, PluginData

log = logging.getLogger(__name__)

RenderCallback = Callable[[str, PluginData], None]
RenderBatchCallback = Callable[[dict[str, PluginData]], None]


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
        render_batch_cb: RenderBatchCallback,
        max_workers: int = 4,
        display_refresh_interval: float = -1.0,
    ) -> None:
        self._plugins = plugins
        self._render_cb = render_cb
        self._render_batch_cb = render_batch_cb
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="plugin")
        self._next_run: dict[str, float] = dict.fromkeys(plugins, 0.0)
        self._futures: dict[str, Future] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._display_refresh_interval = float(display_refresh_interval)
        self._pending_lock = threading.Lock()
        self._pending: dict[str, PluginData] = {}

    # ------------------------------------------------------------------

    def _plugin_interval(self, name: str, plugin: BasePlugin) -> float:
        """Return plugin interval seconds, with basic sanity fallback."""
        try:
            interval = float(getattr(plugin, "interval", 0))
        except Exception:
            interval = 0.0

        if interval <= 0:
            log.warning("[%s] invalid interval=%r; using 1s fallback", name, getattr(plugin, "interval", None))
            return 1.0

        return interval

    def start(self) -> None:
        """Start the scheduler."""
        log.info("Starting scheduler (%d plugins)", len(self._plugins))
        self._stop_event.clear()

        # Initial fetch: block until every plugin produces a first value (or error).
        # Without this, a global display_refresh_interval can delay the first frame.
        self._initial_fetch_and_render()

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
        next_display = time.monotonic()
        while not self._stop_event.is_set():
            now = time.monotonic()
            for name, plugin in self._plugins.items():
                # Skip if a fetch is still in-flight
                if name in self._futures and not self._futures[name].done():
                    continue
                if now >= self._next_run[name]:
                    self._next_run[name] = now + self._plugin_interval(name, plugin)
                    self._futures[name] = self._executor.submit(self._fetch_and_notify, name, plugin)

            if (self._display_refresh_interval != -1) and (now >= next_display):
                with self._pending_lock:
                    pending = dict(self._pending)
                    self._pending.clear()
                if pending:
                    try:
                        self._render_batch_cb(pending)
                    except Exception as exc:
                        log.error("render batch callback raised: %s", exc)

                next_display = now if self._display_refresh_interval <= 0 else now + self._display_refresh_interval

            wait_for = 1.0
            if self._display_refresh_interval != -1 and self._display_refresh_interval > 0:
                wait_for = min(wait_for, self._display_refresh_interval / 2)
            self._stop_event.wait(timeout=wait_for)

    def _initial_fetch_and_render(self, timeout: float = 30.0) -> None:
        start = time.monotonic()
        futures: dict[Future, tuple[str, BasePlugin]] = {}

        for name, plugin in self._plugins.items():
            futures[self._executor.submit(self._fetch_only, name, plugin)] = (name, plugin)

        results: dict[str, PluginData] = {}
        for fut in as_completed(futures, timeout=timeout):
            name, plugin = futures[fut]
            try:
                data = fut.result()
            except Exception as exc:
                data = plugin.on_fetch_error(exc)

            if data is not None:
                results[name] = data

        elapsed = time.monotonic() - start
        log.info("Initial fetch complete: %d/%d plugins in %.2fs", len(results), len(self._plugins), elapsed)

        if not results:
            return

        # Seed next_run so the next scheduled fetch happens after the interval.
        now = time.monotonic()
        for name, plugin in self._plugins.items():
            self._next_run[name] = now + self._plugin_interval(name, plugin)

        try:
            if self._display_refresh_interval == -1:
                for name, data in results.items():
                    self._render_cb(name, data)
            else:
                self._render_batch_cb(results)
        except Exception as exc:
            log.error("Initial render raised: %s", exc)

    def _fetch_only(self, name: str, plugin: BasePlugin) -> PluginData:
        """Fetch and run success hook; raise on error."""
        data = plugin.fetch()
        return plugin.on_fetch_success(data)

    def _fetch_and_notify(self, name: str, plugin: BasePlugin) -> None:
        try:
            data = plugin.fetch()
            result = plugin.on_fetch_success(data)
        except Exception as exc:
            result = plugin.on_fetch_error(exc)

        if result is not None:
            if self._display_refresh_interval == -1:
                try:
                    self._render_cb(name, result)
                except Exception as exc:
                    log.error("[%s] render callback raised: %s", name, exc)
            else:
                with self._pending_lock:
                    self._pending[name] = result
