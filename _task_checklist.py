"""tasks · TipTap checklist parser and HTML utilities (split from panels_task.py)."""
from __future__ import annotations

import re
from html.parser import HTMLParser


class _ChecklistParser(HTMLParser):
    """Extract taskItem entries from Vikunja's TipTap HTML description."""

    def __init__(self):
        super().__init__()
        self._in_item = False
        self._in_div = False
        self._current_checked = False
        self._current_text: list[str] = []
        self.items: list[dict] = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "li" and attrs_d.get("data-type") == "taskItem":
            self._in_item = True
            self._current_checked = attrs_d.get("data-checked") == "true"
            self._current_text = []
        elif tag == "div" and self._in_item:
            self._in_div = True

    def handle_endtag(self, tag):
        if tag == "li" and self._in_item:
            text = "".join(self._current_text).strip()
            if text:
                self.items.append({"checked": self._current_checked, "text": text})
            self._in_item = False
            self._in_div = False
        elif tag == "div":
            self._in_div = False

    def handle_data(self, data):
        if self._in_div:
            self._current_text.append(data)


def _parse_checklist(html: str) -> list[dict]:
    """Return list of {checked, text} from TipTap taskList HTML."""
    if not html or "taskList" not in html:
        return []
    parser = _ChecklistParser()
    parser.feed(html)
    return parser.items


def _toggle_checklist_item(html: str, index: int, checked: bool) -> str:
    """Return description HTML with item at `index` toggled to `checked`."""
    pattern = r'(<li data-type="taskItem" data-checked=")(?:true|false)(")'
    items_found = list(re.finditer(pattern, html))
    if index >= len(items_found):
        return html
    m = items_found[index]
    new_val = "true" if checked else "false"
    return html[:m.start()] + m.group(1) + new_val + m.group(2) + html[m.end():]


def _strip_tasklist(html: str) -> str:
    """Remove TipTap taskList blocks from HTML — rendered separately as DUI checklist."""
    return re.sub(r'<ul[^>]*data-type=["\']taskList["\'][^>]*>.*?</ul>', "", html,
                  flags=re.DOTALL).strip()
