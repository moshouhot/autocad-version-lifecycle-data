#!/usr/bin/env python3
"""Build an independent community evidence layer for Autodesk not-found items."""
from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

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

@dataclass(frozen=True)
class VersionClaim:
    raw: str
    kind: str
    sort_key: int | None

@dataclass(frozen=True)
class Comparison:
    claim: str
    result: str
    detail: str

@dataclass(frozen=True)
class Conflict:
    field: str
    lifecycle_claim: str
    source_claim: str
    verification: str

@dataclass(frozen=True)
class RelatedItem:
    name: str
    type: str
    relation: str
    source_url: str
    evidence_text: str

_RELEASE_ORDER = {"R12": 1200, "R13": 1300, "R14": 1400, "2000": 2000, "2000I": 2001, "2002": 2002}


def parse_first_version(text: str | None) -> VersionClaim | None:
    raw = normalize_space(text)
    if not raw:
        return None
    upper = raw.casefold().endswith("or earlier") or raw.startswith(("≤", "<="))
    token = re.sub(r"\s+or earlier$", "", raw, flags=re.I).lstrip("≤<=> ").upper()
    if token in _RELEASE_ORDER:
        key = _RELEASE_ORDER[token]
    elif re.fullmatch(r"20\d{2}", token):
        key = int(token)
    else:
        return VersionClaim(raw, "unknown", None)
    return VersionClaim(raw, "upper_bound" if upper else "exact", key)


def compare_source_to_lifecycle(record: dict, evidence: SourceEvidence, metadata: dict) -> tuple[list[Comparison], list[Conflict]]:
    comparisons: list[Comparison] = []
    conflicts: list[Conflict] = []
    claim = parse_first_version(evidence.first_version_text)
    spans = record.get("availability") or []
    if claim and spans:
        first = parse_first_version(spans[0]["from"])
        if claim.sort_key is None or first is None or first.sort_key is None:
            comparisons.append(Comparison("first_known_version", "unknown", f"Cannot compare {claim.raw!r}."))
        elif claim.sort_key <= first.sort_key:
            comparisons.append(Comparison("first_known_version", "consistent", f"Source places the item at or before dataset boundary {spans[0]['from']}."))
        else:
            detail = f"Source first version {claim.raw} is later than lifecycle start {spans[0]['from']}."
            comparisons.append(Comparison("first_known_version", "conflict", detail))
            conflicts.append(Conflict("first_known_version", spans[0]["from"], claim.raw, "Check another version history source."))
    obsolete = normalize_space(evidence.obsolete_text)
    if obsolete:
        if re.search(r"no longer supported|removed|not supported since", obsolete, re.I):
            if record.get("available_in_latest"):
                comparisons.append(Comparison("availability", "conflict", obsolete))
                conflicts.append(Conflict("availability", "available in latest lifecycle version", obsolete, "Verify in an AutoCAD runtime or another independent source."))
            else:
                comparisons.append(Comparison("availability", "consistent", obsolete))
        else:
            comparisons.append(Comparison("obsolete_status", "unknown", "Obsolete does not necessarily mean unavailable."))
    return comparisons, conflicts


def classify_evidence(sources: list[SourceEvidence], comparisons: list[Comparison], conflicts: list[Conflict]) -> str:
    if conflicts or any(c.result == "conflict" for c in comparisons):
        return "conflict"
    direct = {s.source for s in sources if s.match_status == "matched"}
    if len(direct) >= 2 and any(c.result == "consistent" for c in comparisons):
        return "confirmed"
    if len(direct) >= 1 and any(c.result == "consistent" for c in comparisons):
        return "corroborated"
    if direct:
        return "single_source"
    return "not_found"


def build_name_catalog(records: list[dict]) -> dict[str, tuple[dict, ...]]:
    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(normalized(record["name"]), []).append(record)
    return {name: tuple(items) for name, items in grouped.items()}


def _sentences(text: str) -> list[str]:
    return [normalize_space(x) for x in re.split(r"(?<=[.!?])\s+|[\r\n]+", text) if normalize_space(x)]


def extract_related_items(description: str, target: dict, catalog: dict[str, tuple[dict, ...]], source_url: str) -> list[RelatedItem]:
    output: list[RelatedItem] = []
    target_name = normalized(target["name"])
    for sentence in _sentences(description):
        for name, candidates in catalog.items():
            if name == target_name or len(candidates) != 1:
                continue
            if not re.search(rf"(?<![A-Z0-9_]){re.escape(name)}(?![A-Z0-9_])", sentence, re.I):
                continue
            before = sentence[:re.search(rf"(?<![A-Z0-9_]){re.escape(name)}(?![A-Z0-9_])", sentence, re.I).start()]
            if re.search(r"exported by|used (?:for|by)|controls?.*(?:command|files?)", before, re.I):
                relation = "controlled_command" if candidates[0]["type"] == "command" else "related_system_variable"
            elif re.search(r"\bsee\b|same as", before, re.I):
                relation = "related_command" if candidates[0]["type"] == "command" else "related_system_variable"
            else:
                continue
            output.append(RelatedItem(name, candidates[0]["type"], relation, source_url, sentence))
    return output

ALLOWED_COMMUNITY_HOSTS = {"www.cadforum.cz", "cadforum.cz", "www.hyperpics.com", "hyperpics.com"}
USER_AGENT = "autocad-version-lifecycle-data/1.1 (+https://github.com/moshouhot/autocad-version-lifecycle-data)"
HYPERPICS_URL = "http://www.hyperpics.com/system_variables/"

class RobotsDenied(PermissionError): pass

@dataclass(frozen=True)
class HttpResult:
    text: str
    status: int
    url: str
    from_cache: bool

class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, headers=None):
        self._body=body; self.status=status; self.headers=headers or {}; self.url=""
    def read(self): return self._body
    def getcode(self): return self.status
    def __enter__(self): return self
    def __exit__(self,*_): return False

class CachedHttpClient:
    def __init__(self, cache_dir: Path, user_agent: str = USER_AGENT, timeout: float = 20,
                 retries: int = 3, opener: Callable = urllib.request.urlopen,
                 sleep: Callable = time.sleep, robots: bool = True):
        self.cache_dir=Path(cache_dir); self.cache_dir.mkdir(parents=True,exist_ok=True)
        self.user_agent=user_agent; self.timeout=timeout; self.retries=retries
        self.opener=opener; self.sleep=sleep; self.robots=robots
        self.stats=Counter(); self._lock=threading.Lock(); self._robots={}
    def _paths(self,url):
        key=hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir/f"{key}.body", self.cache_dir/f"{key}.json"
    def _allowed(self,url):
        if not self.robots: return True
        parts=urllib.parse.urlparse(url); origin=f"{parts.scheme}://{parts.hostname}"
        with self._lock: rp=self._robots.get(origin)
        if rp is None:
            rp=urllib.robotparser.RobotFileParser(f"{origin}/robots.txt")
            try: rp.read()
            except Exception: rp=urllib.robotparser.RobotFileParser(); rp.parse([])
            with self._lock: self._robots[origin]=rp
        return rp.can_fetch(self.user_agent,url)
    def get_text(self,url,refresh=False):
        host=(urllib.parse.urlparse(url).hostname or "").lower()
        if host not in ALLOWED_COMMUNITY_HOSTS: raise ValueError(f"disallowed community host: {host}")
        body_path,meta_path=self._paths(url)
        if not refresh and body_path.exists() and meta_path.exists():
            with self._lock: self.stats["cache_hits"]+=1
            meta=json.loads(meta_path.read_text(encoding="utf-8"))
            return HttpResult(body_path.read_text(encoding="utf-8"),meta["status"],url,True)
        if not self._allowed(url):
            with self._lock: self.stats["robots_denied"]+=1
            raise RobotsDenied(url)
        last=None
        for attempt in range(self.retries):
            try:
                req=urllib.request.Request(url,headers={"User-Agent":self.user_agent,"Accept":"text/html"})
                with self.opener(req,timeout=self.timeout) as response:
                    raw=response.read(); status=getattr(response,"status",None) or response.getcode()
                    ctype=(getattr(response,"headers",{}) or {}).get("Content-Type","")
                    match=re.search(r"charset=([\w-]+)",ctype,re.I); charset=match.group(1) if match else "utf-8"
                    try: text=raw.decode(charset)
                    except (LookupError,UnicodeDecodeError): text=raw.decode("windows-1252","replace")
                body_tmp=body_path.with_suffix(".tmp"); body_tmp.write_text(text,encoding="utf-8"); body_tmp.replace(body_path)
                meta={"url":url,"status":status,"fetched_at":datetime.now(timezone.utc).isoformat(),"body":body_path.name}
                meta_tmp=meta_path.with_suffix(".tmp"); meta_tmp.write_text(json.dumps(meta,separators=(",",":")),encoding="utf-8"); meta_tmp.replace(meta_path)
                with self._lock: self.stats["network_requests"]+=1
                return HttpResult(text,status,url,False)
            except urllib.error.HTTPError as exc:
                last=exc
                if exc.code not in {429,500,502,503,504}: raise
            except urllib.error.URLError as exc: last=exc
            with self._lock: self.stats["retries"]+=1
            if attempt+1<self.retries: self.sleep(2**attempt)
        raise last or RuntimeError("request failed")


def load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def select_targets(lifecycle_records: list[dict], official_records: list[dict]) -> list[dict]:
    not_found={d["lifecycle_id"] for d in official_records if (d.get("match") or {}).get("status")=="not_found"}
    return [record for record in lifecycle_records if record["id"] in not_found]


def source_to_dict(source: SourceEvidence) -> dict:
    return {"source":source.source,"url":source.url,"match_status":source.match_status,
            "matched_name":source.matched_name,"description":source.description,
            "first_version_text":source.first_version_text,"obsolete_text":source.obsolete_text,
            "product_notes":source.product_notes}

def comparison_to_dict(item: Comparison) -> dict: return asdict(item)
def conflict_to_dict(item: Conflict) -> dict: return asdict(item)
def related_to_dict(item: RelatedItem) -> dict: return asdict(item)


def crawl_target(record: dict, client: CachedHttpClient, hyperpics_index: dict[str,SourceEvidence],
                 metadata: dict, catalog: dict[str,tuple[dict,...]], refresh: bool=False) -> dict:
    requested=record["name"]; lookup=requested[1:] if record["type"]=="command" and requested.startswith("'") else requested
    url=cadforum_url(lookup,record["type"]); sources=[]; errors=[]
    try:
        result=client.get_text(url,refresh=refresh)
        cad=parse_cadforum_html(result.text,url,lookup,record["type"])
        sources.append(cad)
    except RobotsDenied as exc:
        sources.append(SourceEvidence("cadforum",url,"robots_denied")); errors.append({"source":"cadforum","kind":"robots_denied","detail":str(exc)})
    except Exception as exc:
        sources.append(SourceEvidence("cadforum",url,"error")); errors.append({"source":"cadforum","kind":"error","detail":f"{type(exc).__name__}: {exc}"})
    if record["type"]=="system_variable":
        hp=hyperpics_index.get(normalized(requested))
        sources.append(hp if hp else SourceEvidence("hyperpics",HYPERPICS_URL,"not_found"))
    comparisons=[]; conflicts=[]
    for source in sources:
        if source.match_status=="matched":
            c,cf=compare_source_to_lifecycle(record,source,metadata); comparisons.extend(c); conflicts.extend(cf)
    related=[]
    for source in sources:
        if source.match_status=="matched" and source.description:
            related.extend(extract_related_items(source.description,record,catalog,source.url))
    status=classify_evidence(sources,comparisons,conflicts)
    return {"lifecycle_id":record["id"],"type":record["type"],"name":record["name"],
            "evidence_status":status,"sources":[source_to_dict(x) for x in sources],
            "comparisons":[comparison_to_dict(x) for x in comparisons],
            "related_items":[related_to_dict(x) for x in related],
            "conflicts":[conflict_to_dict(x) for x in conflicts],"crawl_errors":errors}


def build_report(records: list[dict], stats: dict, targets: list[dict]) -> dict:
    types=Counter(r["type"] for r in records); statuses=Counter(r["evidence_status"] for r in records)
    source_counts={}
    for source in ("cadforum","hyperpics"):
        source_counts[source]=dict(Counter(s["match_status"] for r in records for s in r.get("sources",[]) if s["source"]==source))
    errors=[{"lifecycle_id":r["lifecycle_id"],**e} for r in records for e in r.get("crawl_errors",[])]
    return {"generated_at":datetime.now(timezone.utc).isoformat(),
            "counts":{"total":len(records),"commands":types["command"],"system_variables":types["system_variable"]},
            "target_count":len(targets),"evidence_statuses":dict(statuses),"sources":source_counts,
            "related_item_records":sum(bool(r.get("related_items")) for r in records),
            "conflict_ids":sorted(r["lifecycle_id"] for r in records if r.get("conflicts")),
            "errors":errors,"http":dict(stats)}


def atomic_write_jsonl(path: str | Path, records: list[dict]):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile("w",encoding="utf-8",delete=False,dir=path.parent,newline="\n") as tmp:
        for record in records: tmp.write(json.dumps(record,ensure_ascii=False,separators=(",",":"))+"\n")
        name=tmp.name
    Path(name).replace(path)

def atomic_write_json(path: str | Path, value: dict):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile("w",encoding="utf-8",delete=False,dir=path.parent,newline="\n") as tmp:
        json.dump(value,tmp,ensure_ascii=False,indent=2); tmp.write("\n"); name=tmp.name
    Path(name).replace(path)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lifecycle",default="data/autocad_2004_2027.jsonl"); ap.add_argument("--official",default="data/autodesk_documentation.jsonl")
    ap.add_argument("--metadata",default="metadata.json"); ap.add_argument("--output",default="data/community_documentation.jsonl")
    ap.add_argument("--report",default="reports/community_cross_validation_report.json"); ap.add_argument("--cache-dir",default=".cache/community-docs")
    ap.add_argument("--ids"); ap.add_argument("--limit",type=int); ap.add_argument("--workers",type=int,default=2); ap.add_argument("--refresh",action="store_true")
    args=ap.parse_args(argv)
    if not 1<=args.workers<=4: ap.error("--workers must be between 1 and 4")
    lifecycle=load_jsonl(args.lifecycle); official=load_jsonl(args.official); metadata=json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    targets=select_targets(lifecycle,official)
    if args.ids:
        wanted={x.strip() for x in args.ids.split(",") if x.strip()}; targets=[r for r in targets if r["id"] in wanted]
    if args.limit is not None: targets=targets[:args.limit]
    client=CachedHttpClient(Path(args.cache_dir))
    hyperpics_index={}
    if any(r["type"]=="system_variable" for r in targets):
        hp=client.get_text(HYPERPICS_URL,refresh=args.refresh); hyperpics_index=parse_hyperpics_index(hp.text,HYPERPICS_URL)
    catalog=build_name_catalog(lifecycle); order={r["id"]:i for i,r in enumerate(lifecycle)}; records=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(crawl_target,r,client,hyperpics_index,metadata,catalog,args.refresh):r for r in targets}
        for future in as_completed(futures): records.append(future.result())
    records.sort(key=lambda r:order[r["lifecycle_id"]]); report=build_report(records,client.stats,targets)
    atomic_write_jsonl(args.output,records); atomic_write_json(args.report,report)
    print(f"WROTE records={len(records)} commands={sum(r['type']=='command' for r in records)} system_variables={sum(r['type']=='system_variable' for r in records)} errors={len(report['errors'])}")
    return 1 if report["errors"] else 0

if __name__ == "__main__": raise SystemExit(main())
