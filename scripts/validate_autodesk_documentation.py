#!/usr/bin/env python3
import argparse,json,re,sys,urllib.parse
from collections import Counter
from pathlib import Path

ABS_RE=re.compile(r"[A-Za-z]:\\")
ALLOWED={"docs.autodesk.com","help.autodesk.com"}

def load(path):return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
def base(v):return v.split(".",1)[0]
def available(record,version,meta):
 axis=meta["version_axes"][record["type"]];idx={v:i for i,v in enumerate(axis)};positions=[idx[v] for v in axis if base(v)==base(version)]
 return any(idx[s["from"]]<=p<=idx[s["to"]] for s in record["availability"] for p in positions)
def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument("--lifecycle",default="data/autocad_2004_2027.jsonl");ap.add_argument("--documentation",default="data/autodesk_documentation.jsonl");ap.add_argument("--metadata",default="metadata.json");ap.add_argument("--report",default="reports/autodesk_documentation_report.json");a=ap.parse_args(argv)
 for p in (a.lifecycle,a.documentation,a.metadata,a.report):
  if not Path(p).exists():print(f"FAIL missing {p}",file=sys.stderr);return 1
 life=load(a.lifecycle);docs=load(a.documentation);meta=json.loads(Path(a.metadata).read_text(encoding="utf-8"));report=json.loads(Path(a.report).read_text(encoding="utf-8"));errors=[]
 if len(life)!=2608 or len(docs)!=2608:errors.append(f"counts lifecycle={len(life)} documentation={len(docs)}")
 lm={r["id"]:r for r in life};seen=set()
 for i,d in enumerate(docs,1):
  ident=d.get("lifecycle_id");r=lm.get(ident)
  if ident in seen:errors.append(f"line {i} duplicate {ident}")
  seen.add(ident)
  if not r:errors.append(f"line {i} unknown id {ident}");continue
  if d.get("type")!=r["type"] or d.get("name")!=r["name"]:errors.append(f"line {i} identity mismatch")
  m=d.get("match") or {};status=m.get("status");doc=d.get("documentation")
  if status=="matched":
   if not isinstance(doc,dict):errors.append(f"line {i} matched without documentation");continue
   required_doc={"official_name","title","url","guid","description","summary"}
   if set(doc)!=required_doc:errors.append(f"line {i} documentation fields mismatch")
   host=urllib.parse.urlparse(doc.get("url","")).hostname
   if host not in ALLOWED:errors.append(f"line {i} non-official URL")
   version=m.get("document_version")
   if not re.fullmatch(r"20\d{2}",str(version)):errors.append(f"line {i} invalid document version")
   elif d.get("available_in_document_version") is not available(r,version,meta):errors.append(f"line {i} availability mismatch")
  elif status=="not_found":
   if doc is not None or m.get("document_version") is not None or d.get("available_in_document_version") is not None:errors.append(f"line {i} invalid not_found")
  elif status=="ambiguous":
   if doc is not None or len(m.get("candidates") or [])<2:errors.append(f"line {i} invalid ambiguous")
  else:errors.append(f"line {i} invalid status")
  raw=json.dumps(d,ensure_ascii=False)
  if ABS_RE.search(raw) or "<html" in raw.lower() or "<script" in raw.lower():errors.append(f"line {i} leaked path/html")
 if set(lm)!=seen:errors.append(f"missing lifecycle IDs: {len(set(lm)-seen)}")
 counts=Counter(d.get("type") for d in docs);statuses=Counter((d.get("match") or {}).get("status") for d in docs)
 if counts!={"command":1444,"system_variable":1164}:errors.append(f"type counts {dict(counts)}")
 if sum(statuses.values())!=2608:errors.append("status count mismatch")
 if report.get("counts")!={"total":2608,"commands":1444,"system_variables":1164}:errors.append("report counts mismatch")
 if report.get("match_status")!=dict(statuses):errors.append("report match status mismatch")
 if report.get("errors"):errors.append(f"report contains {len(report['errors'])} crawl errors")
 if errors:
  print("FAIL\n"+"\n".join(errors[:40]),file=sys.stderr);return 1
 print(f"PASS documentation records=2608 commands=1444 system_variables=1164 matched={statuses['matched']} not_found={statuses['not_found']} ambiguous={statuses['ambiguous']}");return 0
if __name__=="__main__":raise SystemExit(main())
