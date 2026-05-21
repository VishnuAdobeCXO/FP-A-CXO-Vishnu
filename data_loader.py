"""
data_loader.py
Works in two modes:
  LOCAL  → reads .xlsx files from DATA_FOLDER on disk
  AZURE  → reads .xlsx files from Azure Blob Storage container
Mode is auto-detected: if AZURE_STORAGE_CONNECTION_STRING env var is set → Azure mode.
"""

import os, io, glob, hashlib
import pandas as pd
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
# Prefer a ./data/ folder sitting next to this file (works on Streamlit Cloud).
# Falls back to the local OneDrive path when ./data/ doesn't exist.
_script_dir = os.path.dirname(os.path.abspath(__file__))
_bundled    = os.path.join(_script_dir, "data")
DATA_FOLDER = _bundled if os.path.isdir(_bundled) else \
              r"C:\Users\vkovoor\OneDrive - Adobe\COE FP&A\1. Outlook and QRF Workbooks\Vishnu"
BLOB_CONTAINER     = "variance-data"          # Azure Blob container name
AZURE_CONN_STR     = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
IS_AZURE           = bool(AZURE_CONN_STR)

COLS = ["pl_cat","cch_l1","cch_l2","cch_l3","major_ce","ce_grp",
        "gl_code","gl_desc","version","fiscal_qtr","fiscal_year",
        "amount","cost_center","source"]


# ── Utilities ──────────────────────────────────────────────────────────────────
def _unique_cols(df):
    seen, cols = {}, []
    for c in df.columns:
        if c in seen:
            seen[c] += 1
            cols.append(f"{c}__{seen[c]}")
        else:
            seen[c] = 0
            cols.append(c)
    df.columns = cols
    return df

def _find(df, names):
    for n in names:
        if n in df.columns: return n
    return None

def _norm_pl(v):
    return {"Fixed":"FIXED","FIXED":"FIXED","Variable":"VARIABLE",
            "VARIABLE":"VARIABLE","COGS":"COGS"}.get(str(v).strip(), str(v).strip().upper())

def _split_gl(v):
    p = str(v).split("-", 1)
    return p[0].strip(), (p[1].strip() if len(p) > 1 else "")


# ── File loaders ───────────────────────────────────────────────────────────────
def _load_row_file(src):
    df = _unique_cols(pd.read_excel(src, sheet_name=0))
    n  = len(df)
    pl  = _find(df, ["P&L Category","PL Category"])
    l1  = _find(df, ["CCH Lvl 1 Name","CCH Lvl 1","CCH EVP Owner"])
    l2  = _find(df, ["CCH Lvl 2 Name","CCH Lvl 2"])
    l3  = _find(df, ["CCH Lvl 3 Name","CCH Lvl 3"])
    mce = _find(df, ["Major Cost Element Grp Desc"])
    ceg = _find(df, ["Cost Element Grp Desc"])
    gl  = _find(df, ["GL Account"])
    gld = _find(df, ["GL Account Desc"])
    ver = _find(df, ["Version"])
    qtr = _find(df, ["Fiscal Qtr/Year"])
    yr  = _find(df, ["Fiscal Year"])
    amt = _find(df, ["Value USD @ Plan Rates","Amount"])
    cc  = _find(df, ["Cost Center"])
    name = src if isinstance(src, str) else getattr(src, "name", "upload")
    return pd.DataFrame({
        "pl_cat":     df[pl].apply(_norm_pl)                              if pl  else [None]*n,
        "cch_l1":     df[l1].values                                       if l1  else [None]*n,
        "cch_l2":     df[l2].values                                       if l2  else [None]*n,
        "cch_l3":     df[l3].values                                       if l3  else [None]*n,
        "major_ce":   df[mce].values                                      if mce else [None]*n,
        "ce_grp":     df[ceg].values                                      if ceg else [None]*n,
        "gl_code":    df[gl].fillna(0).astype(float).astype(int).astype(str) if gl else [""]*n,
        "gl_desc":    df[gld].values                                      if gld else [""]*n,
        "version":    df[ver].values                                      if ver else ["Unknown"]*n,
        "fiscal_qtr": df[qtr].values                                      if qtr else [None]*n,
        "fiscal_year":df[yr].values                                       if yr  else [None]*n,
        "amount":     pd.to_numeric(df[amt], errors="coerce").fillna(0).values if amt else [0.0]*n,
        "cost_center":df[cc].values                                       if cc  else [None]*n,
        "source":     [os.path.basename(str(name))]*n,
    })

def _load_wide_file(src):
    df = _unique_cols(pd.read_excel(src, sheet_name=0))
    n  = len(df)
    pl  = _find(df, ["PL Category","P&L Category"])
    l1  = _find(df, ["CCH Lvl 1","CCH Lvl 1 Name","CCH EVP Owner"])
    l2  = _find(df, ["CCH Lvl 2","CCH Lvl 2 Name"])
    l3  = _find(df, ["CCH Lvl 3","CCH Lvl 3 Name"])
    mce = _find(df, ["Major Cost Element Grp Desc"])
    ceg = _find(df, ["Cost Element Grp Desc"])
    gl  = _find(df, ["GL Account"])
    ver = _find(df, ["Version"])
    cc  = _find(df, ["Cost Center"])
    name = src if isinstance(src, str) else getattr(src, "name", "upload")

    qtr_cols = [c for c in df.columns
                if "Amount USD" in str(c) and "Q" in str(c) and "FY" in str(c)]
    if not qtr_cols:
        return pd.DataFrame(columns=COLS)

    chunks = []
    for col in qtr_cols:
        label = str(col).replace("Amount USD (FX Adj) - ","").replace("Amount USD - ","").strip()
        parts = label.split()
        qtr_std = f"20{parts[1][2:]}-{parts[0]}" if len(parts)==2 else label
        yr_val  = int(f"20{parts[1][2:]}") if len(parts)==2 else None
        gl_code = df[gl].apply(lambda x: _split_gl(x)[0]).values if gl else [""]*n
        gl_desc = df[gl].apply(lambda x: _split_gl(x)[1]).values if gl else [""]*n
        chunks.append(pd.DataFrame({
            "pl_cat":     df[pl].apply(_norm_pl).values  if pl  else [None]*n,
            "cch_l1":     df[l1].values                  if l1  else [None]*n,
            "cch_l2":     df[l2].values                  if l2  else [None]*n,
            "cch_l3":     df[l3].values                  if l3  else [None]*n,
            "major_ce":   df[mce].values                 if mce else [None]*n,
            "ce_grp":     df[ceg].values                 if ceg else [None]*n,
            "gl_code":    gl_code,
            "gl_desc":    gl_desc,
            "version":    df[ver].values                 if ver else ["Forecast"]*n,
            "fiscal_qtr": [qtr_std]*n,
            "fiscal_year":[yr_val]*n,
            "amount":     pd.to_numeric(df[col], errors="coerce").fillna(0).values,
            "cost_center":df[cc].values                  if cc  else [None]*n,
            "source":     [os.path.basename(str(name))]*n,
        }))
    return pd.concat(chunks, ignore_index=True)

def _process_file(src):
    """Auto-detect file type and load."""
    peek = _unique_cols(pd.read_excel(src, sheet_name=0, nrows=1))
    is_wide = any("Amount USD" in str(c) and "Q" in str(c) for c in peek.columns)
    if hasattr(src, "seek"): src.seek(0)   # reset buffer for BytesIO
    loaded = _load_wide_file(src) if is_wide else _load_row_file(src)
    for c in COLS:
        if c not in loaded.columns:
            loaded[c] = None
    return loaded[COLS]


# ── Azure Blob helpers ─────────────────────────────────────────────────────────
def _get_blob_client():
    from azure.storage.blob import BlobServiceClient
    return BlobServiceClient.from_connection_string(AZURE_CONN_STR)

def upload_to_blob(file_bytes: bytes, filename: str):
    """Upload a file to Azure Blob Storage."""
    client = _get_blob_client()
    blob   = client.get_blob_client(container=BLOB_CONTAINER, blob=filename)
    blob.upload_blob(file_bytes, overwrite=True)

def list_blobs() -> list:
    client = _get_blob_client()
    return [b.name for b in client.get_container_client(BLOB_CONTAINER).list_blobs()
            if b.name.endswith(".xlsx")]

def _blob_hash() -> str:
    try:
        client = _get_blob_client()
        blobs  = list(client.get_container_client(BLOB_CONTAINER).list_blobs())
        sig    = "|".join(f"{b.name}:{b.last_modified}" for b in sorted(blobs, key=lambda x: x.name))
        return hashlib.md5(sig.encode()).hexdigest()
    except Exception:
        return "error"

def _local_hash() -> str:
    files = sorted(glob.glob(os.path.join(DATA_FOLDER, "*.xlsx")))
    sig   = "|".join(f"{f}:{os.path.getmtime(f)}" for f in files)
    return hashlib.md5(sig.encode()).hexdigest()


# ── Master loader ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def load_all_data(_hash: str) -> pd.DataFrame:
    dfs = []

    if IS_AZURE:
        # ── Azure mode: read from Blob Storage ──
        client = _get_blob_client()
        for name in list_blobs():
            try:
                blob_data = client.get_blob_client(BLOB_CONTAINER, name).download_blob().readall()
                dfs.append(_process_file(io.BytesIO(blob_data)))
            except Exception as e:
                st.warning(f"⚠️ Could not read blob {name}: {e}")
    else:
        # ── Local mode: read from disk folder ──
        for path in glob.glob(os.path.join(DATA_FOLDER, "*.xlsx")):
            try:
                dfs.append(_process_file(path))
            except Exception as e:
                st.warning(f"⚠️ Could not read {os.path.basename(path)}: {e}")

    if not dfs:
        return pd.DataFrame(columns=COLS)

    out = pd.concat(dfs, ignore_index=True)
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce").fillna(0)
    return out


def get_data():
    h  = _blob_hash() if IS_AZURE else _local_hash()
    df = load_all_data(h)
    return df, h
