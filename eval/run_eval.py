import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nl2sql import databases, db, generate  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions.json"
RESULTS_DIR = ROOT / "eval" / "results"
TAGS = ["stint", "franchise", "schema_linking", "join", "filter", "aggregation", "date", "syntax", "other"]


def qdb(q):
    return q.get("database", databases.DEFAULT)


def load_questions(split=None, database=None):
    qs = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    return [q for q in qs if split in (None, "all", q["split"]) and database in (None, "all", qdb(q))]


def bucket(join_count):
    if join_count is None:
        return "n/a"
    return "3+" if join_count >= 3 else str(join_count)


def norm_value(v):
    return round(v, 4) if isinstance(v, float) else v


def has_order_by(sql):
    return bool(re.search(r"\border\s+by\b", sql, re.IGNORECASE))


def results_match(pred_rows, gold_rows, gold_sql):
    pred = [tuple(norm_value(v) for v in r) for r in pred_rows]
    gold = [tuple(norm_value(v) for v in r) for r in gold_rows]
    if not has_order_by(gold_sql):
        pred, gold = sorted(pred, key=repr), sorted(gold, key=repr)
    return pred == gold


def norm_sql(sql):
    return re.sub(r"\s+", " ", (sql or "").strip().rstrip(";").strip()).lower()


def is_refusal(out):
    err = out.get("error") or ""
    return out.get("refused", False) or not out.get("sql") or "only SELECT" in err or "empty query" in err


tables_in = db.tables_in


def tag_failure(q, out):
    """Heuristic failure tag from the question's trap and simple SQL features."""
    pred, gold = (out.get("sql") or "").lower(), q["gold_sql"].lower()
    if out.get("refused"):
        return "other"  # wrongly refused an answerable question
    if (out.get("error") or "").startswith("generation failed"):
        return "other"  # API/infra failure, not a SQL error
    if out.get("error"):
        return "syntax"
    if q["trap"] == "stint" and "sum(" not in pred:
        return "stint"
    if q["trap"] == "franchise" and "franchid" not in pred:
        return "franchise"
    if q["trap"] == "time" and "max(yearid)" not in pred and "2025" not in pred and "2016" not in pred:
        return "date"
    if not tables_in(gold) <= tables_in(pred):
        return "schema_linking"
    if len(tables_in(pred)) != len(tables_in(gold)) or ("join" in gold) != ("join" in pred):
        return "join"
    if any(k in gold for k in ("sum(", "count(", "avg(", "max(", "group by")) and not any(
            k in pred for k in ("sum(", "count(", "avg(", "max(", "group by")):
        return "aggregation"
    if "where" in gold and "where" in pred:
        return "filter"
    return "other"


def score(q, out):
    """Returns a result record for one question."""
    rec = {"id": q["id"], "question": q["question"], "trap": q["trap"], "split": q["split"],
           "database": qdb(q), "join_bucket": bucket(q["join_count"]),
           "pred_sql": out.get("sql"), "error": out.get("error"),
           "timings": out.get("timings", {}), "assumptions": out.get("assumptions"),
           "retried": out.get("retried", False), "exec_match": False, "exact_match": False, "failure": None}
    if out.get("route_scores"):
        rec["routed_to"] = out["database"]
        rec["route_correct"] = out["database"] == qdb(q)
    if q["gold_sql"] is not None and out.get("tables") is not None:
        gold = tables_in(q["gold_sql"])
        rec["retrieval_recall_topk"] = gold <= {t.lower() for t in out["retrieved"]}
        rec["retrieval_recall"] = gold <= {t.lower() for t in out["tables"]}
        rec["tables"] = out["tables"]
    if q["gold_sql"] is None:
        rec["refused"] = is_refusal(out)
        rec["exec_match"] = rec["refused"]
        if not rec["refused"]:
            rec["failure"] = "other"
        return rec
    _, gold_rows = db.execute_safe(q["gold_sql"], limit=100000, path=databases.path(qdb(q)))
    rec["exact_match"] = norm_sql(out.get("sql")) == norm_sql(q["gold_sql"])
    if rec.get("route_correct") is False:
        rec["failure"] = "other"  # routed to the wrong database; the SQL cannot be right
        rec["first_attempt_match"] = False
        return rec
    if not out.get("error") and not out.get("refused"):
        rec["exec_match"] = results_match(out["rows"], gold_rows, q["gold_sql"])
    first = out.get("first") or {"error": out.get("error"), "rows": out.get("rows"), "refused": out.get("refused")}
    rec["first_attempt_match"] = bool(not first.get("error") and not first.get("refused")
                                      and results_match(first["rows"], gold_rows, q["gold_sql"]))
    if not rec["exec_match"]:
        rec["failure"] = tag_failure(q, out)
    return rec


def _acc(recs):
    n = len(recs)
    return {"n": n, "exec_acc": round(sum(r["exec_match"] for r in recs) / n, 3) if n else None,
            "exact_match": round(sum(r["exact_match"] for r in recs) / n, 3) if n else None}


def _recall(recs):
    r = [x for x in recs if "retrieval_recall" in x]
    if not r:
        return None
    return {"n": len(r), "topk": round(sum(x["retrieval_recall_topk"] for x in r) / len(r), 3),
            "with_neighbors": round(sum(x["retrieval_recall"] for x in r) / len(r), 3)}


def summarize(records):
    def group(key):
        g = defaultdict(list)
        for r in records:
            g[r[key]].append(r)
        return {k: _acc(v) for k, v in sorted(g.items())}

    fails = defaultdict(int)
    for r in records:
        if r["failure"]:
            fails[r["failure"]] += 1
    answerable = [r for r in records if r["trap"] != "unanswerable"]
    unans = [r for r in records if r["trap"] == "unanswerable"]
    robustness = {
        "retry_rate": round(sum(r["retried"] for r in answerable) / len(answerable), 3) if answerable else None,
        "first_attempt_acc": round(sum(r["first_attempt_match"] for r in answerable) / len(answerable), 3)
        if answerable else None,
        "final_acc": round(sum(r["exec_match"] for r in answerable) / len(answerable), 3) if answerable else None,
        "unanswerable_refused": f"{sum(r['exec_match'] for r in unans)}/{len(unans)}",
        "false_refusals": sum(1 for r in answerable if r["pred_sql"] is None and r["error"] is None),
    }
    by_bucket = defaultdict(list)
    for r in records:
        by_bucket[r["join_bucket"]].append(r)
    recall = {"overall": _recall(records), **{k: _recall(v) for k, v in sorted(by_bucket.items())}}
    routed = [r for r in records if "route_correct" in r]
    return {"overall": _acc(records), "answerable_only": robustness,
            "retrieval_recall": recall if recall["overall"] else None,
            "route_accuracy": {"n": len(routed), "acc": round(sum(r["route_correct"] for r in routed) / len(routed), 3)}
            if routed else None,
            "by_database": group("database"), "by_join_bucket": group("join_bucket"), "by_trap": group("trap"),
            "by_split": group("split"), "failure_tags": dict(fails)}


def run(ask_fn, split=None, label=None, save=True, database=None):
    """ask_fn receives the question dict (so it can read the gold database when not routing)."""
    records = []
    generate.reset_usage()
    for q in load_questions(split, database):
        t = time.perf_counter()
        out = ask_fn(q)
        rec = score(q, out)
        rec["latency"] = round(time.perf_counter() - t, 3)
        records.append(rec)
    result = {"label": label, "timestamp": datetime.now().isoformat(timespec="seconds"),
              "model": os.getenv("NL2SQL_MODEL", generate.DEFAULT_MODEL), "usage": dict(generate.USAGE),
              "avg_latency": round(sum(r["latency"] for r in records) / len(records), 2) if records else None,
              "summary": summarize(records), "records": records}
    if save:
        RESULTS_DIR.mkdir(exist_ok=True)
        path = RESULTS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}.json"
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        result["path"] = str(path)
    return result


def print_report(result):
    s = result["summary"]
    print(f"model: {result.get('model')}  avg latency: {result.get('avg_latency')}s  usage: {result.get('usage')}")
    print(f"overall: {s['overall']}")
    for key in ("by_database", "by_join_bucket", "by_trap", "by_split"):
        print(key)
        for k, v in s[key].items():
            print(f"  {k:22} n={v['n']:<3} exec={v['exec_acc']}  exact={v['exact_match']}")
    print("answerable only:", s["answerable_only"])
    print("failure tags:", s["failure_tags"])
    if s.get("route_accuracy"):
        print("routing accuracy:", s["route_accuracy"])
    if s["retrieval_recall"]:
        print("retrieval recall (topk / with neighbors):")
        for k, v in s["retrieval_recall"].items():
            if v:
                print(f"  {k:8} n={v['n']:<3} {v['topk']} / {v['with_neighbors']}")
    if result.get("path"):
        print("saved:", result["path"])


def compare(a, b):
    """Print baseline-vs-other execution accuracy per join bucket from two saved results."""
    la, lb = a["label"], b["label"]
    print(f"{'bucket':8} {la:>14} {lb:>14}")
    sa, sb = a["summary"], b["summary"]
    print(f"{'overall':8} {sa['overall']['exec_acc']:>14} {sb['overall']['exec_acc']:>14}")
    for k in sa["by_join_bucket"]:
        print(f"{k:8} {sa['by_join_bucket'][k]['exec_acc']:>14} {sb['by_join_bucket'][k]['exec_acc']:>14}")


def show_gold():
    for q in load_questions():
        if q["gold_sql"]:
            cols, rows = db.execute_safe(q["gold_sql"], limit=100000, path=databases.path(qdb(q)))
            print(f"{q['id']} rows={len(rows)} cols={cols} sample={rows[:3]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all", choices=["all", "dev", "heldout", "heldout_new"])
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--linking", action="store_true", help="use schema linking")
    ap.add_argument("--retry", action="store_true", help="retry once on SQL error or empty result")
    ap.add_argument("--assumptions", action="store_true", help="model states how it resolved ambiguity")
    ap.add_argument("--gate", action="store_true", help="model may refuse unanswerable questions")
    ap.add_argument("--semantic", action="store_true", help="add the data glossary to the prompt")
    ap.add_argument("--db", default="all", choices=["all"] + list(databases.DATABASES), help="only questions for this database")
    ap.add_argument("--route", action="store_true", help="router picks the database instead of the gold label")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"), help="compare two saved result files")
    ap.add_argument("--gold", action="store_true", help="print row count and sample for each gold query")
    args = ap.parse_args()
    if args.compare:
        compare(*[json.loads(Path(p).read_text(encoding="utf-8")) for p in args.compare])
    elif args.gold:
        show_gold()
    else:
        from nl2sql.pipeline import ask
        flags = {"linking": args.linking, "retry": args.retry, "assumptions": args.assumptions, "gate": args.gate,
                 "semantic": args.semantic}
        flags["route"] = args.route
        label = args.label if args.label != "baseline" else "+".join(k for k, v in flags.items() if v) or "baseline"
        if args.db != "all":
            label += f"@{args.db}"
        print_report(run(lambda q: ask(q["question"], database=None if args.route else qdb(q), **flags),
                         args.split, label, database=args.db))
