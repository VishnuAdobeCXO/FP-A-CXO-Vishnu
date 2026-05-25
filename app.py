import streamlit as st
import pandas as pd
from data_loader import get_data, DATA_FOLDER, IS_AZURE, upload_to_blob, list_blobs

st.set_page_config(page_title="FP&A Variance Tool", page_icon="📊", layout="wide")

st.markdown("""
<style>
[data-testid="stSidebar"] { background:#1a1a2e; }
[data-testid="stSidebar"] * { color:#e0e0e0 !important; }
</style>""", unsafe_allow_html=True)

def fmt(v):
    if pd.isna(v): return "—"
    a = abs(v)
    s = f"${a/1e6:.2f}M" if a>=1e6 else f"${a/1e3:.1f}K" if a>=1e3 else f"${a:,.0f}"
    return f"({s})" if v<0 else s

def fmt_pct(v):
    if pd.isna(v) or v is None: return "—"
    return f"({abs(v):.1f}%)" if v<0 else f"{v:.1f}%"

def fu(v):
    if pd.isna(v) or v==0: return "—"
    return "✅ F" if v<0 else "🔴 U"

def style_var(val):
    try:
        raw = str(val).replace("$","").replace(",","").replace("M","").replace("K","")
        neg = "(" in raw
        num = float(raw.strip("()")) * (-1 if neg else 1)
        if num<0: return "color:#1a7f4b;font-weight:600"
        if num>0: return "color:#d93025;font-weight:600"
    except: pass
    return ""

# ── Load ──────────────────────────────────────────────────────────────────────
df_all, _ = get_data()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    st.caption(f"📁 Vishnu folder")
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    st.divider()

    if df_all.empty:
        st.error("No data found."); st.stop()

    all_ver = sorted(df_all["version"].dropna().unique().tolist())
    st.markdown("**Version Mapping**")
    act_ver  = st.selectbox("Actuals version", ["— (not available)"]+all_ver)
    fc_ver   = st.selectbox("Forecast version", all_ver,
                 index=next((i for i,v in enumerate(all_ver) if v=="Forecast"),0))
    oth_ver  = st.selectbox("Other version (snapshot)", all_ver,
                 index=next((i for i,v in enumerate(all_ver) if "WK" in v or "Outlook" in v),0))
    has_act  = act_ver != "— (not available)"

    st.divider()
    all_qtrs = sorted(df_all["fiscal_qtr"].dropna().unique().tolist())
    sel_qtrs = st.multiselect("Quarter(s)", all_qtrs, default=all_qtrs)
    st.divider()

    pl_opts  = sorted(df_all["pl_cat"].dropna().unique().tolist())
    pl_sel   = st.multiselect("P&L Category", pl_opts, default=[])

    st.divider()
    l1_opts  = sorted(df_all["cch_l1"].dropna().unique().tolist())
    sel_l1   = st.multiselect("CCH L1", l1_opts, default=[])
    src2     = df_all[df_all["cch_l1"].isin(sel_l1)] if sel_l1 else df_all
    l2_opts  = sorted(src2["cch_l2"].dropna().unique().tolist())
    sel_l2   = st.multiselect("CCH L2", l2_opts, default=[])
    src3     = src2[src2["cch_l2"].isin(sel_l2)] if sel_l2 else src2
    l3_opts  = sorted(src3["cch_l3"].dropna().unique().tolist())
    sel_l3   = st.multiselect("CCH L3 (Team)", l3_opts, default=[])

    st.divider()
    fc_opts  = sorted(df_all["field_controller"].dropna().unique().tolist())
    sel_fc   = st.multiselect("Field Controller", fc_opts, default=[])

# ── Filter ────────────────────────────────────────────────────────────────────
df = df_all.copy()
if sel_qtrs:  df = df[df["fiscal_qtr"].isin(sel_qtrs)]
if pl_sel:    df = df[df["pl_cat"].isin(pl_sel)]
if sel_l1:    df = df[df["cch_l1"].isin(sel_l1)]
if sel_l2:    df = df[df["cch_l2"].isin(sel_l2)]
if sel_l3:    df = df[df["cch_l3"].isin(sel_l3)]
if sel_fc:    df = df[df["field_controller"].isin(sel_fc)]

fc_tot  = df[df["version"]==fc_ver]["amount"].sum()
oth_tot = df[df["version"]==oth_ver]["amount"].sum()
act_tot = df[df["version"]==act_ver]["amount"].sum() if has_act else None
var_tot = fc_tot - oth_tot

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 📊 FP&A Variance Analysis")
st.caption(f"**{fc_ver}** vs **{oth_ver}** · {', '.join(sel_qtrs) if sel_qtrs else 'All quarters'}")

c1,c2,c3,c4 = st.columns(4)
c1.metric("Forecast",       fmt(fc_tot))
c2.metric("Other Version",  fmt(oth_tot))
c3.metric("Variance",       fmt(var_tot),
          delta=fmt_pct(var_tot/abs(oth_tot)*100 if oth_tot else None), delta_color="inverse")
c4.metric("F/U", "✅ Favourable" if var_tot<0 else ("🔴 Unfavourable" if var_tot>0 else "Nil"))
st.divider()

# ── Build variance table ───────────────────────────────────────────────────────
def build(df, grp_cols):
    fc_df  = df[df["version"]==fc_ver ].groupby(grp_cols)["amount"].sum().rename("forecast")
    oth_df = df[df["version"]==oth_ver].groupby(grp_cols)["amount"].sum().rename("other")
    act_df = df[df["version"]==act_ver].groupby(grp_cols)["amount"].sum().rename("actuals") if has_act else None
    merged = pd.concat([fc_df, oth_df], axis=1).fillna(0)
    if act_df is not None:
        merged = pd.concat([merged, act_df], axis=1).fillna(0)
    else:
        merged["actuals"] = 0.0
    merged = merged.reset_index()
    merged["var_fc_oth"]  = merged["forecast"] - merged["other"]
    merged["var_act_fc"]  = merged["actuals"]  - merged["forecast"]
    merged["var_act_oth"] = merged["actuals"]  - merged["other"]
    merged["pct"]         = merged.apply(lambda r: r["var_fc_oth"]/abs(r["other"])*100 if r["other"]!=0 else None, axis=1)
    merged["fu"]          = merged["var_fc_oth"].apply(fu)
    return merged.sort_values("var_fc_oth", ascending=False)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 Main View","🏢 Org Drill-down","📊 GL View","🗄️ Raw Data","📤 Upload Files"])

# ── TAB 1: Main View ──────────────────────────────────────────────────────────
with tab1:
    st.markdown("### P&L · Major Cost Element")
    st.caption("Use the **CCH L3** sidebar filter to drill into a specific team")
    srch = st.text_input("🔍 Search", placeholder="e.g. Cloud, Salaries, COGS...", key="s1")

    # Group by P&L + Major CE only → each cost element appears once per P&L type
    grp = [c for c in ["pl_cat","major_ce"] if c in df.columns]
    raw = build(df, grp)

    if srch:
        mask = pd.Series(False, index=raw.index)
        for col in ["major_ce","pl_cat"]:
            if col in raw.columns:
                mask |= raw[col].astype(str).str.contains(srch, case=False, na=False)
        raw = raw[mask]

    # Labels
    act_l = "Actuals"
    fc_l  = "Forecast"
    oth_l = "Other Version"

    # Build display DataFrame:
    # P&L | Major CE | Actuals | Forecast | Other Version |
    # Fcst vs Other | Var% (F/O) | Act vs Fcst | Var% (A/F) |
    # Act vs Other | Var% (A/O) | F/U
    disp = pd.DataFrame()
    disp["P&L"]             = raw["pl_cat"]
    disp["Major CE"]        = raw["major_ce"]
    disp[act_l]             = raw["actuals"].apply(fmt)
    disp[fc_l]              = raw["forecast"].apply(fmt)
    disp[oth_l]             = raw["other"].apply(fmt)
    disp["Fcst vs Other"]   = raw["var_fc_oth"].apply(fmt)
    disp["Var % (F/O)"]     = raw.apply(
        lambda r: fmt_pct(r["var_fc_oth"]/abs(r["other"])*100 if r["other"]!=0 else None), axis=1)
    disp["F/U (F/O)"]       = raw["var_fc_oth"].apply(fu)
    disp["Act vs Fcst"]     = raw["var_act_fc"].apply(fmt)
    disp["Var % (A/F)"]     = raw.apply(
        lambda r: fmt_pct(r["var_act_fc"]/abs(r["forecast"])*100 if r["forecast"]!=0 else None), axis=1)
    disp["F/U (A/F)"]       = raw["var_act_fc"].apply(fu)
    disp["Act vs Other"]    = raw["var_act_oth"].apply(fmt)
    disp["Var % (A/O)"]     = raw.apply(
        lambda r: fmt_pct(r["var_act_oth"]/abs(r["other"])*100 if r["other"]!=0 else None), axis=1)
    disp["F/U (A/O)"]       = raw["var_act_oth"].apply(fu)

    var_style_cols = ["Fcst vs Other", "Act vs Fcst", "Act vs Other"]

    st.dataframe(
        disp.style.map(style_var, subset=var_style_cols),
        use_container_width=True, hide_index=True, height=460
    )

    # ── Totals row ────────────────────────────────────────────────────────────
    fc_sum  = raw["forecast"].sum()
    oth_sum = raw["other"].sum()
    act_sum = raw["actuals"].sum()
    vfo_sum = raw["var_fc_oth"].sum()
    vaf_sum = raw["var_act_fc"].sum()
    vao_sum = raw["var_act_oth"].sum()

    tot_df = pd.DataFrame([{
        "P&L":           "TOTAL",
        "Major CE":      "",
        act_l:           fmt(act_sum),
        fc_l:            fmt(fc_sum),
        oth_l:           fmt(oth_sum),
        "Fcst vs Other": fmt(vfo_sum),
        "Var % (F/O)":   fmt_pct(vfo_sum/abs(oth_sum)*100 if oth_sum!=0 else None),
        "F/U (F/O)":     fu(vfo_sum),
        "Act vs Fcst":   fmt(vaf_sum),
        "Var % (A/F)":   fmt_pct(vaf_sum/abs(fc_sum)*100  if fc_sum!=0  else None),
        "F/U (A/F)":     fu(vaf_sum),
        "Act vs Other":  fmt(vao_sum),
        "Var % (A/O)":   fmt_pct(vao_sum/abs(oth_sum)*100 if oth_sum!=0 else None),
        "F/U (A/O)":     fu(vao_sum),
    }])
    st.dataframe(
        tot_df.style.map(style_var, subset=["Fcst vs Other","Act vs Fcst","Act vs Other"]),
        use_container_width=True, hide_index=True
    )
    st.download_button("⬇️ Download CSV", raw.to_csv(index=False).encode(), "variance.csv","text/csv")

# ── TAB 2: Org Drill-down ─────────────────────────────────────────────────────
with tab2:
    st.markdown("### Org Hierarchy Drill-down")
    st.caption("Each org node appears as one consolidated row — use sidebar filters to narrow by P&L or team")
    level = st.radio("Level", ["L1","L1→L2","L1→L2→L3"], horizontal=True)

    # No pl_cat in grouping → each L1/L2/L3 appears exactly once
    lmap = {
        "L1":           ["cch_l1"],
        "L1→L2":        ["cch_l1","cch_l2"],
        "L1→L2→L3":     ["cch_l1","cch_l2","cch_l3"],
    }
    og   = [c for c in lmap[level] if c in df.columns]
    oraw = build(df, og)

    od = oraw.rename(columns={"cch_l1":"L1","cch_l2":"L2","cch_l3":"L3"})

    # Same column order as main view
    od["Actuals"]           = oraw["actuals"].apply(fmt)
    od["Forecast"]          = oraw["forecast"].apply(fmt)
    od["Other Version"]     = oraw["other"].apply(fmt)
    od["Fcst vs Other"]     = oraw["var_fc_oth"].apply(fmt)
    od["Var % (F/O)"]       = oraw.apply(
        lambda r: fmt_pct(r["var_fc_oth"]/abs(r["other"])*100 if r["other"]!=0 else None), axis=1)
    od["F/U (F/O)"]         = oraw["var_fc_oth"].apply(fu)
    od["Act vs Fcst"]       = oraw["var_act_fc"].apply(fmt)
    od["Var % (A/F)"]       = oraw.apply(
        lambda r: fmt_pct(r["var_act_fc"]/abs(r["forecast"])*100 if r["forecast"]!=0 else None), axis=1)
    od["F/U (A/F)"]         = oraw["var_act_fc"].apply(fu)
    od["Act vs Other"]      = oraw["var_act_oth"].apply(fmt)
    od["Var % (A/O)"]       = oraw.apply(
        lambda r: fmt_pct(r["var_act_oth"]/abs(r["other"])*100 if r["other"]!=0 else None), axis=1)
    od["F/U (A/O)"]         = oraw["var_act_oth"].apply(fu)

    dim_cols  = [c for c in ["L1","L2","L3"] if c in od.columns]
    num_cols  = ["Actuals","Forecast","Other Version",
                 "Fcst vs Other","Var % (F/O)","F/U (F/O)",
                 "Act vs Fcst","Var % (A/F)","F/U (A/F)",
                 "Act vs Other","Var % (A/O)","F/U (A/O)"]
    show2     = dim_cols + num_cols

    st.dataframe(
        od[show2].style.map(style_var, subset=["Fcst vs Other","Act vs Fcst","Act vs Other"]),
        use_container_width=True, hide_index=True, height=460
    )

    # Totals row
    o_fc  = oraw["forecast"].sum()
    o_oth = oraw["other"].sum()
    o_act = oraw["actuals"].sum()
    o_vfo = oraw["var_fc_oth"].sum()
    o_vaf = oraw["var_act_fc"].sum()
    o_vao = oraw["var_act_oth"].sum()
    st.dataframe(pd.DataFrame([{
        "L1":"TOTAL","L2":"","L3":"",
        "Actuals":       fmt(o_act),
        "Forecast":      fmt(o_fc),
        "Other Version": fmt(o_oth),
        "Fcst vs Other": fmt(o_vfo),
        "Var % (F/O)":   fmt_pct(o_vfo/abs(o_oth)*100 if o_oth!=0 else None),
        "F/U (F/O)":     fu(o_vfo),
        "Act vs Fcst":   fmt(o_vaf),
        "Var % (A/F)":   fmt_pct(o_vaf/abs(o_fc)*100  if o_fc!=0  else None),
        "F/U (A/F)":     fu(o_vaf),
        "Act vs Other":  fmt(o_vao),
        "Var % (A/O)":   fmt_pct(o_vao/abs(o_oth)*100 if o_oth!=0 else None),
        "F/U (A/O)":     fu(o_vao),
    }]).style.map(style_var, subset=["Fcst vs Other","Act vs Fcst","Act vs Other"]),
    use_container_width=True, hide_index=True)

# ── TAB 3: GL View ────────────────────────────────────────────────────────────
with tab3:
    st.markdown("### GL View")
    st.caption("Grouped by P&L · CCH L2 · CCH L3 · Major CE · GL Description — one row per unique combination")

    srch3 = st.text_input("🔍 Search", placeholder="e.g. Cloud, Salaries...", key="s3")

    # Group by all GL-level dimensions → guaranteed no duplicate rows
    gl_grp = [c for c in ["pl_cat","cch_l2","cch_l3","major_ce","gl_desc"] if c in df.columns]
    gl_raw = build(df, gl_grp)

    if srch3:
        mask3 = pd.Series(False, index=gl_raw.index)
        for col in gl_grp:
            if col in gl_raw.columns:
                mask3 |= gl_raw[col].astype(str).str.contains(srch3, case=False, na=False)
        gl_raw = gl_raw[mask3]

    gl_disp = pd.DataFrame()
    gl_disp["P&L"]           = gl_raw["pl_cat"]
    gl_disp["CCH L2"]        = gl_raw.get("cch_l2", "")
    gl_disp["CCH L3"]        = gl_raw.get("cch_l3", "")
    gl_disp["Major CE"]      = gl_raw.get("major_ce", "")
    gl_disp["GL Description"]= gl_raw.get("gl_desc", "")
    gl_disp["Actuals"]       = gl_raw["actuals"].apply(fmt)
    gl_disp["Forecast"]      = gl_raw["forecast"].apply(fmt)
    gl_disp["Other Version"] = gl_raw["other"].apply(fmt)
    gl_disp["Fcst vs Other"] = gl_raw["var_fc_oth"].apply(fmt)
    gl_disp["Var % (F/O)"]   = gl_raw.apply(
        lambda r: fmt_pct(r["var_fc_oth"]/abs(r["other"])*100 if r["other"]!=0 else None), axis=1)
    gl_disp["F/U (F/O)"]     = gl_raw["var_fc_oth"].apply(fu)
    gl_disp["Act vs Fcst"]   = gl_raw["var_act_fc"].apply(fmt)
    gl_disp["Var % (A/F)"]   = gl_raw.apply(
        lambda r: fmt_pct(r["var_act_fc"]/abs(r["forecast"])*100 if r["forecast"]!=0 else None), axis=1)
    gl_disp["F/U (A/F)"]     = gl_raw["var_act_fc"].apply(fu)
    gl_disp["Act vs Other"]  = gl_raw["var_act_oth"].apply(fmt)
    gl_disp["Var % (A/O)"]   = gl_raw.apply(
        lambda r: fmt_pct(r["var_act_oth"]/abs(r["other"])*100 if r["other"]!=0 else None), axis=1)
    gl_disp["F/U (A/O)"]     = gl_raw["var_act_oth"].apply(fu)

    gl_var_cols = ["Fcst vs Other","Act vs Fcst","Act vs Other"]
    st.dataframe(
        gl_disp.style.map(style_var, subset=gl_var_cols),
        use_container_width=True, hide_index=True, height=500
    )

    # Totals row
    g_fc  = gl_raw["forecast"].sum()
    g_oth = gl_raw["other"].sum()
    g_act = gl_raw["actuals"].sum()
    g_vfo = gl_raw["var_fc_oth"].sum()
    g_vaf = gl_raw["var_act_fc"].sum()
    g_vao = gl_raw["var_act_oth"].sum()
    gl_tot = pd.DataFrame([{
        "P&L":"TOTAL","CCH L2":"","CCH L3":"","Major CE":"","GL Description":"",
        "Actuals":       fmt(g_act),
        "Forecast":      fmt(g_fc),
        "Other Version": fmt(g_oth),
        "Fcst vs Other": fmt(g_vfo),
        "Var % (F/O)":   fmt_pct(g_vfo/abs(g_oth)*100 if g_oth!=0 else None),
        "F/U (F/O)":     fu(g_vfo),
        "Act vs Fcst":   fmt(g_vaf),
        "Var % (A/F)":   fmt_pct(g_vaf/abs(g_fc)*100  if g_fc!=0  else None),
        "F/U (A/F)":     fu(g_vaf),
        "Act vs Other":  fmt(g_vao),
        "Var % (A/O)":   fmt_pct(g_vao/abs(g_oth)*100 if g_oth!=0 else None),
        "F/U (A/O)":     fu(g_vao),
    }])
    st.dataframe(
        gl_tot.style.map(style_var, subset=gl_var_cols),
        use_container_width=True, hide_index=True
    )
    st.download_button("⬇️ Download GL View", gl_raw.to_csv(index=False).encode(), "gl_view.csv","text/csv")

# ── TAB 4: Raw Data ───────────────────────────────────────────────────────────
with tab4:
    st.markdown("### Raw Data")
    st.caption(f"{len(df):,} rows after filters")
    ver_f = st.multiselect("Versions", sorted(df["version"].unique()), default=sorted(df["version"].unique()))
    dv    = df[df["version"].isin(ver_f)] if ver_f else df
    show_c = [c for c in ["version","pl_cat","cch_l1","cch_l2","cch_l3","major_ce",
                           "gl_code","gl_desc","fiscal_qtr","amount"] if c in dv.columns]
    st.dataframe(dv[show_c].sort_values("amount",ascending=False),
                 use_container_width=True, hide_index=True, height=460)
    st.download_button("⬇️ Download", dv.to_csv(index=False).encode(), "raw.csv","text/csv")

# ── TAB 5: Upload / Update Files ─────────────────────────────────────────────
with tab5:
    st.markdown("### Update Data Files")

    if IS_AZURE:
        # ── Azure mode: upload directly to Blob Storage ──
        st.caption("Upload new Actuals, Forecast, or Snapshot `.xlsx` files. "
                   "The app refreshes automatically within 60 seconds.")
        uploaded = st.file_uploader("Choose Excel file(s)", type=["xlsx"],
                                    accept_multiple_files=True)
        if uploaded:
            for f in uploaded:
                try:
                    upload_to_blob(f.read(), f.name)
                    st.success(f"✅ Uploaded **{f.name}**")
                except Exception as e:
                    st.error(f"❌ Failed to upload {f.name}: {e}")
            if st.button("🔄 Refresh data now"):
                st.cache_data.clear(); st.rerun()
        st.divider()
        st.markdown("#### Files currently in storage")
        try:
            blobs = list_blobs()
            for b in (blobs or []):
                st.markdown(f"- 📄 `{b}`")
            if not blobs:
                st.info("No files uploaded yet.")
        except Exception as e:
            st.warning(f"Could not list blobs: {e}")

    else:
        # ── Streamlit Cloud / local mode: guide user to update via GitHub ──
        st.info("ℹ️ **How to update the data**")
        st.markdown("""
Replace the files in the **`data/`** folder of the GitHub repository, then commit & push.
Streamlit Cloud will automatically redeploy within ~1 minute and pick up the new data.

**Steps:**
1. Open [github.com](https://github.com) → your repository → **`data/`** folder
2. Click the file you want to replace → **⋯ menu → Upload files**
3. Drag your new `.xlsx` file in (keep the same filename)
4. Click **Commit changes**
5. Wait ~60 seconds, then hit **🔄 Refresh Data** in the sidebar

Alternatively, if you have Git installed locally:
```
cd C:\\variance_app
git add data\\*.xlsx
git commit -m "update data files"
git push
```
        """)
        if st.button("🔄 Refresh Data now"):
            st.cache_data.clear(); st.rerun()
