#!/usr/bin/env python3
"""Validate the community purpose-description layer against PDF lifecycle IDs."""
import argparse,json,re,sys,urllib.parse
from collections import Counter
from pathlib import Path

ALLOWED_HOSTS={"www.cadforum.cz","cadforum.cz","www.hyperpics.com","hyperpics.com","www.manusoft.com","manusoft.com","help.bricsys.com"}
TOP_FIELDS={"lifecycle_id","type","name","description_status","descriptions","related_items"}
ABS_RE=re.compile(r"[A-Za-z]:\\")
def load(path):return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
def validate_record_shape(record,line):
    errors=[];prefix=f"line {line}"
    if set(record)!=TOP_FIELDS:errors.append(f"{prefix} fields mismatch")
    status=record.get("description_status");descriptions=record.get("descriptions") or []
    if status not in {"matched","not_found","ambiguous"}:errors.append(f"{prefix} invalid description status")
    if status=="matched" and not descriptions:errors.append(f"{prefix} matched without description")
    if status=="not_found" and descriptions:errors.append(f"{prefix} not_found has descriptions")
    for desc in descriptions:
        if set(desc)!={"source","url","matched_name","text"}:errors.append(f"{prefix} description fields mismatch")
        if not str(desc.get("text","")).strip():errors.append(f"{prefix} empty description")
        host=(urllib.parse.urlparse(desc.get("url","")).hostname or "").lower()
        if desc.get("source") in {"cadforum","bricsys","hyperpics","manusoft"} and host not in ALLOWED_HOSTS:errors.append(f"{prefix} source host mismatch")
    raw=json.dumps(record,ensure_ascii=False)
    if ABS_RE.search(raw) or "<html" in raw.lower() or "<script" in raw.lower():errors.append(f"{prefix} leaked path/html")
    return errors
def validate_records(lifecycle,official,records,report):
    errors=[];life={r["id"]:r for r in lifecycle};targets={d["lifecycle_id"] for d in official if (d.get("match") or {}).get("status")=="not_found"};seen=set()
    if len(records)!=len(targets):errors.append(f"record count {len(records)} != target count {len(targets)}")
    for line,r in enumerate(records,1):
        errors.extend(validate_record_shape(r,line));ident=r.get("lifecycle_id")
        if ident in seen:errors.append(f"line {line} duplicate {ident}")
        seen.add(ident);source=life.get(ident)
        if ident not in targets:errors.append(f"line {line} non-target id {ident}")
        if source and (r.get("type")!=source["type"] or r.get("name")!=source["name"]):errors.append(f"line {line} identity mismatch")
    if seen!=targets:errors.append(f"target ID set mismatch missing={len(targets-seen)} extra={len(seen-targets)}")
    types=Counter(r.get("type") for r in records);statuses=Counter(r.get("description_status") for r in records);sources=Counter(d["source"] for r in records for d in r.get("descriptions",[]))
    if report.get("counts")!={"total":len(records),"commands":types["command"],"system_variables":types["system_variable"]}:errors.append("report counts mismatch")
    if report.get("target_count")!=len(targets):errors.append("report target count mismatch")
    if report.get("description_statuses")!=dict(statuses):errors.append("report description statuses mismatch")
    if report.get("sources")!=dict(sources):errors.append("report source counts mismatch")
    if report.get("errors"):errors.append(f"report contains {len(report['errors'])} crawl errors")
    for forbidden in ("evidence_statuses","conflict_ids"):
        if forbidden in report:errors.append(f"report contains obsolete field {forbidden}")
    return errors
def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument("--lifecycle",default="data/autocad_2004_2027.jsonl");ap.add_argument("--official",default="data/autodesk_documentation.jsonl");ap.add_argument("--data",default="data/community_documentation.jsonl");ap.add_argument("--report",default="reports/community_cross_validation_report.json");a=ap.parse_args(argv)
    for p in (a.lifecycle,a.official,a.data,a.report):
        if not Path(p).exists():print(f"FAIL missing {p}",file=sys.stderr);return 1
    lifecycle=load(a.lifecycle);official=load(a.official);records=load(a.data);report=json.loads(Path(a.report).read_text(encoding="utf-8"));errors=validate_records(lifecycle,official,records,report)
    if errors:print("FAIL\n"+"\n".join(errors[:60]),file=sys.stderr);return 1
    counts=Counter(r["type"] for r in records);statuses=Counter(r["description_status"] for r in records)
    print(f"PASS community descriptions records={len(records)} commands={counts['command']} system_variables={counts['system_variable']} matched={statuses['matched']} not_found={statuses['not_found']} ambiguous={statuses['ambiguous']}");return 0
if __name__=="__main__":raise SystemExit(main())
