"""RSS plugin – renders headlines from one or more RSS feeds."""

from __future__ import annotations

import random
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

from PIL import Image, ImageDraw

from maginkmirror.core.fonts import load_font
from maginkmirror.plugins import BasePlugin, PluginData, Zone

PLUGIN_CLASS = "RssPlugin"

_DEFAULT_HEADERS = {
    "User-Agent": "MagInkMirror/1.0 (+https://github.com/antonioferegrino/MagInkMirror)",
    "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _urlopen_with_headers(url: str, *, timeout: int = 10):
    req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
    return urllib.request.urlopen(req, timeout=timeout)


def _host_from_url(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc
    except Exception:
        return url


def _local_name(tag: str) -> str:
    """
    Convert an XML tag with optional namespace to its local name.

    Example: `{http://purl.org/rss/1.0/}item` → `item`
    """

    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_child_text(elem: ET.Element, wanted_local_name: str) -> str | None:
    for child in list(elem):
        if _local_name(child.tag) == wanted_local_name:
            if child.text is None:
                return None
            return child.text.strip()
    return None


@dataclass(frozen=True)
class RssItem:
    title: str
    link: str | None
    published: datetime | None
    source: str


def _parse_rss_items(xml_bytes: bytes, *, source: str) -> list[RssItem]:
    """
    Best-effort RSS item extraction.

    We intentionally avoid strict schema assumptions and rely on local tag
    names so namespaces don't break parsing.
    """

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    items: list[RssItem] = []
    for item_elem in root.iter():
        if _local_name(item_elem.tag) != "item":
            continue

        title = _find_child_text(item_elem, "title") or ""
        link = _find_child_text(item_elem, "link")

        pub_raw = _find_child_text(item_elem, "pubDate")
        # Some feeds use other fields; keep it simple and only support pubDate.
        published = None
        if pub_raw:
            try:
                published = parsedate_to_datetime(pub_raw)
            except Exception:
                published = None

        if title:
            items.append(RssItem(title=title, link=link, published=published, source=source))

    return items


def _shorten_to_width(draw: ImageDraw.ImageDraw, text: str, *, font, max_width: int) -> str:
    """
    Truncate text with an ellipsis so it fits `max_width`.

    This is conservative and may be slower, but RSS titles are short enough
    for typical refresh intervals.
    """

    text = text.strip()
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


class RssPlugin(BasePlugin):
    """
    RSS plugin.

    Config under `[plugins.rss]` (all optional):
    - `feed_url`: string or array of strings (required for useful output)
    - `max_items`: int (default 5)
    - `shuffle`: bool (default true) - randomize items across feeds
    - `interval`: override BasePlugin.interval by setting plugin's `interval`
    - `headline_font` / `headline_font_size`
    - `meta_font` / `meta_font_size`
    - `show_source`: bool (default true)
    - `show_dates`: bool (default true)
    """

    name = "rss"
    interval = 60

    def fetch(self) -> PluginData:
        feed_url = self.config.get("feed_url")
        if not feed_url:
            raise ValueError("plugins.rss.feed_url is required (string or array).")

        if isinstance(feed_url, str):
            feed_urls = [feed_url]
        else:
            feed_urls = list(feed_url)

        max_items = int(self.config.get("max_items", 5))
        max_items = max(1, max_items)

        timeout = int(self.config.get("timeout", 10))
        shuffle = bool(self.config.get("shuffle", True))

        all_items: list[RssItem] = []
        for url in feed_urls:
            source = _host_from_url(url)
            with _urlopen_with_headers(url, timeout=timeout) as resp:
                xml_bytes = resp.read()
            items = _parse_rss_items(xml_bytes, source=source)
            all_items.extend(items)

        if not all_items:
            raise RuntimeError("No RSS items found (parse produced 0 items).")

        if shuffle:
            random.shuffle(all_items)

        selected = all_items[:max_items]

        payload = {
            "items": [
                {
                    "title": it.title,
                    "published": it.published.isoformat() if it.published else None,
                    "source": it.source,
                    "link": it.link,
                }
                for it in selected
            ]
        }
        return PluginData(payload=payload)

    def render(self, data: PluginData, image: Image.Image, zone: Zone) -> None:
        draw = ImageDraw.Draw(image)
        fill = 0

        headline_font = load_font(
            self.config,
            self.config.get("headline_font", "Merriweather"),
            int(self.config.get("headline_font_size", 22)),
        )
        meta_font = load_font(
            self.config,
            self.config.get("meta_font", "Merriweather"),
            int(self.config.get("meta_font_size", 14)),
        )

        if data.error:
            draw.text((10, 10), "RSS unavailable", font=meta_font, fill=fill)
            return

        p = data.payload or {}
        items: list[dict] = list(p.get("items") or [])
        max_items_to_draw = int(self.config.get("max_items_to_draw", len(items) or 1))
        max_items_to_draw = max(1, max_items_to_draw)
        items = items[:max_items_to_draw]

        show_source = bool(self.config.get("show_source", True))
        show_dates = bool(self.config.get("show_dates", True))

        padding_x = zone.width_percent_int(4)
        padding_top = zone.height_percent_int(5)
        max_text_width = max(1, zone.width - (2 * padding_x))

        gap = max(2, zone.height_percent_int(2))
        y = padding_top

        # Render title + one line of meta (source/date), per item.
        # We also compute each line height from `textbbox` to be font-accurate.
        for it in items:
            title = str(it.get("title", "") or "").strip()
            published_iso = it.get("published")
            source = str(it.get("source", "") or "").strip()

            # Title (truncate to width)
            title = _shorten_to_width(draw, title, font=headline_font, max_width=max_text_width)
            title_bbox = draw.textbbox((0, 0), title, font=headline_font)
            title_h = title_bbox[3] - title_bbox[1]

            # Center horizontally
            title_w = title_bbox[2] - title_bbox[0]
            x = int(round((zone.width - title_w) / 2))
            draw.text((x, y), title, font=headline_font, fill=fill)

            y += title_h + gap

            # Meta line
            meta_parts: list[str] = []
            if show_source and source:
                meta_parts.append(source)
            if show_dates and published_iso:
                try:
                    # Render date in a compact format.
                    dt = datetime.fromisoformat(published_iso)
                    meta_parts.append(dt.strftime("%Y-%m-%d"))
                except Exception:
                    pass

            if meta_parts:
                meta = " ".join(meta_parts)
                meta = _shorten_to_width(draw, meta, font=meta_font, max_width=max_text_width)
                meta_bbox = draw.textbbox((0, 0), meta, font=meta_font)
                meta_w = meta_bbox[2] - meta_bbox[0]
                meta_h = meta_bbox[3] - meta_bbox[1]
                x = int(round((zone.width - meta_w) / 2))
                draw.text((x, y), meta, font=meta_font, fill=fill)
                y += meta_h + gap

            # Stop if we run out of vertical space.
            if y >= zone.height:
                break

