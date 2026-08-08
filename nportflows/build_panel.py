"""Step 3: build the fund(series)-month panel of flows, returns and net assets.

Key facts about the public N-PORT data that drive the design (see README):
  * Only the filing for the 3rd month of each FISCAL quarter is public. It carries
    flows (Item B.6) and class returns (Item B.5) for each of the 3 months, but net
    assets (B.1.c) only at REPORT_DATE (end of month 3).
  * Month k of a filing is calendar month  REPORT_DATE month - (3 - k).
  * Returns are per share class; flows and net assets are per series (= fund).
    Class net assets are not reported, so class returns are equal-weighted.
  * Amendments (NPORT-P/A) restate earlier filings and can sit in later zips.

Usage:  python -m nportflows.build_panel
"""
import json

import numpy as np
import pandas as pd

from . import config as C
from .io import load_all_quarters, save

MON = (1, 2, 3)
stages = {}


def stage(name, n):
    stages[name] = int(n)
    print(f"  {name:<55} {n:>10,}")


def parse_date(s: pd.Series) -> pd.Series:
    """Accept ISO and Oracle-style (30-SEP-2019) dates; anything else -> NaT, counted."""
    s = s.astype("string").str.strip()
    out = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    for fmt in ("%d-%b-%Y", "%m/%d/%Y"):
        m = out.isna() & s.notna()
        if m.any():
            out[m] = pd.to_datetime(s[m].str.title(), format=fmt, errors="coerce")
    return out


def num(df, cols):
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ---------------------------------------------------------------------------
def load_filings():
    sub = load_all_quarters(C.INTERIM, "submission").drop_duplicates("ACCESSION_NUMBER")
    stage("submissions (all types)", len(sub))
    sub["SUB_TYPE"] = sub["SUB_TYPE"].str.upper().str.strip()
    sub = sub[sub["SUB_TYPE"].isin(["NPORT-P", "NPORT-P/A"])].copy()
    stage("submissions NPORT-P or NPORT-P/A", len(sub))
    sub["filing_date"] = parse_date(sub["FILING_DATE"])
    sub["report_date"] = parse_date(sub["REPORT_DATE"])
    stage("  unparseable REPORT_DATE", sub["report_date"].isna().sum())

    fri = load_all_quarters(C.INTERIM, "fund_info").drop_duplicates("ACCESSION_NUMBER")
    reg = load_all_quarters(C.INTERIM, "registrant").drop_duplicates("ACCESSION_NUMBER")
    f = (fri.drop(columns="src_q")
            .merge(sub.drop(columns="src_q"), on="ACCESSION_NUMBER", how="inner")
            .merge(reg[["ACCESSION_NUMBER", "CIK", "REGISTRANT_NAME"]], on="ACCESSION_NUMBER", how="left"))
    flow_cols = [f"{p}_FLOW_MON{k}" for k in MON for p in ("SALES", "REINVESTMENT", "REDEMPTION")]
    f = num(f, ["NET_ASSETS", "TOTAL_ASSETS"] + flow_cols)
    f = f[f["SERIES_ID"].notna() & f["report_date"].notna()].copy()
    stage("filings with SERIES_ID and REPORT_DATE", len(f))
    f["rmonth"] = f["report_date"].dt.to_period("M")

    # Amendments: keep the latest filing per series and report month.
    f = f.sort_values(["SERIES_ID", "rmonth", "filing_date", "ACCESSION_NUMBER"])
    dup = f.duplicated(["SERIES_ID", "rmonth"], keep="last")
    stage("  superseded by a later filing (amendments)", dup.sum())
    f = f[~dup].copy()
    stage("filings after de-duplication", len(f))
    return f


def class_returns(f):
    r = load_all_quarters(C.INTERIM, "returns")
    r = r[r["ACCESSION_NUMBER"].isin(f["ACCESSION_NUMBER"])].copy()
    scale = 100.0 if C.RETURNS_IN_PERCENT else 1.0
    for k in MON:
        r[f"r{k}"] = pd.to_numeric(r[f"MONTHLY_TOTAL_RETURN{k}"], errors="coerce") / scale
    g = r.groupby("ACCESSION_NUMBER")
    out = g.agg(n_classes=("CLASS_ID", "size"))
    for k in MON:
        out[f"ret_ew_{k}"] = g[f"r{k}"].mean()        # primary: equal-weighted across classes
        out[f"ret_med_{k}"] = g[f"r{k}"].median()
        out[f"ret_spread_{k}"] = g[f"r{k}"].max() - g[f"r{k}"].min()
    return out.reset_index()


def reconstruct_net_assets(f):
    """Net assets are reported only at month 3. Lagged NA for months 1-3 is rebuilt from
    the accounting identity  NA_m = NA_{m-1}(1+r_m) - D_m + S_m + RI_m - R_m,
    assuming cash distributions D_m equal reinvested distributions RI_m (both unreported/
    partly reported), i.e.  NA_m = NA_{m-1}(1+r_m) + S_m - R_m.
    Forward from the previous filing's reported NA (no future information) when that
    filing exists exactly 3 months earlier; backward from this filing's NA otherwise.
    The forward path ends at a month-3 value we can compare with the reported one:
    that 'closure error' is the main consistency check on units, timing and returns."""
    prev = f[["SERIES_ID", "rmonth", "NET_ASSETS"]].rename(columns={"NET_ASSETS": "na_prev_rep"})
    prev["rmonth"] = prev["rmonth"] + 3
    f = f.merge(prev, on=["SERIES_ID", "rmonth"], how="left")
    S = {k: f[f"SALES_FLOW_MON{k}"] for k in MON}
    R = {k: f[f"REDEMPTION_FLOW_MON{k}"] for k in MON}
    r = {k: f[f"ret_ew_{k}"] for k in MON}

    fwd = {0: f["na_prev_rep"]}
    for k in MON:
        fwd[k] = fwd[k - 1] * (1 + r[k]) + S[k] - R[k]
    bwd = {3: f["NET_ASSETS"]}
    for k in (3, 2, 1):
        bwd[k - 1] = (bwd[k] - S[k] + R[k]) / (1 + r[k])

    f["closure_err"] = fwd[3] / f["NET_ASSETS"] - 1
    use_fwd = f["na_prev_rep"].notna()
    for k in MON:
        f[f"na_lag_{k}"] = np.where(use_fwd, fwd[k - 1], bwd[k - 1])
        f[f"na_end_{k}"] = f["NET_ASSETS"] if k == 3 else np.where(use_fwd, fwd[k], bwd[k])
    f["na_method"] = np.where(use_fwd, "forward", "backward")
    return f


def to_long(f):
    keep = ["SERIES_ID", "SERIES_NAME", "CIK", "REGISTRANT_NAME", "ACCESSION_NUMBER",
            "filing_date", "rmonth", "IS_LAST_FILING", "n_classes", "closure_err", "na_method"]
    parts = []
    for k in MON:
        d = f[keep].copy()
        d["month"] = f["rmonth"] - (3 - k)
        d["mon_in_filing"] = k
        d["sales"] = f[f"SALES_FLOW_MON{k}"]
        d["reinvest"] = f[f"REINVESTMENT_FLOW_MON{k}"]
        d["redemp"] = f[f"REDEMPTION_FLOW_MON{k}"]
        d["ret"] = f[f"ret_ew_{k}"]
        d["ret_med"] = f[f"ret_med_{k}"]
        d["ret_class_spread"] = f[f"ret_spread_{k}"]
        d["na_lag"] = f[f"na_lag_{k}"]
        d["na_end"] = f[f"na_end_{k}"]
        parts.append(d)
    p = pd.concat(parts, ignore_index=True)
    # A month can appear in two filings (fiscal-year change; monthly public filing in future).
    p = p.sort_values(["SERIES_ID", "month", "filing_date", "ACCESSION_NUMBER"])
    dup = p.duplicated(["SERIES_ID", "month"], keep="last")
    stage("series-months covered by >1 filing (kept latest)", dup.sum())
    return p[~dup].copy()


def classify(f):
    comp = load_all_quarters(C.INTERIM, "composition").drop(columns="src_q")
    c = f[["ACCESSION_NUMBER", "SERIES_ID", "report_date"]].merge(comp, on="ACCESSION_NUMBER")
    debt = c["pct_debt"].replace(0, np.nan)
    c["gov_share"] = c["pct_gov"] / debt
    c["muni_share"] = c["pct_muni"] / debt
    c["corp_share"] = c["pct_corp"] / debt
    # No look-ahead into the tightening: classify on holdings up to CLASSIFY_CUTOFF.
    # Funds first seen after the cutoff use their first filing only (flagged).
    c["pre"] = c["report_date"] <= pd.Timestamp(C.CLASSIFY_CUTOFF)
    has_pre = c.groupby("SERIES_ID")["pre"].transform("any")
    first = c["report_date"].eq(c.groupby("SERIES_ID")["report_date"].transform("min"))
    use = (has_pre & c["pre"]) | (~has_pre & first)
    cols = ["pct_all", "pct_debt", "pct_equity", "gov_share", "muni_share", "corp_share"]
    cl = c[use].groupby("SERIES_ID")[cols].median().add_prefix("cls_")
    src = has_pre[use].groupby(c.loc[use, "SERIES_ID"]).first().reindex(cl.index)
    cl["cls_source"] = np.where(src, "median_pre_cutoff", "first_filing_post_cutoff")
    cl["is_bond"] = (cl["cls_pct_debt"] >= C.BOND_MIN_DEBT_PCT) & (cl["cls_pct_equity"] <= C.BOND_MAX_EQUITY_PCT)
    t = C.SUBTYPE_MIN_SHARE
    cl["bond_type"] = np.select(
        [~cl["is_bond"], cl["cls_muni_share"] >= t, cl["cls_gov_share"] >= t, cl["cls_corp_share"] >= t],
        ["not_bond", "muni", "gov", "corp"], default="mixed")
    return cl.reset_index()


def main():
    print("Building panel")
    f = load_filings()
    f = f.merge(class_returns(f), on="ACCESSION_NUMBER", how="left")
    stage("filings with no class returns", f["n_classes"].isna().sum())
    f = reconstruct_net_assets(f)
    save(f, C.PROCESSED / "filings")

    p = to_long(f)
    p["flow"] = (p["sales"] - p["redemp"]) / p["na_lag"]                      # primary
    p["flow_incl_reinv"] = (p["sales"] + p["reinvest"] - p["redemp"]) / p["na_lag"]

    p = p.merge(classify(f), on="SERIES_ID", how="left")
    p["bond_type"] = p["bond_type"].fillna("unclassified")

    # Category-adjusted return: own return minus leave-one-out mean of same bond type & month.
    ok = p["ret"].notna() & p["bond_type"].isin(["gov", "corp", "muni", "mixed"])
    g = p[ok].groupby(["bond_type", "month"])["ret"]
    s, n = g.transform("sum"), g.transform("count")
    p.loc[ok, "ret_rel"] = np.where(n > 1, p.loc[ok, "ret"] - (s - p.loc[ok, "ret"]) / (n - 1), np.nan)

    # Lags by CALENDAR month (a row shift would misalign across gaps between filings).
    lag = p[["SERIES_ID", "month", "ret", "ret_rel", "flow"]].copy()
    lag["month"] = lag["month"] + 1
    p = p.merge(lag.rename(columns={"ret": "ret_lag", "ret_rel": "ret_rel_lag", "flow": "flow_lag"}),
                on=["SERIES_ID", "month"], how="left")

    # Flags (filters are applied in the regression step, not here).
    mi = p["month"].dt.year * 12 + p["month"].dt.month
    p["months_observed"] = mi - mi.groupby(p["SERIES_ID"]).transform("min")
    activity = p.groupby("SERIES_ID")[["sales", "redemp"]].transform("sum").sum(axis=1)
    p["flag_no_flow_activity"] = activity.eq(0)          # likely closed-end / non-redeemable
    p["flag_last_filing"] = p["IS_LAST_FILING"].astype("string").str.upper().eq("Y")
    p["flag_extreme_flow"] = p["flow"].abs() > C.EXTREME_FLOW
    p["flag_bad_na_lag"] = ~(p["na_lag"] > 0)
    p["size_ok"] = p["na_lag"] >= C.MIN_LAG_NA
    p["size_ok_robust"] = p["na_lag"] >= C.MIN_LAG_NA_ROBUST
    p["in_sample"] = p["month"] >= pd.Period(C.SAMPLE_START, "M")
    p["eligible"] = (p["in_sample"] & p["bond_type"].isin(["gov", "corp", "muni", "mixed"])
                     & p["size_ok"] & ~p["flag_no_flow_activity"] & ~p["flag_bad_na_lag"]
                     & p["flow"].notna() & p["ret_lag"].notna())

    assert not p.duplicated(["SERIES_ID", "month"]).any(), "panel key not unique"
    p["month"] = p["month"].dt.to_timestamp()            # storage-friendly
    p = p.sort_values(["SERIES_ID", "month"]).reset_index(drop=True)
    stage("panel series-months (all funds)", len(p))
    stage("panel series-months eligible (bond, size, lagged ret)", p["eligible"].sum())
    stage("bond funds eligible in >= 1 month", p.loc[p["eligible"], "SERIES_ID"].nunique())
    save(p, C.PROCESSED / "panel")
    C.REPORTS.mkdir(parents=True, exist_ok=True)
    (C.REPORTS / "build_stages.json").write_text(json.dumps(stages, indent=2))


if __name__ == "__main__":
    main()
