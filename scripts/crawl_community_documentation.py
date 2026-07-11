#!/usr/bin/env python3
"""Build an independent community evidence layer for Autodesk not-found items."""
from __future__ import annotations

import html as html_lib
import re
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser

SPACE_RE = re.compile(r"\s+")


def normalize_space(value: str | None) -> str:
    return SPACE_RE.sub(" ", html_lib.unescape(value or "")).strip()


def normalized(value: str | None) -> str:
    return normalize_space(value).upper()


@dataclass
class SourceEvidence:
    source: str
    url: str
    match_status: str
    matched_name: str | None = None
    description: str | None = None
    first_version_text: str | None = None
    obsolete_text: str | None = None
    product_notes: dict = field(default_factory=dict)


def cadforum_url(name: str, item_type: str) -> str:
    page = "command.asp" if item_type == "command" else "variable.asp"
    query = urllib.parse.urlencode({"cmd": name}, quote_via=urllib.parse.quote)
    return f"https://www.cadforum.cz/en/{page}?{query}"


class TextCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "nav"}:
            self._skip += 1
        elif not self._skip and tag.lower() in {"br", "p", "div", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "nav"} and self._skip:
            self._skip -= 1
        elif not self._skip and tag.lower() in {"p", "div", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = [normalize_space(x) for x in "".join(self.parts).splitlines()]
        return "\n".join(x for x in lines if x)


def parse_cadforum_html(html: str, url: str, expected_name: str, expected_type: str) -> SourceEvidence:
    parser = TextCollector(); parser.feed(html); text = parser.text()
    lower = text.casefold()
    if "was not found" in lower:
        return SourceEvidence("cadforum", url, "not_found")
    kind = "command" if expected_type == "command" else "variable"
    pattern = re.compile(rf"\bThe\s+({re.escape(expected_name)})\s+{kind}\b", re.I)
    hit = pattern.search(text)
    if not hit:
        return SourceEvidence("cadforum", url, "not_found")
    version_match = re.search(r"In AutoCAD since version\s+([^\n]+)", text, re.I)
    description_patterns = [
        rf"{re.escape(expected_name)} command description:\s*\n?([^\n]+)",
        rf"Description of the variable {re.escape(expected_name)}:\s*\n?([^\n]+)",
    ]
    description = None
    for candidate in description_patterns:
        match = re.search(candidate, text, re.I)
        if match:
            description = normalize_space(match.group(1)); break
    obsolete = None
    match = re.search(r"([^\n]*(?:no longer supported|obsolete since)[^\n]*)", text, re.I)
    if match:
        obsolete = normalize_space(match.group(1))
    notes = {}
    if f"{kind} not available in AutoCAD LT".casefold() in lower:
        notes["lt_available"] = False
    if kind == "command" and "command not available in core console" in lower:
        notes["core_console_available"] = False
    return SourceEvidence(
        "cadforum", url, "matched", normalized(hit.group(1)), description,
        normalize_space(version_match.group(1)) if version_match else None,
        obsolete, notes,
    )


class HyperPicsTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, dict[str, str]]]] = []
        self.row = None; self.cell = None; self.attrs = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower(); attrs = {k.lower(): (v or "") for k, v in attrs}
        if tag == "tr": self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []; self.attrs = attrs

    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append((normalize_space("".join(self.cell)), self.attrs or {}))
            self.cell = None; self.attrs = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row); self.row = None


def parse_hyperpics_index(html: str, url: str) -> dict[str, SourceEvidence]:
    parser = HyperPicsTableParser(); parser.feed(html)
    versions: list[str] = []; output: dict[str, SourceEvidence] = {}
    available_colors = {"#33cc33", "#ffcc00", "#996633", "#cc6600"}
    for row in parser.rows:
        if not row: continue
        first = normalized(row[0][0]).lstrip("*_")
        if "VARIABLE NAME" in first:
            versions = []
            for text, _ in row[1:]:
                m = re.search(r"'(\d{2})", text)
                versions.append(f"20{m.group(1)}" if m else normalize_space(text))
            continue
        raw_name = normalized(row[0][0])
        if not versions or not raw_name: continue
        cells = row[1:1+len(versions)]
        available = [v for v, (_, attrs) in zip(versions, cells) if attrs.get("bgcolor", "").casefold() in available_colors]
        output[raw_name] = SourceEvidence(
            "hyperpics", url, "matched", raw_name,
            first_version_text=(f"{available[0]} or earlier" if available and available[0] == versions[0] else (available[0] if available else None)),
            product_notes={"available_versions": available},
        )
    return output
