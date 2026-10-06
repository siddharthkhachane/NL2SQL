import json
from pathlib import Path

import pandas as pd
import streamlit as st

from nl2sql import pipeline

RESULTS_DIR = Path(__file__).resolve().parent / "eval" / "results"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Mono:wght@400;500&display=swap');
h1, h2, h3, h4, h5, h6 { font-family: 'Newsreader', Georgia, serif !important; }
html, body, .stApp, .stMarkdown, p, label, input, button, textarea { font-family: 'Newsreader', Georgia, serif; }
[data-testid="stIconMaterial"], .material-symbols-rounded { font-family: 'Material Symbols Rounded' !important; }
.block-container { padding-top: 2.5rem; max-width: 62rem; }
#MainMenu, footer { visibility: hidden; }
h1 { font-weight: 600; letter-spacing: -0.01em; border-bottom: 2px solid #1E2822; padding-bottom: .4rem; }
.kicker { font-family: 'IBM Plex Mono', monospace; font-size: .72rem; letter-spacing: .14em;
          text-transform: uppercase; color: #A8461F; margin-bottom: -.6rem; }
code, pre, .mono { font-family: 'IBM Plex Mono', monospace !important; font-size: .85rem; }
.stTextInput div:has(> input) {
    background: transparent !important; border: 0 !important; border-bottom: 1.5px solid #1E2822 !important; border-radius: 0 !important; box-shadow: none !important; }
.stTextInput input { font-size: 1.15rem; padding-left: 0; background: transparent; }
.stButton button { border-radius: 0; background: #1E2822; color: #F5F0E6; border: 0; padding: .45rem 1.4rem;
                   font-family: 'IBM Plex Mono', monospace; letter-spacing: .06em; }
.stButton button:hover { background: #A8461F; color: #F5F0E6; }
.note { border-left: 3px solid #A8461F; padding: .1rem 0 .1rem .8rem; font-style: italic; margin: .6rem 0; }
.stats { font-family: 'IBM Plex Mono', monospace; font-size: .8rem; color: #5A6459; margin-top: .6rem; }
.stTabs [data-baseweb="tab"] { font-family: 'IBM Plex Mono', monospace; font-size: .8rem; letter-spacing: .08em; }
</style>
"""


def latest_results():
    files = sorted(RESULTS_DIR.glob("*.json"))
    if not files:
        return None
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    data["file"] = files[-1].name
    return data


def html(text, cls):
    st.markdown(f'<div class="{cls}">{text}</div>', unsafe_allow_html=True)


st.set_page_config(page_title="Lahman NL2SQL", layout="centered")
st.markdown(CSS, unsafe_allow_html=True)
html("Lahman baseball database, 1871 to 2025", "kicker")
st.title("Ask the almanac")

ask_tab, eval_tab = st.tabs(["QUESTION", "EVAL"])

with ask_tab:
    st.sidebar.markdown("**Pipeline**")
    linking = st.sidebar.checkbox("Schema linking", value=False)
    retry = st.sidebar.checkbox("Retry once on error or empty result", value=True)
    assumptions = st.sidebar.checkbox("Return assumptions", value=True)
    gate = st.sidebar.checkbox("Refuse unanswerable questions", value=True)

    question = st.text_input("Question", placeholder="Who hit the most home runs in 1997?",
                             label_visibility="collapsed")
    if st.button("RUN") and question.strip():
        out = pipeline.ask(question.strip(), linking=linking, retry=retry, assumptions=assumptions, gate=gate)

        if out["refused"]:
            html("The database cannot answer this question.", "note")
        elif out["error"]:
            html(f"Error: {out['error']}", "note")
        if out["assumptions"]:
            html(out["assumptions"], "note")
        if out["rows"]:
            st.dataframe(pd.DataFrame(out["rows"], columns=out["columns"]), hide_index=True)
        if out["sql"]:
            st.code(out["sql"], language="sql")
        if out["tables"]:
            html("tables: " + ", ".join(out["tables"]), "stats")
        stages = " &nbsp;·&nbsp; ".join(f"{k} {v:.2f}s" for k, v in out["timings"].items())
        html(stages + (" &nbsp;·&nbsp; retried" if out["retried"] else ""), "stats")

with eval_tab:
    res = latest_results()
    if res is None:
        st.write("No saved results. Run eval/run_eval.py.")
    else:
        s = res["summary"]
        html(f"{res['file']} &nbsp;·&nbsp; {res.get('label')}", "stats")
        st.markdown(f"**{s['overall']['exec_acc']:.0%}** execution accuracy, "
                    f"**{s['overall']['exact_match']:.0%}** exact match, {s['overall']['n']} questions.")
        for title, key in (("By join count", "by_join_bucket"), ("By trap", "by_trap"), ("By split", "by_split")):
            st.markdown(f"##### {title}")
            st.dataframe(pd.DataFrame(s[key]).T)
        if s.get("retrieval_recall"):
            st.markdown("##### Retrieval recall")
            st.dataframe(pd.DataFrame(s["retrieval_recall"]).T)
        st.markdown("##### Failure tags")
        st.write(s["failure_tags"] or "none")
        st.markdown("##### Questions")
        st.dataframe(pd.DataFrame(res["records"])[["id", "question", "trap", "exec_match", "failure", "pred_sql"]],
                     hide_index=True)
