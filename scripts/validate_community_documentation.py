#!/usr/bin/env python3
"""Validate the committed community evidence layer against both source datasets."""
import argparse,json,re,sys,urllib.parse
from collections import Counter
from pathlib import Path

ALLOWED_HOSTS={"www.cadforum.cz","cadforum.cz","www.hyperpics.com","hyperpics.com"}
TOP_FIELDS={"lifecycle_id","type","name","evidence_status","sources","comparisons","related_items","conflicts","crawl_errors"}
STATUSES={"confirmed","corroborated","single_source","conflict","not_found"}
ABS_RE=re.compile(r"[A-Za-z]:\\")

def load(path): return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]

def validate_record_shape(record,line):
    errors=[]; prefix=f"line {line}"
    if set(record)!=TOP_FIELDS: errors.append(f"{prefix} top-level fields mismatch")
    status=record.get("evidence_status"); sources=record.get("sources") or []; comparisons=record.get("comparisons") or []; conflicts=record.get("conflicts") or []
    if status not in STATUSES: errors.append(f"{prefix} invalid evidence status")
    matched={s.get("source") for s in sources if s.get("match_status")=="matched"}
    consistent=any(c.get("result")=="consistent" for c in comparisons)
    if status=="confirmed" and (len(matched)<2 or not consistent): errors.append(f"{prefix} confirmed requires two direct sources and a consistent comparison")
    if status=="corroborated" and (not matched or not consistent): errors.append(f"{prefix} corroborated requires a direct source and consistent comparison")
    if status=="single_source" and not matched: errors.append(f"{prefix} single_source without matched source")
    if status=="conflict" and not conflicts: errors.append(f"{prefix} conflict status without conflict details")
    if status=="not_found" and matched: errors.append(f"{prefix} not_found has matched source")
    if conflicts and status!="conflict": errors.append(f"{prefix} conflicts not reflected in status")
    for source in sources:
        if source.get("source") not in {"cadforum","hyperpics"}: errors.append(f"{prefix} invalid source")
        host=(urllib.parse.urlparse(source.get("url","")).hostname or "").lower()
        if host not in ALLOWED_HOSTS: errors.append(f"{prefix} disallowed source host")
        if source.get("match_status") not in {"matched","not_found","robots_denied","error"}: errors.append(f"{prefix} invalid match status")
        if source.get("match_status")=="matched" and not source.get("matched_name"): errors.append(f"{prefix} matched source without name")
    raw=json.dumps(record,ensure_ascii=False)
    if ABS_RE.search(raw) or "<html" in raw.lower() or "<script" in raw.lower(): errors.append(f"{prefix} leaked path/html")
    return errors

def validate_records(lifecycle,official,records,report):
    errors=[]; life={r["id"]:r for r in lifecycle}; targets={d["lifecycle_id"] for d in official if (d.get("match") or {}).get("status")=="not_found"}
    if len(records)!=len(targets): errors.append(f"record count {len(records)} != target count {len(targets)}")
    seen=set()
    for line,record in enumerate(records,1):
        errors.extend(validate_record_shape(record,line)); ident=record.get("lifecycle_id")
        if ident in seen: errors.append(f"line {line} duplicate {ident}")
        seen.add(ident); source=life.get(ident)
        if ident not in targets: errors.append(f"line {line} non-target id {ident}")
        if source and (record.get("name")!=source["name"] or record.get("type")!=source["type"]): errors.append(f"line {line} identity mismatch")
        expected_sources=["cadforum"] if record.get("type")=="command" else ["cadforum","hyperpics"]
        if [s.get("source") for s in record.get("sources",[])]!=expected_sources: errors.append(f"line {line} source attempts mismatch")
    if seen!=targets: errors.append(f"target ID set mismatch missing={len(targets-seen)} extra={len(seen-targets)}")
    types=Counter(r.get("type") for r in records); statuses=Counter(r.get("evidence_status") for r in records)
    expected_counts={"total":len(records),"commands":types["command"],"system_variables":types["system_variable"]}
    if report.get("counts")!=expected_counts: errors.append("report counts mismatch")
    if report.get("target_count")!=len(targets): errors.append("report target count mismatch")
    if report.get("evidence_statuses")!=dict(statuses): errors.append("report evidence statuses mismatch")
    conflict_ids=sorted(r["lifecycle_id"] for r in records if r.get("conflicts"))
    if report.get("conflict_ids")!=conflict_ids: errors.append("report conflict IDs mismatch")
    if report.get("errors"): errors.append(f"report contains {len(report['errors'])} crawl errors")
    return errors

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--lifecycle",default="data/autocad_2004_2027.jsonl"); ap.add_argument("--official",default="data/autodesk_documentation.jsonl"); ap.add_argument("--data",default="data/community_documentation.jsonl"); ap.add_argument("--report",default="reports/community_cross_validation_report.json"); args=ap.parse_args(argv)
    for path in (args.lifecycle,args.official,args.data,args.report):
        if not Path(path).exists(): print(f"FAIL missing {path}",file=sys.stderr); return 1
    lifecycle=load(args.lifecycle); official=load(args.official); records=load(args.data); report=json.loads(Path(args.report).read_text(encoding="utf-8")); errors=validate_records(lifecycle,official,records,report)
    if errors: print("FAIL\n"+"\n".join(errors[:60]),file=sys.stderr); return 1
    counts=Counter(r["type"] for r in records); statuses=Counter(r["evidence_status"] for r in records)
    print(f"PASS community records={len(records)} commands={counts['command']} system_variables={counts['system_variable']} confirmed={statuses['confirmed']} corroborated={statuses['corroborated']} single_source={statuses['single_source']} conflict={statuses['conflict']} not_found={statuses['not_found']}")
    return 0
if __name__=="__main__": raise SystemExit(main())
