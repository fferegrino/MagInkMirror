"""Todoist plugin – renders tasks from Todoist for a given project."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

from PIL import Image, ImageDraw

from maginkmirror.core.fonts import load_font
from maginkmirror.plugins import BasePlugin, PluginData, Zone

PLUGIN_CLASS = "TodoistPlugin"

_DEFAULT_HEADERS = {
    # Some endpoints reject requests without a UA.
    "User-Agent": "MagInkMirror/1.0 (+https://github.com/antonioferegrino/MagInkMirror)",
    "Accept": "application/json,*/*;q=0.9",
}


def _urlopen_json(url: str, *, headers: dict[str, str], timeout: int) -> Any:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body)


def _as_due_str(due: dict[str, Any] | None) -> str | None:
    """
    Convert Todoist v1 `due` object into a compact display string.

    Todoist API v1 returns a due object with a human readable `string`
    (in the authenticated user's timezone). We prefer that for display.
    """
    if not due:
        return None

    string_raw = due.get("string")
    if isinstance(string_raw, str) and string_raw.strip():
        return string_raw.strip()

    date_raw = due.get("date")
    if isinstance(date_raw, str) and date_raw.strip():
        # Best-effort fallback if `string` is missing.
        # Full-day dates are typically YYYY-MM-DD.
        return date_raw.strip()[:10]

    return None


def _due_sort_key(due: dict[str, Any] | None) -> tuple[float, str]:
    """
    Sort tasks by due datetime when available.

    Returns `(timestamp, "")` where timestamp is derived from `due.date`.
    Undated tasks sort last.
    """
    if not due or not isinstance(due, dict):
        return (float("inf"), "")

    date_raw = due.get("date")
    if not isinstance(date_raw, str) or not date_raw.strip():
        return (float("inf"), "")

    # Try to parse RFC3339-ish timestamps.
    iso = date_raw.strip()
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            # `due.date` can be a "floating" datetime without timezone info.
            # For stable ordering, treat it as UTC.
            dt = dt.replace(tzinfo=UTC)
        return (dt.timestamp(), "")
    except Exception:
        return (float("inf"), "")


def _shorten_to_width(draw: ImageDraw.ImageDraw, text: str, *, font, max_width: int) -> str:
    """Truncate `text` with an ellipsis so it fits `max_width` pixels."""
    text = (text or "").strip()
    if not text:
        return ""

    bbox = draw.textbbox((0, 0), text, font=font)
    if (bbox[2] - bbox[0]) <= max_width:
        return text

    ellipsis = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        cand = text[:mid] + ellipsis
        bbox = draw.textbbox((0, 0), cand, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            lo = mid + 1
        else:
            hi = mid

    final = text[: max(0, lo - 1)] + ellipsis
    return final


class TodoistPlugin(BasePlugin):
    """
    Todoist plugin.

    Config under `[plugins.todoist]` (all required for meaningful output):
    - `access_token`: Todoist access token (used as Bearer token)
    - `project_id`: project id to list tasks from

    Optional:
    - `max_items`: number of tasks to render (default 5)
    - `timeout`: HTTP timeout seconds (default 10)
    - `show_dates`: include due dates (default true)
    - `task_font` / `task_font_size`
    - `headline_font` / `headline_font_size`
    """

    name = "todoist"
    interval = 60

    def fetch(self) -> PluginData:
        # Todoist uses an OAuth access token for Bearer auth.
        access_token = self.config.get("access_token")
        project_id = self.config.get("project_id")

        if not access_token or not project_id:
            return PluginData(
                payload={"items": []},
                error="plugins.todoist.access_token and plugins.todoist.project_id are required",
                changed=False,
            )

        max_items = int(self.config.get("max_items", 5))
        max_items = max(1, max_items)
        timeout = int(self.config.get("timeout", 10))
        show_dates = bool(self.config.get("show_dates", True))

        # Todoist API v1: list tasks filtered by project_id.
        # Endpoint returns: { "results": [...], "next_cursor": "..." | null }
        base_url = "https://api.todoist.com/api/v1/tasks"

        headers = dict(_DEFAULT_HEADERS)
        headers["Authorization"] = f"Bearer {access_token}"

        per_page = min(200, max_items)
        cursor: str | None = None
        collected: list[dict[str, Any]] = []

        while len(collected) < max_items:
            params: dict[str, Any] = {"project_id": str(project_id), "limit": per_page}
            if cursor:
                params["cursor"] = cursor

            url = f"{base_url}?{urllib.parse.urlencode(params)}"
            try:
                data = _urlopen_json(url, headers=headers, timeout=timeout)
            except Exception as exc:
                return PluginData(
                    payload={"items": []},
                    error=f"Todoist fetch failed: {exc}",
                    changed=False,
                )

            if not isinstance(data, dict):
                return PluginData(payload={"items": []}, error="Todoist returned non-object JSON", changed=False)

            results = data.get("results") or []
            if not isinstance(results, list):
                results = []

            for t in results:
                if not isinstance(t, dict):
                    continue
                # `GET /tasks` returns active tasks, but keep a safety check.
                if t.get("checked") is True:
                    continue
                collected.append(t)
                if len(collected) >= max_items:
                    break

            cursor = data.get("next_cursor")
            if cursor is None or cursor == "":
                break

        collected.sort(
            key=lambda t: (
                _due_sort_key(t.get("due") if isinstance(t.get("due"), dict) else None)[0],
                str(t.get("id") or ""),
            )
        )

        selected = collected[:max_items]

        payload_items: list[dict[str, Any]] = []
        for t in selected:
            content = str(t.get("content", "") or "").strip()
            due_str = _as_due_str(t.get("due") if isinstance(t.get("due"), dict) else None) if show_dates else None
            payload_items.append(
                {
                    "id": t.get("id"),
                    "content": content,
                    "due": due_str,
                }
            )

        return PluginData(payload={"items": payload_items})

    def render(self, data: PluginData, image: Image.Image, zone: Zone) -> None:
        draw = ImageDraw.Draw(image)
        fill = 0

        headline_font = load_font(
            self.config,
            self.config.get("headline_font", "Merriweather"),
            int(self.config.get("headline_font_size", 20)),
        )
        task_font = load_font(
            self.config, self.config.get("task_font", "Merriweather"), int(self.config.get("task_font_size", 16))
        )

        padding_x = zone.width_percent_int(4)
        x_center = zone.width // 2

        y = zone.height_percent_int(6)
        draw.text((x_center, y), "Todoist", font=headline_font, fill=fill, anchor="mm")
        y += zone.height_percent_int(4)

        if data.error:
            draw.text((padding_x, y), data.error, font=task_font, fill=fill)
            return

        p = data.payload or {}
        items: list[dict[str, Any]] = list(p.get("items") or [])

        if not items:
            draw.text((padding_x, y), "No tasks", font=task_font, fill=fill)
            return

        gap = max(2, zone.height_percent_int(2))
        max_width = max(1, zone.width - (2 * padding_x))

        for it in items:
            content = str(it.get("content", "") or "").strip()
            due = it.get("due")
            if isinstance(due, str) and due:
                line = f"{content} ({due})" if content else due
            else:
                line = content

            if not line:
                continue

            line = _shorten_to_width(draw, line, font=task_font, max_width=max_width)
            bbox = draw.textbbox((0, 0), line, font=task_font)
            text_w = bbox[2] - bbox[0]
            x = int(round((zone.width - text_w) / 2))

            draw.text((x, y), line, font=task_font, fill=fill)
            y += (bbox[3] - bbox[1]) + gap

            if y >= zone.height:
                break
