#!/usr/bin/env python3
"""Build concise third-party purpose descriptions for Autodesk not-found items."""
from __future__ import annotations

import argparse,hashlib,html as html_lib,json,re,tempfile,threading,time
import urllib.error,urllib.parse,urllib.request,urllib.robotparser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import asdict,dataclass
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

SPACE_RE=re.compile(r"\s+")
ALLOWED_HOSTS={"www.cadforum.cz","cadforum.cz"}
USER_AGENT="autocad-version-lifecycle-data/1.2 (+https://github.com/moshouhot/autocad-version-lifecycle-data)"
SOURCE_NOTES={"hyperpics":"Public page checked with a browser User-Agent on 2026-07-11; it exposes a version-color table, while purpose descriptions are marked members-only, so no HyperPics descriptions are copied."}

def normalize_space(value): return SPACE_RE.sub(" ",html_lib.unescape(value or "")).strip()
def normalized(value): return normalize_space(value).upper()

@dataclass(frozen=True)
class SourceEvidence:
    source:str; url:str; match_status:str; matched_name:str|None=None; description:str|None=None

@dataclass(frozen=True)
class RelatedItem:
    name:str; type:str; relation:str; source_url:str; evidence_text:str


def cadforum_url(name,item_type):
    page="command.asp" if item_type=="command" else "variable.asp"
    query=urllib.parse.urlencode({"cmd":name},quote_via=urllib.parse.quote)
    return f"https://www.cadforum.cz/en/{page}?{query}"

class TextCollector(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.parts=[]; self._skip=0
    def handle_starttag(self,tag,attrs):
        tag=tag.lower()
        if tag in {"script","style","nav"}: self._skip+=1
        elif not self._skip and tag in {"br","p","div","h1","h2","h3","h4"}: self.parts.append("\n")
    def handle_endtag(self,tag):
        tag=tag.lower()
        if tag in {"script","style","nav"} and self._skip:self._skip-=1
        elif not self._skip and tag in {"p","div","h1","h2","h3","h4"}:self.parts.append("\n")
    def handle_data(self,data):
        if not self._skip:self.parts.append(data)
    def text(self):
        lines=[normalize_space(x) for x in "".join(self.parts).splitlines()]
        return "\n".join(x for x in lines if x)

def parse_cadforum_html(html,url,expected_name,expected_type):
    parser=TextCollector();parser.feed(html);text=parser.text()
    if "was not found" in text.casefold(): return SourceEvidence("cadforum",url,"not_found")
    kind="command" if expected_type=="command" else "variable"
    hit=re.search(rf"\bThe\s+({re.escape(expected_name)})\s+{kind}\b",text,re.I)
    if not hit:return SourceEvidence("cadforum",url,"not_found")
    patterns=[rf"{re.escape(expected_name)} command description:\s*\n?([^\n]+)",rf"Description of the variable {re.escape(expected_name)}:\s*\n?([^\n]+)"]
    description=None
    for pattern in patterns:
        match=re.search(pattern,text,re.I)
        if match:description=normalize_space(match.group(1));break
    return SourceEvidence("cadforum",url,"matched" if description else "not_found",normalized(hit.group(1)),description)


def build_name_catalog(records):
    grouped={}
    for record in records:grouped.setdefault(normalized(record["name"]),[]).append(record)
    return {name:tuple(items) for name,items in grouped.items()}

def _sentences(text):return [normalize_space(x) for x in re.split(r"(?<=[.!?])\s+|[\r\n]+",text) if normalize_space(x)]
def extract_related_items(description,target,catalog,source_url):
    output=[];target_name=normalized(target["name"])
    for sentence in _sentences(description):
        tokens=dict.fromkeys(normalized(m.group(0)) for m in re.finditer(r"(?<![A-Z0-9_])[+*'-]?[A-Z0-9_]{2,}(?![A-Z0-9_])",sentence,re.I))
        for name in tokens:
            candidates=catalog.get(name,())
            if name==target_name or len(candidates)!=1:continue
            boundary=rf"(?<![A-Z0-9_]){re.escape(name)}(?![A-Z0-9_])";item_type=candidates[0]["type"]
            if re.search(rf"(?:now\s+)?see\s+{boundary}|same\s+as\s+{boundary}",sentence,re.I):relation="related_command" if item_type=="command" else "related_system_variable"
            elif re.search(rf"(?:exported|used)\s+by\s+{boundary}|controls?\s+(?:the\s+)?{boundary}\s+command",sentence,re.I):relation="controlled_command" if item_type=="command" else "related_system_variable"
            else:continue
            output.append(RelatedItem(name,item_type,relation,source_url,sentence))
    return output


def build_description_record(record,sources,catalog):
    descriptions=[];seen=set();related=[]
    for source in sources:
        text=normalize_space(source.description)
        if source.match_status!="matched" or not text:continue
        item={"source":source.source,"url":source.url,"matched_name":source.matched_name or record["name"],"text":text}
        key=(item["source"],item["url"],item["text"].casefold())
        if key in seen:continue
        seen.add(key);descriptions.append(item)
        related.extend(asdict(x) for x in extract_related_items(text,record,catalog,source.url))
    if any(source.match_status=="ambiguous" for source in sources):status="ambiguous"
    elif descriptions:status="matched"
    else:status="not_found"
    return {"lifecycle_id":record["id"],"type":record["type"],"name":record["name"],"description_status":status,"descriptions":descriptions,"related_items":related}

class RobotsDenied(PermissionError):pass
@dataclass(frozen=True)
class HttpResult:text:str;status:int;url:str;from_cache:bool
class FakeResponse:
    def __init__(self,body,status=200,headers=None):self._body=body;self.status=status;self.headers=headers or {};self.url=""
    def read(self):return self._body
    def getcode(self):return self.status
    def __enter__(self):return self
    def __exit__(self,*_):return False
class CachedHttpClient:
    def __init__(self,cache_dir,user_agent=USER_AGENT,timeout=20,retries=3,opener:Callable=urllib.request.urlopen,sleep:Callable=time.sleep,robots=True):
        self.cache_dir=Path(cache_dir);self.cache_dir.mkdir(parents=True,exist_ok=True);self.user_agent=user_agent;self.timeout=timeout;self.retries=retries;self.opener=opener;self.sleep=sleep;self.robots=robots;self.stats=Counter();self._lock=threading.Lock();self._robots={}
    def _paths(self,url):
        key=hashlib.sha256(url.encode()).hexdigest();return self.cache_dir/f"{key}.body",self.cache_dir/f"{key}.json"
    def _allowed(self,url):
        if not self.robots:return True
        parts=urllib.parse.urlparse(url);origin=f"{parts.scheme}://{parts.hostname}"
        with self._lock:rp=self._robots.get(origin)
        if rp is None:
            rp=urllib.robotparser.RobotFileParser(f"{origin}/robots.txt")
            try:rp.read()
            except Exception:rp=urllib.robotparser.RobotFileParser();rp.parse([])
            with self._lock:self._robots[origin]=rp
        return rp.can_fetch(self.user_agent,url)
    def get_text(self,url,refresh=False):
        host=(urllib.parse.urlparse(url).hostname or "").lower()
        if host not in ALLOWED_HOSTS:raise ValueError(f"disallowed host: {host}")
        body_path,meta_path=self._paths(url)
        if not refresh and body_path.exists() and meta_path.exists():
            with self._lock:self.stats["cache_hits"]+=1
            meta=json.loads(meta_path.read_text(encoding="utf-8"));return HttpResult(body_path.read_text(encoding="utf-8"),meta["status"],url,True)
        if not self._allowed(url):raise RobotsDenied(url)
        last=None
        for attempt in range(self.retries):
            try:
                req=urllib.request.Request(url,headers={"User-Agent":self.user_agent,"Accept":"text/html"})
                with self.opener(req,timeout=self.timeout) as response:
                    raw=response.read();status=getattr(response,"status",None) or response.getcode();ctype=(getattr(response,"headers",{}) or {}).get("Content-Type","");match=re.search(r"charset=([\w-]+)",ctype,re.I);charset=match.group(1) if match else "utf-8"
                    try:text=raw.decode(charset)
                    except (LookupError,UnicodeDecodeError):text=raw.decode("windows-1252","replace")
                bt=body_path.with_suffix(".tmp");bt.write_text(text,encoding="utf-8");bt.replace(body_path);meta={"url":url,"status":status,"fetched_at":datetime.now(timezone.utc).isoformat(),"body":body_path.name};mt=meta_path.with_suffix(".tmp");mt.write_text(json.dumps(meta,separators=(",",":")),encoding="utf-8");mt.replace(meta_path)
                with self._lock:self.stats["network_requests"]+=1
                return HttpResult(text,status,url,False)
            except urllib.error.HTTPError as exc:
                last=exc
                if exc.code not in {429,500,502,503,504}:raise
            except urllib.error.URLError as exc:last=exc
            with self._lock:self.stats["retries"]+=1
            if attempt+1<self.retries:self.sleep(2**attempt)
        raise last or RuntimeError("request failed")

def load_jsonl(path):return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
def select_targets(lifecycle,official):
    ids={d["lifecycle_id"] for d in official if (d.get("match") or {}).get("status")=="not_found"};return [r for r in lifecycle if r["id"] in ids]
def crawl_target(record,client,catalog,refresh=False):
    lookup=record["name"][1:] if record["type"]=="command" and record["name"].startswith("'") else record["name"];url=cadforum_url(lookup,record["type"]);errors=[]
    try:source=parse_cadforum_html(client.get_text(url,refresh).text,url,lookup,record["type"])
    except Exception as exc:source=SourceEvidence("cadforum",url,"not_found");errors.append({"lifecycle_id":record["id"],"source":"cadforum","kind":type(exc).__name__,"detail":str(exc)})
    return build_description_record(record,[source],catalog),errors

def build_report(records,stats,targets,errors,source_notes):
    types=Counter(r["type"] for r in records);statuses=Counter(r["description_status"] for r in records);sources=Counter(d["source"] for r in records for d in r["descriptions"])
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"counts":{"total":len(records),"commands":types["command"],"system_variables":types["system_variable"]},"target_count":len(targets),"description_statuses":dict(statuses),"sources":dict(sources),"related_item_records":sum(bool(r["related_items"]) for r in records),"source_notes":source_notes,"errors":errors,"http":dict(stats)}
def atomic_write_jsonl(path,records):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile("w",encoding="utf-8",delete=False,dir=path.parent,newline="\n") as tmp:
        for r in records:tmp.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n")
        name=tmp.name
    Path(name).replace(path)
def atomic_write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile("w",encoding="utf-8",delete=False,dir=path.parent,newline="\n") as tmp:json.dump(value,tmp,ensure_ascii=False,indent=2);tmp.write("\n");name=tmp.name
    Path(name).replace(path)
def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--lifecycle",default="data/autocad_2004_2027.jsonl");ap.add_argument("--official",default="data/autodesk_documentation.jsonl");ap.add_argument("--output",default="data/community_documentation.jsonl");ap.add_argument("--report",default="reports/community_cross_validation_report.json");ap.add_argument("--cache-dir",default=".cache/community-docs");ap.add_argument("--ids");ap.add_argument("--limit",type=int);ap.add_argument("--workers",type=int,default=2);ap.add_argument("--refresh",action="store_true");args=ap.parse_args(argv)
    if not 1<=args.workers<=4:ap.error("--workers must be between 1 and 4")
    lifecycle=load_jsonl(args.lifecycle);official=load_jsonl(args.official);targets=select_targets(lifecycle,official)
    if args.ids:wanted={x.strip() for x in args.ids.split(",")};targets=[r for r in targets if r["id"] in wanted]
    if args.limit is not None:targets=targets[:args.limit]
    client=CachedHttpClient(Path(args.cache_dir));catalog=build_name_catalog(lifecycle);order={r["id"]:i for i,r in enumerate(lifecycle)};records=[];errors=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(crawl_target,r,client,catalog,args.refresh) for r in targets]
        for future in as_completed(futures):record,errs=future.result();records.append(record);errors.extend(errs)
    records.sort(key=lambda r:order[r["lifecycle_id"]]);report=build_report(records,client.stats,targets,errors,SOURCE_NOTES);atomic_write_jsonl(args.output,records);atomic_write_json(args.report,report)
    print(f"WROTE records={len(records)} matched={sum(r['description_status']=='matched' for r in records)} not_found={sum(r['description_status']=='not_found' for r in records)} ambiguous={sum(r['description_status']=='ambiguous' for r in records)} errors={len(errors)}")
    return 1 if errors else 0
if __name__=="__main__":raise SystemExit(main())
