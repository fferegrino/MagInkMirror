"""Notion plugin – board view of database pages grouped by a Status column."""

from __future__ import annotations

import logging
import os
from typing import Any

from PIL import Image, ImageDraw

from maginkmirror.core.colors import Color
from maginkmirror.core.fonts import load_font
from maginkmirror.plugins import BasePlugin, PluginData, Zone

PLUGIN_CLASS = "NotionPlugin"

log = logging.getLogger(__name__)

_UNASSIGNED = "Unassigned"
_UUID_HEX_LEN = 32

# Ascenders + descenders; stabilizes line height across task rows (same idea as the Pokémon plugin).
_TASK_LINE_REF_TEXT = "gjylth"


def _rich_text_plain(rich_text: list[Any] | None) -> str:
    if not rich_text:
        return ""
    out: list[str] = []
    for part in rich_text:
        if isinstance(part, dict):
            out.append(str(part.get("plain_text", "") or ""))
    return "".join(out)


def _normalize_database_id(raw: str) -> str:
    s = str(raw).strip()
    hex_only = s.replace("-", "")
    if len(hex_only) == _UUID_HEX_LEN:
        return f"{hex_only[:8]}-{hex_only[8:12]}-{hex_only[12:16]}-{hex_only[16:20]}-{hex_only[20:]}"
    return s


def _title_property_name(properties: dict[str, Any]) -> str | None:
    for name, meta in properties.items():
        if isinstance(meta, dict) and meta.get("type") == "title":
            return name
    return None


def _status_options_order(properties: dict[str, Any], status_prop: str) -> list[str]:
    sp = properties.get(status_prop)
    if not isinstance(sp, dict):
        return []
    if sp.get("type") == "select":
        opts = (sp.get("select") or {}).get("options") or []
        return [str(o["name"]) for o in opts if isinstance(o, dict) and o.get("name")]
    if sp.get("type") == "status":
        opts = (sp.get("status") or {}).get("options") or []
        return [str(o["name"]) for o in opts if isinstance(o, dict) and o.get("name")]
    return []


def _page_title(properties: dict[str, Any], title_name: str) -> str:
    p = properties.get(title_name)
    if not isinstance(p, dict) or p.get("type") != "title":
        return ""
    return _rich_text_plain(p.get("title")).strip()


def _page_status(properties: dict[str, Any], status_name: str) -> str | None:
    p = properties.get(status_name)
    if not isinstance(p, dict):
        return None
    t = p.get("type")
    if t == "select":
        sel = p.get("select")
        if isinstance(sel, dict) and sel.get("name"):
            return str(sel["name"])
        return None
    if t == "status":
        st = p.get("status")
        if isinstance(st, dict) and st.get("name"):
            return str(st["name"])
        return None
    return None


def _text_width(draw: ImageDraw.ImageDraw, text: str, *, font: Any) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _shorten_to_width(draw: ImageDraw.ImageDraw, text: str, *, font: Any, max_width: int) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if _text_width(draw, text, font=font) <= max_width:
        return text
    ellipsis = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        cand = text[:mid] + ellipsis
        if _text_width(draw, cand, font=font) <= max_width:
            lo = mid + 1
        else:
            hi = mid
    return text[: max(0, lo - 1)] + ellipsis


def _break_long_word(draw: ImageDraw.ImageDraw, word: str, *, font: Any, max_width: int) -> list[str]:
    """Split a single word into segments that fit ``max_width`` (character-wise)."""
    if not word:
        return []
    out: list[str] = []
    chunk = ""
    for ch in word:
        cand = chunk + ch
        if _text_width(draw, cand, font=font) <= max_width:
            chunk = cand
        else:
            if chunk:
                out.append(chunk)
            chunk = ch
    if chunk:
        out.append(chunk)
    return out


def _wrap_paragraph_to_width(draw: ImageDraw.ImageDraw, paragraph: str, *, font: Any, max_width: int) -> list[str]:
    """Greedy word-wrap; oversize words are broken so the full paragraph is kept."""
    para = paragraph.strip()
    if not para:
        return []
    if max_width < 1:
        return [para]
    lines: list[str] = []
    words = para.split()
    current: list[str] = []
    for w in words:
        candidate = w if not current else " ".join([*current, w])
        if _text_width(draw, candidate, font=font) <= max_width:
            current.append(w)
            continue
        if current:
            lines.append(" ".join(current))
            current = []
        if _text_width(draw, w, font=font) <= max_width:
            current.append(w)
        else:
            lines.extend(_break_long_word(draw, w, font=font, max_width=max_width))
    if current:
        lines.append(" ".join(current))
    return lines


def _wrap_title_lines(draw: ImageDraw.ImageDraw, text: str, *, font: Any, max_width: int) -> list[str]:
    """Wrap title text to fit width; honors newlines in the source string."""
    raw = (text or "").strip()
    if not raw:
        return []
    out: list[str] = []
    for para in raw.splitlines():
        out.extend(_wrap_paragraph_to_width(draw, para, font=font, max_width=max_width))
    return out


def _merge_column_order(schema_order: list[str], seen: set[str], configured: list[str] | None) -> list[str]:
    out: list[str] = []
    if configured:
        for name in configured:
            if name in seen and name not in out:
                out.append(name)
    for name in schema_order:
        if name in seen and name not in out:
            out.append(name)
    rest = sorted(s for s in seen if s not in out)
    out.extend(rest)
    return out


def _parse_column_order(raw: Any) -> list[str] | None:
    if isinstance(raw, list):
        return [str(x) for x in raw if x is not None]
    if isinstance(raw, str) and raw.strip():
        return [s.strip() for s in raw.split(",") if s.strip()]
    return None


def _bucket_pages_by_status(
    pages: list[Any],
    *,
    title_name: str,
    status_prop: str,
) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        props = page.get("properties")
        if not isinstance(props, dict):
            continue
        title = _page_title(props, title_name)
        if not title:
            continue
        st = _page_status(props, status_prop)
        key = st if st else _UNASSIGNED
        buckets.setdefault(key, []).append(title)
    for names in buckets.values():
        names.sort(key=str.casefold)
    return buckets


def _status_option_colors(status_property: dict[str, Any] | None) -> dict[str, str]:
    """Map status/option display names to Notion color ids for theming."""
    out: dict[str, str] = {}
    if not isinstance(status_property, dict):
        return out
    ptype = status_property.get("type")
    raw_opts: list[Any] = []
    if ptype == "status":
        raw_opts = list((status_property.get("status") or {}).get("options") or [])
    elif ptype == "select":
        raw_opts = list((status_property.get("select") or {}).get("options") or [])
    for option in raw_opts:
        if isinstance(option, dict) and option.get("name"):
            out[str(option["name"])] = str(option.get("color") or "default")
    return out


class NotionPlugin(BasePlugin):
    """
    Notion board plugin – queries a Notion database and renders tasks in columns by Status.

    Install the client (contrib dependency group): ``uv sync --group contrib``.

    Config under ``[plugins.notion]``:

    - ``token``: integration secret (or set env ``NOTION_TOKEN``)
    - ``database_id``: Notion database id (with or without hyphens)

    Optional:

    - ``status_property``: property name for columns (default ``Status``)
    - ``title_property``: title column name; if omitted, the first title property is used
    - ``column_order``: list of status names left-to-right (unknown names are ignored;
      remaining columns follow schema order, then alphabetical)
    - ``max_tasks_per_column``: max task lines per column (default 12)
    - ``timeout``: HTTP timeout seconds (default 15)
    - ``headline`` / ``headline_font`` / ``headline_font_size``
    - ``task_font`` / ``task_font_size``
    - ``column_header_font_size``: defaults between headline and task size
    - ``show_headline``: show the top board title (default ``true``)
    - ``show_column_headlines``: show each column's status name above its tasks (default ``true``)
    - ``column_top_padding``: extra space below the column strip top before headers/tasks (pixels;
      default scales with zone height)
    - ``task_padding_x`` / ``task_padding_y``: horizontal / vertical padding inside each task pill
      (defaults scale with zone size)
    """

    name = "notion"
    interval = 120

    def fetch(self) -> PluginData:
        """Load pages from the configured Notion database and group them by Status."""
        try:
            from notion_client import Client
            from notion_client.helpers import collect_paginated_api
        except ImportError:
            return PluginData(
                payload={"columns": []},
                error="notion-client is required: install with `uv sync --group contrib`",
                changed=False,
            )

        token = self.config.get("token") or os.environ.get("NOTION_TOKEN")
        database_raw = self.config.get("database_id")
        if not token or not database_raw:
            return PluginData(
                payload={"columns": []},
                error="plugins.notion.token (or NOTION_TOKEN) and plugins.notion.database_id are required",
                changed=False,
            )

        tok = str(token).strip()
        db_raw = str(database_raw)
        return self._fetch_with_client(Client, collect_paginated_api, tok, db_raw)

    def _fetch_with_client(
        self,
        client_cls: Any,
        collect_paginated_api: Any,
        token: str,
        database_raw: str,
    ) -> PluginData:
        database_id = _normalize_database_id(database_raw)
        status_prop = str(self.config.get("status_property", "Status"))
        title_override = self.config.get("title_property")
        title_override = str(title_override).strip() if title_override else None
        timeout_s = int(self.config.get("timeout", 15))
        timeout_ms = max(1000, timeout_s * 1000)

        from notion_client import Client

        client: Client = client_cls(auth=token, timeout_ms=timeout_ms)

        try:
            db = client.databases.retrieve(database_id=database_id)
            [data_source] = db.get("data_sources") or []
            data_source = client.data_sources.retrieve(data_source_id=data_source.get("id"))
        except Exception as exc:
            log.warning("Notion database retrieve failed: %s", exc)
            return PluginData(payload={"columns": []}, error=f"Notion database error: {exc}", changed=False)

        properties = data_source.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}

        title_name = title_override if title_override else _title_property_name(properties)
        if not title_name:
            return PluginData(
                payload={"columns": []},
                error="No title property found; set plugins.notion.title_property",
                changed=False,
            )

        sp_meta = properties.get(status_prop)
        if not isinstance(sp_meta, dict) or sp_meta.get("type") not in ("select", "status"):
            return PluginData(
                payload={"columns": []},
                error=f"Property {status_prop!r} must be a Notion select or status field",
                changed=False,
            )

        schema_order = _status_options_order(properties, status_prop)
        sp_conf = properties.get(status_prop)
        color_map = _status_option_colors(sp_conf if isinstance(sp_conf, dict) else None)
        try:
            pages = collect_paginated_api(client.data_sources.query, data_source_id=data_source.get("id"))
        except Exception as exc:
            log.warning("Notion query failed: %s", exc)
            return PluginData(payload={"columns": []}, error=f"Notion query failed: {exc}", changed=False)

        buckets = _bucket_pages_by_status(pages, title_name=title_name, status_prop=status_prop)

        seen = set(schema_order) | set(buckets.keys())
        order = _merge_column_order(schema_order, seen, _parse_column_order(self.config.get("column_order")))

        max_per = max(1, int(self.config.get("max_tasks_per_column", 12)))

        columns: list[dict[str, Any]] = []
        for name in order:
            tasks = buckets.get(name, [])
            columns.append({"name": name, "tasks": tasks[:max_per]})

        return PluginData(payload={"columns": columns, "status_color_map": color_map})

    def render(self, data: PluginData, image: Image.Image, zone: Zone) -> None:
        """Draw the board headline and one column per status value."""
        draw = ImageDraw.Draw(image)
        fill = 0
        headline = str(self.config.get("headline", "Notion"))
        headline_font = load_font(
            self.config,
            self.config.get("headline_font", "Merriweather"),
            int(self.config.get("headline_font_size", 18)),
        )
        task_font = load_font(
            self.config, self.config.get("task_font", "Merriweather"), int(self.config.get("task_font_size", 13))
        )
        hs = int(self.config.get("headline_font_size", 18))
        ts = int(self.config.get("task_font_size", 13))
        mid = int(round((hs + ts) / 2))
        col_header_font = load_font(
            self.config,
            self.config.get("column_header_font", self.config.get("task_font", "Merriweather")),
            int(self.config.get("column_header_font_size", mid)),
        )
        pad_x = max(4, zone.width_percent_int(2))
        pad_y = max(4, zone.height_percent_int(3))
        gutter = max(4, zone.width_percent_int(1))

        show_headline = bool(self.config.get("show_headline", True))
        show_column_headlines = bool(self.config.get("show_column_headlines", True))

        y = pad_y
        if show_headline:
            draw.text((zone.width // 2, y), headline, font=headline_font, fill=fill, anchor="mm")
            hb = draw.textbbox((0, 0), headline, font=headline_font)
            y += (hb[3] - hb[1]) + max(4, zone.height_percent_int(2))

        if data.error:
            msg = _shorten_to_width(draw, data.error, font=task_font, max_width=zone.width - 2 * pad_x)
            draw.text((pad_x, y), msg, font=task_font, fill=fill)
            return

        columns: list[dict[str, Any]] = list((data.payload or {}).get("columns") or [])
        if not columns:
            draw.text((pad_x, y), "No columns", font=task_font, fill=fill)
            return

        base_h, inner_v_pad, line_gap, bar_edge_inset = _task_text_layout(draw, task_font, zone)
        default_task_px = max(8, zone.width // 140)
        default_col_top = max(8, zone.height_percent_int(2))
        task_padding_x = max(0, int(self.config.get("task_padding_x", default_task_px)))
        task_padding_y = max(0, int(self.config.get("task_padding_y", inner_v_pad)))
        column_top_pad = max(0, int(self.config.get("column_top_padding", default_col_top)))
        inner_v_pad_effective = task_padding_y if task_padding_y > 0 else inner_v_pad

        _draw_board_columns(
            draw,
            zone,
            columns,
            status_color_map=(data.payload or {}).get("status_color_map") or {},
            y=y,
            pad_x=pad_x,
            pad_y=pad_y,
            gutter=gutter,
            col_header_font=col_header_font,
            task_font=task_font,
            fill=fill,
            show_column_headlines=show_column_headlines,
            column_top_pad=column_top_pad,
            task_padding_x=task_padding_x,
            inner_v_pad=inner_v_pad_effective,
            base_h=base_h,
            line_gap=line_gap,
            bar_edge_inset=bar_edge_inset,
        )


def _task_text_layout(draw: ImageDraw.ImageDraw, task_font: Any, zone: Zone) -> tuple[int, int, int, int]:
    """Return ink line height, inner vertical padding, gap between wrapped lines, and bar inset."""
    ref_bb = draw.textbbox((0, 0), _TASK_LINE_REF_TEXT, font=task_font)
    base_h = max(1, ref_bb[3] - ref_bb[1])
    v_pad = max(8, zone.height // 64)
    line_gap = max(2, zone.height // 240)
    bar_inset = max(4, zone.width // 160)
    return base_h, v_pad, line_gap, bar_inset


def _task_block_height(n_lines: int, base_h: int, v_pad: int, line_gap: int) -> int:
    """Total pixel height for a wrapped title block."""
    if n_lines <= 0:
        return 0
    return 2 * v_pad + n_lines * base_h + max(0, n_lines - 1) * line_gap


def _draw_board_columns(
    draw: ImageDraw.ImageDraw,
    zone: Zone,
    columns: list[dict[str, Any]],
    *,
    status_color_map: dict[str, str] | None,
    y: int,
    pad_x: int,
    pad_y: int,
    gutter: int,
    col_header_font: Any,
    task_font: Any,
    fill: int,
    show_column_headlines: bool,
    column_top_pad: int,
    task_padding_x: int,
    inner_v_pad: int,
    base_h: int,
    line_gap: int,
    bar_edge_inset: int,
) -> None:
    n = len(columns)
    inner_w = zone.width - 2 * pad_x
    col_w = max(1, (inner_w - gutter * max(0, n - 1)) // n)
    row_gap = max(2, zone.height_percent_int(1))
    smap = status_color_map or {}
    text_inset = task_padding_x

    for i, col in enumerate(columns):
        if not isinstance(col, dict):
            continue
        name = str(col.get("name", "") or "")
        column_color = smap.get(name)
        column_color = Color("gray" if (column_color is None) or (column_color == "default") else column_color)
        bg_color = column_color.lighten(0.9).rgb_u8()
        task_color = column_color.lighten(0.8).rgb_u8()
        text_color = column_color.darken(0.8).rgb_u8()
        tasks = col.get("tasks") or []
        if not isinstance(tasks, list):
            tasks = []

        x0 = pad_x + i * (col_w + gutter)
        draw.rounded_rectangle((x0, y, x0 + col_w, y + zone.height - pad_y * 2), radius=10, fill=bg_color)
        cy = y + column_top_pad
        if show_column_headlines:
            header = _shorten_to_width(draw, name, font=col_header_font, max_width=col_w)
            hb2 = draw.textbbox((0, 0), header, font=col_header_font)
            hw = hb2[2] - hb2[0]
            hx = x0 + max(0, (col_w - hw) // 2)
            draw.text((hx, cy), header, font=col_header_font, fill=fill)
            cy += (hb2[3] - hb2[1]) + row_gap

        bar_left = x0 + bar_edge_inset
        bar_right = x0 + col_w - bar_edge_inset
        bar_w = max(1, bar_right - bar_left)
        max_text_w = max(1, bar_w - 2 * text_inset)

        for t in tasks:
            lines = _wrap_title_lines(draw, str(t), font=task_font, max_width=max_text_w)
            if not lines:
                continue
            block_h = _task_block_height(len(lines), base_h, inner_v_pad, line_gap)
            row_top = cy
            row_bot = cy + block_h
            rr = max(2, min(6, max(base_h, block_h) // 4))
            draw.rounded_rectangle((bar_left, row_top, bar_right, row_bot), radius=rr, fill=task_color)
            tx = bar_left + text_inset
            for li, line in enumerate(lines):
                inner_y = row_top + inner_v_pad + li * (base_h + line_gap)
                mid_y = inner_y + base_h // 2
                draw.text((tx, mid_y), line, font=task_font, fill=text_color, anchor="lm")
            cy = row_bot + row_gap
            if cy >= zone.height - pad_y:
                break
