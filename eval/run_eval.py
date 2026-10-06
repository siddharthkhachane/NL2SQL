import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nl2sql import db  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions.json"
RESULTS_DIR = ROOT / "eval" / "results"
TAGS = ["stint", "franchise", "schema_linking", "join", "filter", "aggregation", "date", "syntax", "other"]


def load_questions(split=None):
    qs = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    return [q for q in qs if split in (None, "all", q["split"])]


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
    return not out.get("sql") or "only SELECT" in err or "empty query" in err


def tables_in(sql):
    return {t.lower() for t in re.findall(r"\b(?:from|join)\s+\"?(\w+)", sql or "", re.IGNORECASE)}


def tag_failure(q, out):
    """Heuristic failure tag from the question's trap and simple SQL features."""
    pred, gold = (out.get("sql") or "").lower(), q["gold_sql"].lower()
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
           "join_bucket": bucket(q["join_count"]), "pred_sql": out.get("sql"), "error": out.get("error"),
           "timings": out.get("timings", {}), "exec_match": False, "exact_match": False, "failure": None}
    if q["gold_sql"] is None:
        rec["refused"] = is_refusal(out)
        rec["exec_match"] = rec["refused"]
        if not rec["refused"]:
            rec["failure"] = "other"
        return rec
    _, gold_rows = db.execute_safe(q["gold_sql"], limit=100000)
    rec["exact_match"] = norm_sql(out.get("sql")) == norm_sql(q["gold_sql"])
    if not out.get("error"):
        rec["exec_match"] = results_match(out["rows"], gold_rows, q["gold_sql"])
    if not rec["exec_match"]:
        rec["failure"] = tag_failure(q, out)
    return rec


def _acc(recs):
    n = len(recs)
    return {"n": n, "exec_acc": round(sum(r["exec_match"] for r in recs) / n, 3) if n else None,
            "exact_match": round(sum(r["exact_match"] for r in recs) / n, 3) if n else None}


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
    return {"overall": _acc(records), "by_join_bucket": group("join_bucket"), "by_trap": group("trap"),
            "by_split": group("split"), "failure_tags": dict(fails)}


def run(ask_fn, split=None, label=None, save=True):
    records = []
    for q in load_questions(split):
        t = time.perf_counter()
        out = ask_fn(q["question"])
        rec = score(q, out)
        rec["latency"] = round(time.perf_counter() - t, 3)
        records.append(rec)
    result = {"label": label, "timestamp": datetime.now().isoformat(timespec="seconds"),
              "summary": summarize(records), "records": records}
    if save:
        RESULTS_DIR.mkdir(exist_ok=True)
        path = RESULTS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}.json"
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        result["path"] = str(path)
    return result


def print_report(result):
    s = result["summary"]
    print(f"overall: {s['overall']}")
    for key in ("by_join_bucket", "by_trap", "by_split"):
        print(key)
        for k, v in s[key].items():
            print(f"  {k:22} n={v['n']:<3} exec={v['exec_acc']}  exact={v['exact_match']}")
    print("failure tags:", s["failure_tags"])
    if result.get("path"):
        print("saved:", result["path"])


def show_gold():
    for q in load_questions():
        if q["gold_sql"]:
            cols, rows = db.execute_safe(q["gold_sql"], limit=100000)
            print(f"{q['id']} rows={len(rows)} cols={cols} sample={rows[:3]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all", choices=["all", "dev", "heldout"])
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--gold", action="store_true", help="print row count and sample for each gold query")
    args = ap.parse_args()
    if args.gold:
        show_gold()
    else:
        from nl2sql.pipeline import ask
        print_report(run(ask, args.split, args.label))
