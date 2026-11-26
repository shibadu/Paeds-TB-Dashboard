"""
Pediatric TB training — pre-test vs post-test dashboard.

Data: ONE Google Sheet tab (Google Form responses) where every row is a single
submission and a "Test Type" column says whether it is a Pre-test or Post-test.

Data sources (sidebar):
  1. Live Google Sheet  - works if the sheet is shared "anyone with the link"
  2. File upload        - CSV / XLSX exported from the sheet (fallback)

Run:  streamlit run app.py
"""

from __future__ import annotations

import io
import re
import unicodedata
from difflib import get_close_matches

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

SHEET_ID = "1O4imjNe9kEW7w8NtIZEgQHF-JjKE0y0M6xFbXNmB6cI"
GID = "444284147"               # Form Responses 1
UPLOAD_TAB = "Form Responses 1"  # tab read when an XLSX is uploaded

REFRESH_SECONDS = 300

# Column guesses tuned to this form export (all overridable in the sidebar)
SCORE_GUESS = "score"
ID_GUESS = "participant id"
EMAIL_GUESS = "email"
SESSION_GUESS = "training session"
TYPE_GUESS = "test type"

INK = "#17222B"
PRE_C = "#8FA3B0"
POST_C = "#12726B"
UP_C = "#12726B"
DOWN_C = "#B0443C"
FLAT_C = "#B9C2C8"

st.set_page_config(page_title="Pediatric TB training", page_icon="📈", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 2.2rem; max-width: 1400px;}
      [data-testid="stMetricValue"] {font-size: 1.9rem;}
      h1 {letter-spacing: -0.02em;}
      [data-testid="stToolbar"] {visibility: hidden; height: 0; position: fixed;}
      [data-testid="stDecoration"] {visibility: hidden; height: 0;}
      #MainMenu {visibility: hidden;}
      footer {visibility: hidden; height: 0;}
      [data-testid="stBottomBlockContainer"] {visibility: hidden; height: 0;}
      a[href*="streamlit.io"], a[href*="github.com/streamlit"] {display: none !important;}
      .viewerBadge_container__1QSob, .viewerBadge_link__1S137 {display: none !important;}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Small compatibility helpers (Streamlit renamed use_container_width -> width)
# --------------------------------------------------------------------------

def show_chart(fig: go.Figure) -> None:
    try:
        st.plotly_chart(fig, width="stretch")
    except TypeError:
        st.plotly_chart(fig, use_container_width=True)


def show_table(df: pd.DataFrame, **kwargs) -> None:
    try:
        st.dataframe(df, width="stretch", **kwargs)
    except TypeError:
        st.dataframe(df, use_container_width=True, **kwargs)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

@st.cache_data(ttl=REFRESH_SECONDS, show_spinner=False)
def load_public_csv(sheet_id: str, gid: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    return pd.read_csv(url)


def read_upload(file) -> pd.DataFrame:
    if file.name.lower().endswith((".xlsx", ".xlsm", ".xls")):
        xls = pd.ExcelFile(file)
        tab = UPLOAD_TAB if UPLOAD_TAB in xls.sheet_names else xls.sheet_names[0]
        return xls.parse(tab)
    return pd.read_csv(file)


# --------------------------------------------------------------------------
# Cleaning helpers
# --------------------------------------------------------------------------

def normalise_id(value) -> str:
    """Collapse messy participant IDs: 'PTB 0020', 'PTB02', 'PTBO15', 'ptb012'.

    Short alphanumeric codes ('PTB' + number) key on the digits alone, so
    'PTB02' and 'PTB002' agree. Anything else (e.g. 'Betty1') becomes a
    lower-cased text key.
    """
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().strip()
    if not text:
        return ""
    if re.fullmatch(r"(?i)ptb\s*[o0-9]+", text):       # letter O typed for zero
        text = re.sub(r"(?i)o", "0", text)
    digits = re.sub(r"\D", "", text)
    letters = re.sub(r"[^A-Za-z]", "", text)
    if digits and len(letters) <= 3:
        return str(int(digits))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def normalise_email(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().lower()
    return text if "@" in text else ""


def find_col(columns: list[str], wanted: str, fallback: int = 0) -> int:
    for i, col in enumerate(columns):
        if wanted in col.lower():
            return i
    return min(fallback, len(columns) - 1)


def cohens_dz(diff: pd.Series) -> float:
    sd = diff.std(ddof=1)
    return float(diff.mean() / sd) if sd and not np.isnan(sd) else np.nan


# --------------------------------------------------------------------------
# Sidebar — source
# --------------------------------------------------------------------------

st.sidebar.header("Data")
st.sidebar.button("↻ Refresh now", on_click=st.cache_data.clear,
                  help=f"Live data is cached for {REFRESH_SECONDS // 60} min between refreshes")
uploaded = st.sidebar.file_uploader("…or upload an export (CSV / XLSX)", type=["csv", "xlsx", "xls"])

error = None
try:
    raw = read_upload(uploaded) if uploaded else load_public_csv(SHEET_ID, GID)
except Exception as exc:  # noqa: BLE001
    raw, error = None, f"Couldn't read the data: {exc}"

st.title("Pediatric TB training — pre/post test")
st.caption("Scores matched participant by participant across the pre-test and post-test.")

if error:
    st.info(error + "  \nShare the sheet as “Anyone with the link can view”, or upload an export in the sidebar.")
    st.stop()
if raw is None or raw.empty:
    st.warning("The sheet came back empty.")
    st.stop()

raw = raw.rename(columns=lambda c: str(c).strip())
cols = list(raw.columns)

# --------------------------------------------------------------------------
# Sidebar — column mapping
# --------------------------------------------------------------------------

st.sidebar.header("Columns")
with st.sidebar.expander("Column mapping", expanded=False):
    st.caption("Auto-detected — only change if the form is edited.")
    type_col = st.selectbox("Test type", cols, index=find_col(cols, TYPE_GUESS))
    score_col = st.selectbox("Score", cols, index=find_col(cols, SCORE_GUESS, 1))
    id_col = st.selectbox("Participant ID", cols, index=find_col(cols, ID_GUESS, 2))
    email_col = st.selectbox("Email (used for matching)", ["(none)"] + cols,
                             index=1 + find_col(cols, EMAIL_GUESS, 0) if any(EMAIL_GUESS in c.lower() for c in cols) else 0)
    session_col = st.selectbox("Training session", ["(none)"] + cols,
                               index=1 + find_col(cols, SESSION_GUESS, 0) if any(SESSION_GUESS in c.lower() for c in cols) else 0)
    types = sorted(raw[type_col].dropna().astype(str).str.strip().unique())
    pre_label = st.selectbox("Value meaning “pre-test”", types,
                             index=next((i for i, t in enumerate(types) if "pre" in t.lower()), 0))
    post_label = st.selectbox("Value meaning “post-test”", types,
                              index=next((i for i, t in enumerate(types) if "post" in t.lower()), min(1, len(types) - 1)))

has_email = email_col != "(none)"
has_session = session_col != "(none)"

match_by = st.sidebar.radio(
    "Match pre ↔ post by", ["Email", "Participant ID"] if has_email else ["Participant ID"],
    help="Participant IDs are often mistyped between the two tests; email is more reliable.",
)
fuzzy = st.sidebar.checkbox("Match near-identical IDs", value=True,
                            help="Catches small typos when matching on Participant ID.",
                            disabled=match_by == "Email")
keep = st.sidebar.selectbox("If someone submitted twice", ["Keep first", "Keep last", "Keep best"])

# --------------------------------------------------------------------------
# Build the matched dataset
# --------------------------------------------------------------------------

df = raw.copy()
df["_type"] = df[type_col].astype(str).str.strip()
df["_score"] = pd.to_numeric(df[score_col], errors="coerce")
df["_id"] = df[id_col].astype(str).str.strip()
df["_idkey"] = df[id_col].map(normalise_id)
df["_email"] = df[email_col].map(normalise_email) if has_email else ""
df["_session"] = df[session_col].astype(str).str.strip() if has_session else "All"
df["_key"] = df["_email"] if match_by == "Email" else df["_idkey"]
if match_by == "Email":                       # fall back to ID where an email is missing
    df.loc[df["_key"] == "", "_key"] = "id:" + df["_idkey"]

n_questions = sum(bool(re.match(r"^Q\d+\b", c)) for c in cols)
observed_max = float(df["_score"].max()) if df["_score"].notna().any() else 1.0
default_max = float(max(n_questions, observed_max))
max_score = st.sidebar.number_input(
    "Maximum possible score", min_value=1.0, value=default_max, step=1.0,
    help=f"Defaults to the number of questions found ({n_questions}); highest score seen is {observed_max:.0f}. "
         "Change it if some questions carry more than one mark.",
)
as_percent = st.sidebar.checkbox("Show scores as %", value=True)
pass_mark = st.sidebar.slider("Pass mark (%)", 0, 100, 80, step=5)

pre_all = df[(df["_type"] == pre_label) & df["_score"].notna() & (df["_key"] != "")]
post_all = df[(df["_type"] == post_label) & df["_score"].notna() & (df["_key"] != "")]


def dedupe(frame: pd.DataFrame) -> pd.DataFrame:
    if keep == "Keep best":
        return frame.sort_values("_score", ascending=False).drop_duplicates("_key")
    return frame.drop_duplicates("_key", keep="first" if keep == "Keep first" else "last")


pre, post = dedupe(pre_all), dedupe(post_all)
dupes_dropped = (len(pre_all) - len(pre)) + (len(post_all) - len(post))

if fuzzy and match_by == "Participant ID":
    pre_keys = set(pre["_key"])
    remap = {}
    for key in post["_key"]:
        if key not in pre_keys:
            close = get_close_matches(key, pre_keys, n=1, cutoff=0.9)
            if close:
                remap[key] = close[0]
    post = dedupe(post.assign(_key=post["_key"].replace(remap)))

matched = pre[["_key", "_id", "_idkey", "_session", "_score"]].merge(
    post[["_key", "_id", "_idkey", "_session", "_score"]],
    on="_key", how="left", suffixes=("", "_post"),
).rename(columns={"_score": "pre", "_score_post": "post", "_id": "id", "_id_post": "id_post",
                  "_session": "session", "_session_post": "session_post"})

if matched.empty:
    st.error("No usable pre-test rows found — check the column mapping in the sidebar.")
    st.stop()

if as_percent:
    matched["pre"] = matched["pre"] / max_score * 100
    matched["post"] = matched["post"] / max_score * 100
    unit, ceiling = "%", 100.0
else:
    unit, ceiling = "", max_score

matched["gain"] = matched["post"] - matched["pre"]
matched["pre_pct"] = matched["pre"] / ceiling * 100
matched["post_pct"] = matched["post"] / ceiling * 100

# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------

view = matched
if has_session:
    sessions = sorted(view["session"].dropna().unique())
    if len(sessions) > 1:
        st.sidebar.header("Filters")
        chosen = st.sidebar.multiselect("Training session", sessions, default=sessions)
        view = view[view["session"].isin(chosen)]

if view.empty:
    st.warning("No participants left after filtering.")
    st.stop()

fmt = lambda v: f"{v:.1f}{unit}"  # noqa: E731

paired = view.dropna(subset=["post"])
pre_only_n = len(view) - len(paired)

# --------------------------------------------------------------------------
# Data-quality flags (shown, never silently resolved)
# --------------------------------------------------------------------------

issues = paired[paired["id"].map(normalise_id) != paired["id_post"].map(normalise_id)]
sess_issues = paired[paired["session"] != paired["session_post"]] if has_session else paired.iloc[0:0]
post_only = post[~post["_key"].isin(pre["_key"])]
over_max = df["_score"].max() > max_score if df["_score"].notna().any() else False

n_flags = (len(issues) > 0) + (len(sess_issues) > 0) + (dupes_dropped > 0) + (len(post_only) > 0) + bool(over_max)
if n_flags:
    with st.expander(f"⚠ Data checks ({n_flags})", expanded=False):
        if len(issues):
            st.markdown(f"**{len(issues)} participant(s) used a different ID on the post-test** "
                        f"(matched by {match_by.lower()}, so scores are still paired):")
            show_table(issues[["id", "id_post"]].rename(columns={"id": "Pre-test ID", "id_post": "Post-test ID"}),
                       hide_index=True)
        if len(sess_issues):
            st.markdown(f"**{len(sess_issues)} participant(s) picked a different training session on the post-test:**")
            show_table(sess_issues[["id", "session", "session_post"]].rename(
                columns={"id": "Participant", "session": "Pre-test session", "session_post": "Post-test session"}),
                hide_index=True)
        if dupes_dropped:
            st.markdown(f"**{dupes_dropped} duplicate submission(s) removed** ({keep.lower()} rule).")
        if len(post_only):
            st.markdown(f"**{len(post_only)} post-test submission(s) with no matching pre-test:** "
                        + ", ".join(post_only["_id"].astype(str)))
        if over_max:
            st.markdown(f"**A score ({df['_score'].max():.0f}) exceeds the maximum score you set ({max_score:.0f})** — "
                        "raise the maximum in the sidebar.")

# --------------------------------------------------------------------------
# Pre-test only fallback
# --------------------------------------------------------------------------

if paired.empty:
    st.info("No post-test scores yet for this selection — showing pre-test results only.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Participants (pre-test)", f"{len(view):,}")
    c2.metric("Mean pre-test", fmt(view["pre"].mean()))
    c3.metric(f"Passing at {pass_mark}%", f"{(view['pre_pct'] >= pass_mark).mean() * 100:.0f}%")

    dist = go.Figure(go.Histogram(x=view["pre"], marker_color=PRE_C,
                                  xbins=dict(start=0, end=ceiling * 1.0001, size=max(ceiling / 20, 1))))
    dist.add_vline(x=pass_mark / 100 * ceiling, line_dash="dot", line_color=INK,
                   annotation_text="Pass mark", annotation_position="top")
    dist.update_layout(height=380, margin=dict(t=10, b=10, l=10, r=10), xaxis_title=f"Score {unit}".strip(),
                       yaxis_title="Participants", plot_bgcolor="rgba(0,0,0,0)")
    show_chart(dist)
    st.stop()

# --------------------------------------------------------------------------
# Headline numbers
# --------------------------------------------------------------------------

if pre_only_n:
    st.caption(f"{pre_only_n} of {len(view):,} participants have a pre-test only (no post-test yet) — "
               "listed in the table below but excluded from the comparisons.")

full_view = view
view = paired
improved = (view["gain"] > 0).mean() * 100
pre_pass = (view["pre_pct"] >= pass_mark).mean() * 100
post_pass = (view["post_pct"] >= pass_mark).mean() * 100

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Matched participants", f"{len(view):,}",
          help=f"Pre-test {len(pre):,} · post-test {len(post):,} submissions (after de-duplication)")
c2.metric("Mean pre-test", fmt(view["pre"].mean()))
c3.metric("Mean post-test", fmt(view["post"].mean()), delta=fmt(view["gain"].mean()))
c4.metric(f"Passing at {pass_mark}%", f"{post_pass:.0f}%", delta=f"{post_pass - pre_pass:+.0f} pts vs pre")
c5.metric("Improved", f"{improved:.0f}%", help="Share whose post-test score is higher than their pre-test score")

stat_line = (f"Mean gain {view['gain'].mean():+.1f}{unit} (SD {view['gain'].std(ddof=1):.1f}) · "
             f"effect size dz = {cohens_dz(view['gain']):.2f}")
try:
    from scipy import stats

    t_stat, p_val = stats.ttest_rel(view["post"], view["pre"])
    stat_line += f" · paired t = {t_stat:.2f}, p {'< 0.001' if p_val < 0.001 else f'= {p_val:.3f}'}"
    if (view["gain"] != 0).any():
        w_p = stats.wilcoxon(view["post"], view["pre"]).pvalue
        stat_line += f" · Wilcoxon p {'< 0.001' if w_p < 0.001 else f'= {w_p:.3f}'}"
except Exception:  # noqa: BLE001
    pass
st.caption(stat_line)
st.divider()

# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------

left, right = st.columns(2)

with left:
    st.subheader("Where scores moved")
    slope = go.Figure()
    for _, row in view.sort_values("gain").iterrows():
        colour = UP_C if row["gain"] > 0 else DOWN_C if row["gain"] < 0 else FLAT_C
        slope.add_trace(go.Scatter(
            x=["Pre-test", "Post-test"], y=[row["pre"], row["post"]], mode="lines+markers",
            line=dict(color=colour, width=1), marker=dict(size=5, color=colour), opacity=0.5, showlegend=False,
            hovertemplate=f"{row['id']}<br>%{{x}}: %{{y:.1f}}{unit}<extra></extra>",
        ))
    slope.add_trace(go.Scatter(
        x=["Pre-test", "Post-test"], y=[view["pre"].mean(), view["post"].mean()],
        mode="lines+markers+text", line=dict(color=INK, width=4), marker=dict(size=11, color=INK), name="Mean",
        text=[fmt(view["pre"].mean()), fmt(view["post"].mean())],
        textposition="middle right", textfont=dict(color=INK, size=13),
    ))
    slope.update_layout(height=420, margin=dict(t=10, b=10, l=10, r=40), yaxis_title=f"Score {unit}".strip(),
                        showlegend=False, plot_bgcolor="rgba(0,0,0,0)")
    show_chart(slope)

with right:
    st.subheader("Score distribution")
    bins = dict(start=0, end=ceiling * 1.0001, size=max(ceiling / 20, 1))
    dist = go.Figure()
    dist.add_trace(go.Histogram(x=view["pre"], name="Pre-test", marker_color=PRE_C, xbins=bins, opacity=0.75))
    dist.add_trace(go.Histogram(x=view["post"], name="Post-test", marker_color=POST_C, xbins=bins, opacity=0.75))
    dist.add_vline(x=pass_mark / 100 * ceiling, line_dash="dot", line_color=INK,
                   annotation_text="Pass mark", annotation_position="top")
    dist.update_layout(barmode="overlay", height=420, margin=dict(t=10, b=10, l=10, r=10),
                       xaxis_title=f"Score {unit}".strip(), yaxis_title="Participants",
                       plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=1.02, x=0))
    show_chart(dist)

left2, right2 = st.columns(2)

with left2:
    st.subheader("Gain per participant")
    ordered = view.sort_values("gain", ascending=False)
    bar = go.Figure(go.Bar(
        x=ordered["id"], y=ordered["gain"],
        marker_color=[UP_C if g > 0 else DOWN_C if g < 0 else FLAT_C for g in ordered["gain"]],
        hovertemplate="%{x}<br>Gain %{y:+.1f}" + unit + "<extra></extra>",
    ))
    bar.add_hline(y=view["gain"].mean(), line_dash="dot", line_color=INK,
                  annotation_text=f"Mean {view['gain'].mean():+.1f}{unit}", annotation_position="top right")
    bar.update_layout(height=430, margin=dict(t=10, b=10, l=10, r=10), yaxis_title=f"Gain {unit}".strip(),
                      xaxis=dict(type="category", tickangle=-60), plot_bgcolor="rgba(0,0,0,0)")
    show_chart(bar)

with right2:
    st.subheader("Individual movement")
    scatter = go.Figure()
    scatter.add_trace(go.Scatter(
        x=view["pre"], y=view["post"], mode="markers",
        marker=dict(size=9, color=view["gain"], colorscale=[[0, DOWN_C], [0.5, FLAT_C], [1, UP_C]],
                    cmid=0, line=dict(width=0.5, color="white")),
        text=view["id"].astype(str),
        hovertemplate="%{text}<br>Pre %{x:.1f}<br>Post %{y:.1f}<extra></extra>",
    ))
    scatter.add_trace(go.Scatter(x=[0, ceiling], y=[0, ceiling], mode="lines",
                                 line=dict(color=INK, dash="dash", width=1), hoverinfo="skip", showlegend=False))
    scatter.update_layout(height=430, margin=dict(t=10, b=10, l=10, r=10),
                          xaxis_title=f"Pre-test {unit}".strip(), yaxis_title=f"Post-test {unit}".strip(),
                          plot_bgcolor="rgba(0,0,0,0)", showlegend=False)
    show_chart(scatter)
    st.caption("Points above the dashed line improved; below it, scores dropped.")

if has_session and view["session"].nunique() > 1:
    st.subheader("By training session")
    grouped = (view.groupby("session")
               .agg(n=("gain", "size"), pre=("pre", "mean"), post=("post", "mean"), gain=("gain", "mean"))
               .sort_values("gain"))
    grouped = grouped[grouped["n"] >= 2]
    if grouped.empty:
        st.caption("Not enough participants per session to compare.")
    else:
        gb = go.Figure()
        gb.add_trace(go.Bar(y=grouped.index, x=grouped["pre"], name="Pre-test", orientation="h", marker_color=PRE_C))
        gb.add_trace(go.Bar(y=grouped.index, x=grouped["post"], name="Post-test", orientation="h", marker_color=POST_C))
        gb.update_layout(barmode="group", height=max(300, 90 * len(grouped)), margin=dict(t=10, b=10, l=10, r=10),
                         xaxis_title=f"Mean score {unit}".strip(), plot_bgcolor="rgba(0,0,0,0)",
                         legend=dict(orientation="h", y=1.1, x=0))
        show_chart(gb)
        show_table(grouped.rename(columns={"n": "Participants", "pre": "Mean pre", "post": "Mean post",
                                           "gain": "Mean gain"}).round(1))

# --------------------------------------------------------------------------
# Participant table
# --------------------------------------------------------------------------

st.subheader("Participants")
only_dropped = st.checkbox("Show only those who did not improve")
table = full_view[full_view["gain"] <= 0] if only_dropped else full_view
columns = ["id"] + (["session"] if has_session else []) + ["pre", "post", "gain"]
table = (table[columns]
         .rename(columns={"id": "Participant", "session": "Training session", "pre": "Pre-test",
                          "post": "Post-test", "gain": "Gain"})
         .sort_values("Gain", ascending=False, na_position="last")
         .round(1))
show_table(table, height=430, hide_index=True)

buffer = io.StringIO()
table.to_csv(buffer, index=False)
st.download_button("Download this table (CSV)", buffer.getvalue(),
                   file_name="pediatric_tb_pre_post_results.csv", mime="text/csv")
