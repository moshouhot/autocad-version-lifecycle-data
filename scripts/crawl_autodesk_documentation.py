#!/usr/bin/env python3
"""Build a compact cross-version Autodesk documentation index."""
from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

OFFICIAL_HOSTS = {"docs.autodesk.com", "help.autodesk.com", "beehive.autodesk.com"}
LEGACY_INDEXES = {
    "2013": "http://docs.autodesk.com/ACD/2013/ENU/contents-data.html",
    "2014": "http://docs.autodesk.com/ACD/2014/ENU/contents-data.html",
}
SEARCH_ENDPOINT = "https://beehive.autodesk.com/community/service/rest/cloudhelp/resource/cloudhelpchannel/search/"
USER_AGENT = "autocad-version-lifecycle-data/1.0 (+https://github.com/moshouhot/autocad-version-lifecycle-data)"
GUID_RE = re.compile(r"GUID-[0-9A-F-]{36}", re.I)
SPACE_RE = re.compile(r"\s+")
ALIAS_RE = re.compile(r"^(.+?)\s+\(([^()]+)\)$")

class ParseError(ValueError): pass
class RobotsDenied(PermissionError): pass

@dataclass(frozen=True)
class Topic:
    official_name: str
    title: str
    url: str
    guid: str
    description: str | None
    summary: list[str]
    document_version: str
    topic_type: str

@dataclass(frozen=True)
class SearchEntry:
    url: str
    title: str
    description: str | None
    guid: str
    source: str

@dataclass(frozen=True)
class MatchResult:
    status: str
    strategy: str | None
    topic: Topic | None = None
    candidates: tuple[Topic, ...] = ()

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


def normalize_space(value: str | None) -> str:
    return SPACE_RE.sub(" ", html_lib.unescape(value or "")).strip()

def optional_space(value: str | None) -> str | None:
    value=normalize_space(value)
    return value or None

def extract_guid(url: str, topic_id: str | None = None) -> str:
    match=GUID_RE.search(topic_id or "") or GUID_RE.search(url)
    return match.group(0).upper() if match else (topic_id or "")

def dedupe_paragraphs(paragraphs: list[str], description: str | None) -> list[str]:
    desc=normalize_space(description)
    result=[]; seen={desc.casefold()} if desc else set()
    for item in paragraphs:
        text=normalize_space(item)
        key=text.casefold()
        if text and key not in seen:
            seen.add(key);result.append(text)
    return result

class AutodeskTopicParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta={};self.title="";self._capture_title=False;self._title=[]
        self._capture_h2=False;self._h2=[];self.in_summary=False
        self._capture_p=False;self._p=[];self.summary=[];self._skip=0
    def handle_starttag(self,tag,attrs):
        tag=tag.lower(); a={k.lower():v for k,v in attrs}
        if tag in {"script","style","nav"}:self._skip+=1;return
        if tag=="meta" and a.get("name") and a.get("content") is not None:self.meta[a["name"].lower()]=a["content"]
        elif tag=="title":self._capture_title=True;self._title=[]
        elif tag=="h2":self._capture_h2=True;self._h2=[]
        elif tag=="p" and self.in_summary:self._capture_p=True;self._p=[]
    def handle_endtag(self,tag):
        tag=tag.lower()
        if tag in {"script","style","nav"} and self._skip:self._skip-=1;return
        if tag=="title" and self._capture_title:self.title=normalize_space("".join(self._title));self._capture_title=False
        elif tag=="h2" and self._capture_h2:
            heading=normalize_space("".join(self._h2));self.in_summary=heading.casefold()=="summary";self._capture_h2=False
        elif tag=="p" and self._capture_p:
            self.summary.append(normalize_space("".join(self._p)));self._capture_p=False
    def handle_data(self,data):
        if self._skip:return
        if self._capture_title:self._title.append(data)
        if self._capture_h2:self._h2.append(data)
        if self._capture_p:self._p.append(data)

def parse_topic_html(html: str, url: str, version: str) -> Topic:
    parser=AutodeskTopicParser();parser.feed(html)
    subtype=(parser.meta.get("topic-subtype") or "").lower()
    if not subtype and normalize_space(parser.title).casefold().endswith("(command)"):
        subtype="command"
    elif not subtype and normalize_space(parser.title).casefold().endswith("(system variable)"):
        subtype="sysvar"
    name=parser.meta.get("cmdname") or parser.meta.get("sysvarname") or parser.meta.get("contextid")
    if subtype not in {"command","sysvar","systemvariable","system-variable"} or not name:
        raise ParseError("not a command or system-variable topic")
    topic_type="command" if subtype=="command" else "system_variable"
    return Topic(normalize_space(name),normalize_space(parser.title),url,extract_guid(url,parser.meta.get("topicid")),optional_space(parser.meta.get("description")),dedupe_paragraphs(parser.summary,parser.meta.get("description")),str(version),topic_type)

def parse_search_response(payload: dict, expected_type: str) -> list[SearchEntry]:
    items=((payload.get("entries") or {}).get("item") or [])
    if isinstance(items,dict):items=[items]
    suffix="(Command)" if expected_type=="command" else "(System Variable)"
    out=[]
    for item in items:
        url=str(item.get("url") or "");title=normalize_space(item.get("title"));source=str(item.get("source") or "")
        host=urllib.parse.urlparse(url).hostname or ""
        if source!="CloudHelp" or host!="help.autodesk.com" or "/cloudhelp/" not in url or not title.casefold().endswith(suffix.casefold()):continue
        out.append(SearchEntry(url,title,optional_space(item.get("shortDescription")),extract_guid(url,item.get("topicId")),source))
    return out

def normalized(value: str) -> str:return normalize_space(value).upper()
def name_candidates(name: str) -> list[tuple[str,str]]:
    raw=normalized(name)
    if raw.startswith("'"):return [(raw[1:],"transparent_prefix")]
    out=[(raw,"exact")]
    m=ALIAS_RE.match(raw)
    if m:
        out.extend([(normalized(m.group(1)),"alias_primary"),(normalized(m.group(2)),"alias_parenthetical")])
    seen=set();return [(n,s) for n,s in out if not (n in seen or seen.add(n))]

def match_topics(record: dict, topics: list[Topic]) -> MatchResult:
    expected=record["type"]; by_guid={}
    for t in topics:
        if t.topic_type==expected:by_guid[t.guid or t.url]=t
    topics=list(by_guid.values())
    for candidate,strategy in name_candidates(record["name"]):
        hits=[t for t in topics if normalized(t.official_name)==candidate]
        if not hits:
            suffix="(COMMAND)" if expected=="command" else "(SYSTEM VARIABLE)"
            hits=[t for t in topics if normalized(t.title)==f"{candidate} {suffix}"]
            resolved="title_exact"
        else:resolved={"exact":"metadata_exact","transparent_prefix":"transparent_prefix","alias_primary":"alias_exact","alias_parenthetical":"alias_exact"}[strategy]
        if len(hits)==1:return MatchResult("matched",resolved,hits[0])
        if len(hits)>1:return MatchResult("ambiguous",resolved,None,tuple(hits))
    return MatchResult("not_found",None)

class CachedHttpClient:
    def __init__(self,cache_dir:Path,user_agent:str=USER_AGENT,timeout:float=20,retries:int=3,opener:Callable=urllib.request.urlopen,sleep:Callable=time.sleep,robots:bool=True):
        self.cache_dir=Path(cache_dir);self.cache_dir.mkdir(parents=True,exist_ok=True);self.user_agent=user_agent;self.timeout=timeout;self.retries=retries;self.opener=opener;self.sleep=sleep;self.robots=robots
        self._lock=threading.Lock();self._robots={};self.stats=Counter()
    def _paths(self,url):
        key=hashlib.sha256(url.encode()).hexdigest();return self.cache_dir/f"{key}.body",self.cache_dir/f"{key}.json"
    def _allowed(self,url):
        if not self.robots:return True
        parts=urllib.parse.urlparse(url);host=parts.hostname
        with self._lock:rp=self._robots.get(host)
        if rp is None:
            rp=urllib.robotparser.RobotFileParser(f"{parts.scheme}://{host}/robots.txt")
            try:rp.read()
            except Exception:rp=urllib.robotparser.RobotFileParser();rp.parse([])
            with self._lock:self._robots[host]=rp
        return rp.can_fetch(self.user_agent,url)
    def get_text(self,url,refresh=False):
        host=urllib.parse.urlparse(url).hostname
        if host not in OFFICIAL_HOSTS:raise ValueError(f"non-official host: {host}")
        body_path,meta_path=self._paths(url)
        if not refresh and body_path.exists() and meta_path.exists():
            with self._lock:self.stats["cache_hits"]+=1
            meta=json.loads(meta_path.read_text(encoding="utf-8"));return HttpResult(body_path.read_text(encoding="utf-8"),meta["status"],url,True)
        if not self._allowed(url):raise RobotsDenied(url)
        last=None
        for attempt in range(self.retries):
            try:
                req=urllib.request.Request(url,headers={"User-Agent":self.user_agent,"Accept":"text/html,application/json"})
                with self.opener(req,timeout=self.timeout) as response:
                    raw=response.read();status=getattr(response,"status",None) or response.getcode();charset="utf-8"
                    ctype=(getattr(response,"headers",{}) or {}).get("Content-Type","")
                    m=re.search(r"charset=([\w-]+)",ctype,re.I)
                    if m:charset=m.group(1)
                    text=raw.decode(charset,"replace")
                tmp=body_path.with_suffix(".tmp");tmp.write_text(text,encoding="utf-8");tmp.replace(body_path)
                meta={"url":url,"status":status,"fetched_at":datetime.now(timezone.utc).isoformat(),"body":body_path.name}
                mt=meta_path.with_suffix(".tmp");mt.write_text(json.dumps(meta,separators=(",",":")),encoding="utf-8");mt.replace(meta_path)
                with self._lock:self.stats["network_requests"]+=1
                return HttpResult(text,status,url,False)
            except urllib.error.HTTPError as exc:
                last=exc
                if exc.code not in {429,500,502,503,504}:raise
            except urllib.error.URLError as exc:last=exc
            with self._lock:self.stats["retries"]+=1
            if attempt+1<self.retries:self.sleep(2**attempt)
        raise last or RuntimeError("request failed")
    def get_json(self,url,refresh=False):
        result=self.get_text(url,refresh);return json.loads(result.text),result

@dataclass(frozen=True)
class TopicRef:
    name:str;topic_type:str;url:str;version:str
class LegacyIndexParser(HTMLParser):
    def __init__(self,base,version):super().__init__(convert_charrefs=True);self.base=base;self.version=version;self.href=None;self.buf=[];self.refs=[]
    def handle_starttag(self,t,a):
        if t.lower()=="a":self.href=dict(a).get("href");self.buf=[]
    def handle_data(self,d):
        if self.href is not None:self.buf.append(d)
    def handle_endtag(self,t):
        if t.lower()=="a" and self.href is not None:
            title=normalize_space("".join(self.buf));m=re.match(r"^(.*?)\s+\((Command|System Variable)\)$",title,re.I)
            if m and "GUID-" in self.href:
                typ="command" if m.group(2).lower()=="command" else "system_variable";self.refs.append(TopicRef(normalized(m.group(1)),typ,urllib.parse.urljoin(self.base,self.href),self.version))
            self.href=None;self.buf=[]
def parse_legacy_index(html,version):
    base=f"http://docs.autodesk.com/ACD/{version}/ENU/";p=LegacyIndexParser(base,version);p.feed(html);out={}
    for ref in p.refs:out.setdefault((ref.topic_type,ref.name),[]).append(ref)
    return out

def base_year(v):return v.split(".",1)[0]
def candidate_versions(record,metadata):
    axis=metadata["version_axes"][record["type"]];idx={v:i for i,v in enumerate(axis)};available=[]
    for span in record["availability"]:available.extend(axis[idx[span["from"]]:idx[span["to"]]+1])
    ordered=[]
    for v in list(reversed(available))+list(reversed(record.get("new_in",[])))+list(reversed(record.get("changed_in",[]))):
        y=base_year(v)
        if y not in ordered:ordered.append(y)
    return ordered

def is_available(record,version,metadata):
    axis=metadata["version_axes"][record["type"]];idx={v:i for i,v in enumerate(axis)}
    candidates=[v for v in axis if base_year(v)==base_year(version)]
    if not candidates:return False
    positions=[idx[v] for v in candidates]
    for span in record["availability"]:
        if any(idx[span["from"]]<=p<=idx[span["to"]] for p in positions):return True
    return False

def search_url(name,item_type,version):
    suffix="Command" if item_type=="command" else "System Variable"
    params={"origin":"upi","p":"ACD","v":str(version),"l":"ENU","maxresults":"100","q":f"{name} ({suffix})","source":"CloudHelp"}
    return SEARCH_ENDPOINT+"?"+urllib.parse.urlencode(params)

def topic_to_dict(t):return {"official_name":t.official_name,"title":t.title,"url":t.url,"guid":t.guid,"description":t.description,"summary":t.summary}
def topic_candidate_dict(t):return {"title":t.title,"url":t.url,"guid":t.guid,"document_version":t.document_version}

def build_result(record,result,metadata):
    match={"status":result.status,"strategy":result.strategy,"document_version":result.topic.document_version if result.topic else None}
    out={"lifecycle_id":record["id"],"type":record["type"],"name":record["name"],"available_in_document_version":is_available(record,result.topic.document_version,metadata) if result.topic else None,"match":match,"documentation":topic_to_dict(result.topic) if result.topic else None}
    if result.status=="ambiguous":out["match"]["candidates"]=[topic_candidate_dict(t) for t in result.candidates]
    return out

class Resolver:
    def __init__(self,client,metadata,legacy,refresh=False,max_attempts=5):self.client=client;self.metadata=metadata;self.legacy=legacy;self.refresh=refresh;self.max_attempts=max_attempts;self.memo={};self.lock=threading.Lock();self.errors=[]
    def _fetch_topic(self,url,version):
        return parse_topic_html(self.client.get_text(url,self.refresh).text,url,version)
    def resolve(self,record):
        key=(record["type"],record["name"])
        with self.lock:
            if key in self.memo:return build_result(record,self.memo[key],self.metadata)
        topics=[];versions=candidate_versions(record,self.metadata);prefer_new=versions and int(versions[0])>=2018
        sources=["search","legacy"] if prefer_new else ["legacy","search"]
        try:
            for source in sources:
                if source=="legacy":
                    for cand,_ in name_candidates(record["name"]):
                        for ref in self.legacy.get((record["type"],cand),[]):
                            try:topics.append(self._fetch_topic(ref.url,ref.version))
                            except Exception as e:self.errors.append({"id":record["id"],"stage":"legacy_topic","url":ref.url,"error":str(e)})
                    if topics:break
                else:
                    for version in versions[:self.max_attempts]:
                        found=[]
                        for cand,_ in name_candidates(record["name"]):
                            try:payload,_=self.client.get_json(search_url(cand,record["type"],version),self.refresh)
                            except Exception as e:self.errors.append({"id":record["id"],"stage":"search","version":version,"error":str(e)});continue
                            expected=f"{cand} ({'Command' if record['type']=='command' else 'System Variable'})"
                            for entry in parse_search_response(payload,record["type"]):
                                if normalized(entry.title)==normalized(expected):found.append(entry)
                        for entry in {e.guid or e.url:e for e in found}.values():
                            try:topics.append(self._fetch_topic(entry.url,version))
                            except Exception as e:self.errors.append({"id":record["id"],"stage":"search_topic","url":entry.url,"error":str(e)})
                        if topics:break
                    if topics:break
            result=match_topics(record,topics)
        except Exception as e:
            self.errors.append({"id":record["id"],"stage":"resolve","error":str(e)});result=MatchResult("not_found",None)
        with self.lock:self.memo[key]=result
        return build_result(record,result,self.metadata)

def load_jsonl(path):return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
def atomic_jsonl(path,rows):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="\n") as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    tmp.replace(path)
def atomic_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp");tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");tmp.replace(path)
def build_report(records,results,resolver,client):
    status=Counter(r["match"]["status"] for r in results);strategy=Counter(r["match"].get("strategy") for r in results if r["match"].get("strategy"));versions=Counter(r["match"].get("document_version") for r in results if r["match"].get("document_version"))
    byid={r["id"]:r for r in records};unmatched=[r["lifecycle_id"] for r in results if r["match"]["status"]=="not_found"]
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"counts":{"total":len(results),"commands":sum(r["type"]=="command" for r in results),"system_variables":sum(r["type"]=="system_variable" for r in results)},"match_status":dict(status),"match_strategy":dict(strategy),"document_versions":dict(versions),"not_found_ids":unmatched,"ambiguous":[{"id":r["lifecycle_id"],"candidates":r["match"].get("candidates",[])} for r in results if r["match"]["status"]=="ambiguous"],"available_2014_not_found":[i for i in unmatched if is_available(byid[i],"2014",resolver.metadata)],"available_2027_not_found":[i for i in unmatched if is_available(byid[i],"2027",resolver.metadata)],"errors":resolver.errors,"http":dict(client.stats)}

def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument("--input",default="data/autocad_2004_2027.jsonl");ap.add_argument("--metadata",default="metadata.json");ap.add_argument("--output",default="data/autodesk_documentation.jsonl");ap.add_argument("--report",default="reports/autodesk_documentation_report.json");ap.add_argument("--cache-dir",default=".cache/autodesk-docs");ap.add_argument("--workers",type=int,default=4);ap.add_argument("--limit",type=int);ap.add_argument("--ids");ap.add_argument("--refresh",action="store_true");ap.add_argument("--max-version-attempts",type=int,default=5);args=ap.parse_args(argv)
    records=load_jsonl(args.input);metadata=json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    if args.ids:
        wanted=set(args.ids.split(","));records=[r for r in records if r["id"] in wanted]
    if args.limit:records=records[:args.limit]
    partial=bool(args.ids or args.limit)
    if partial and args.output=="data/autodesk_documentation.jsonl":ap.error("partial runs require an explicit --output")
    client=CachedHttpClient(Path(args.cache_dir), USER_AGENT)
    legacy={}
    for version,url in LEGACY_INDEXES.items():
        try:
            payload=client.get_text(url,args.refresh).text
            for key,refs in parse_legacy_index(payload,version).items():legacy.setdefault(key,[]).extend(refs)
        except Exception as e:print(f"warning: legacy index {version}: {e}",file=sys.stderr)
    resolver=Resolver(client,metadata,legacy,args.refresh,args.max_version_attempts)
    results=[None]*len(records)
    with ThreadPoolExecutor(max_workers=max(1,min(args.workers,4))) as pool:
        futures={pool.submit(resolver.resolve,r):i for i,r in enumerate(records)}
        for completed, future in enumerate(as_completed(futures), 1):
            results[futures[future]]=future.result()
            if completed % 100 == 0 or completed == len(records):
                print(f"progress {completed}/{len(records)}", file=sys.stderr)
    atomic_jsonl(args.output,results);report=build_report(records,results,resolver,client);atomic_json(args.report,report)
    print(f"DONE records={len(results)} matched={report['match_status'].get('matched',0)} not_found={report['match_status'].get('not_found',0)} ambiguous={report['match_status'].get('ambiguous',0)} errors={len(report['errors'])}")
    return 0
if __name__=="__main__":raise SystemExit(main())
