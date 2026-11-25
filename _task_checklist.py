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


def _add_checklist_item(html: str, text: str, checked: bool = False) -> str:
    """Add a checklist item to TipTap HTML. Creates taskList block if missing."""
    import html as html_lib
    escaped_text = html_lib.escape(text.strip())
    chk_str = "true" if checked else "false"
    item_html = f'<li data-type="taskItem" data-checked="{chk_str}"><div>{escaped_text}</div></li>'

    if not html or not html.strip():
        return f'<ul data-type="taskList">{item_html}</ul>'

    # Check if a taskList ul already exists
    ul_match = re.search(r'(<ul[^>]*data-type=["\']taskList["\'][^>]*>)(.*?)(</ul>)', html, flags=re.DOTALL)
    if ul_match:
        # Append before closing </ul>
        prefix = html[:ul_match.start(3)]
        suffix = html[ul_match.start(3):]
        return prefix + item_html + suffix
    else:
        # Append whole ul block to end of description
        sep = "<p></p>" if not html.endswith("</p>") else ""
        return html + sep + f'<ul data-type="taskList">{item_html}</ul>'


def _delete_checklist_item(html: str, index: int) -> tuple[str, bool]:
    """Delete checklist item at `index`. Returns (updated_html, success)."""
    # Match complete <li data-type="taskItem" ...>...</li> blocks
    li_pattern = r'<li data-type="taskItem"[^>]*>.*?</li>'
    items = list(re.finditer(li_pattern, html, flags=re.DOTALL))
    if index < 0 or index >= len(items):
        return html, False

    target = items[index]
    updated = html[:target.start()] + html[target.end():]

    # Clean up empty taskList ul blocks: <ul data-type="taskList">\s*</ul>
    updated = re.sub(r'<ul[^>]*data-type=["\']taskList["\'][^>]*>\s*</ul>', '', updated, flags=re.DOTALL).strip()
    return updated, True


def _strip_tasklist(html: str) -> str:
    """Remove TipTap taskList blocks from HTML — rendered separately as DUI checklist."""
    return re.sub(r'<ul[^>]*data-type=["\']taskList["\'][^>]*>.*?</ul>', "", html,
                  flags=re.DOTALL).strip()
