"""Step 3: build the fund(series)-month panel of flows, returns and net assets.

Key facts about the public N-PORT data that drive the design (see README):
  * Only the filing for the 3rd month of each FISCAL quarter is public (monthly public
    filing is being phased in). A filing carries flows (Item B.6) and class returns
    (Item B.5) for each of its 3 months, but net assets (B.1.c) only at REPORT_DATE.
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
meta = {}


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


def month_index(per: pd.Series) -> pd.Series:
    return per.dt.year * 12 + per.dt.month


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
    stage("  unparseable FILING_DATE (treated as oldest)", sub["filing_date"].isna().sum())

    fri = load_all_quarters(C.INTERIM, "fund_info").drop_duplicates("ACCESSION_NUMBER")
    reg = load_all_quarters(C.INTERIM, "registrant").drop_duplicates("ACCESSION_NUMBER")
    f = (fri.drop(columns="src_q")
            .merge(sub.drop(columns="src_q"), on="ACCESSION_NUMBER", how="inner")
            .merge(reg[["ACCESSION_NUMBER", "CIK", "REGISTRANT_NAME"]], on="ACCESSION_NUMBER", how="left"))
    flow_cols = [f"{p}_FLOW_MON{k}" for k in MON for p in ("SALES", "REINVESTMENT", "REDEMPTION")]
    f = num(f, ["NET_ASSETS", "TOTAL_ASSETS"] + flow_cols)
    f = f[f["SERIES_ID"].notna() & f["report_date"].notna()].copy()
    stage("filings with SERIES_ID and REPORT_DATE", len(f))
    # Sign convention varies by filer: about a quarter of series report redemptions as
    # negative numbers. Redemptions are outflows by definition, so use their magnitude.
    red_cols = [f"REDEMPTION_FLOW_MON{k}" for k in MON]
    stage("  filings reporting redemptions as negatives (made positive)",
          (f[red_cols] < 0).any(axis=1).sum())
    f[red_cols] = f[red_cols].abs()
    f["rmonth"] = f["report_date"].dt.to_period("M")

    # Amendments: keep the latest filing per series and report month. An unparseable
    # filing date sorts first, so it never overrides a dated filing.
    f = f.sort_values(["SERIES_ID", "rmonth", "filing_date", "ACCESSION_NUMBER"], na_position="first")
    dup = f.duplicated(["SERIES_ID", "rmonth"], keep="last")
    stage("  superseded by a later filing (amendments)", dup.sum())
    f = f[~dup].copy()
    stage("filings after de-duplication", len(f))
    return f


def class_returns(f):
    r = load_all_quarters(C.INTERIM, "returns")
    r = r[r["ACCESSION_NUMBER"].isin(f["ACCESSION_NUMBER"])].copy()
    raw = {k: pd.to_numeric(r[f"MONTHLY_TOTAL_RETURN{k}"], errors="coerce") for k in MON}
    med = float(pd.concat(raw.values()).abs().median())
    looks_pct = med > 0.1     # percent: ~0.3-4; decimals: ~0.003-0.04
    if C.RETURNS_IN_PERCENT == "auto":
        in_pct = looks_pct
    else:
        in_pct = bool(C.RETURNS_IN_PERCENT)
        if in_pct != looks_pct:
            print(f"  WARNING: RETURNS_IN_PERCENT={C.RETURNS_IN_PERCENT} but median |raw return| "
                  f"is {med:.4g}, which looks like {'percent' if looks_pct else 'decimals'}")
    meta.update(returns_median_abs_raw=med, returns_in_percent=in_pct,
                returns_units_source="auto" if C.RETURNS_IN_PERCENT == "auto" else "config")
    print(f"  returns treated as {'percent' if in_pct else 'decimals'} (median |raw| = {med:.4g})")
    scale = 100.0 if in_pct else 1.0
    for k in MON:
        r[f"r{k}"] = raw[k] / scale
    g = r.groupby("ACCESSION_NUMBER")
    out = g.agg(n_classes=("CLASS_ID", "size"))
    for k in MON:
        rk = r[f"r{k}"]
        med = g[f"r{k}"].transform("median")
        keep = (rk - med).abs() <= C.CLASS_OUTLIER
        gk = rk.where(keep).groupby(r["ACCESSION_NUMBER"])
        out[f"ret_ew_{k}"] = gk.mean()                   # primary: equal-weighted, outlier classes out
        out[f"ret_ew_all_{k}"] = g[f"r{k}"].mean()       # all classes (previous definition)
        out[f"ret_med_{k}"] = g[f"r{k}"].median()
        out[f"ret_spread_{k}"] = g[f"r{k}"].max() - g[f"r{k}"].min()
        out[f"n_cls_dropped_{k}"] = (rk.notna() & ~keep).groupby(r["ACCESSION_NUMBER"]).sum()
    return out.reset_index()


def na_path(S, R, r, j, anchor, d):
    """Net assets at month-ends 0..3 of each filing (0 = end of the month before month 1),
    given a known value `anchor` at month-end j (per row; NaN j = no anchor). Months after
    j are rolled forward, months before it backward, with
        NA_m = NA_{m-1} (1 + r_m - d) + S_m - R_m."""
    na = {k: anchor.where(j == k) for k in range(4)}
    for k in MON:
        na[k] = na[k].where(~(j < k), na[k - 1] * (1 + r[k] - d) + S[k] - R[k])
    for k in (3, 2, 1):
        na[k - 1] = na[k - 1].where(~(j >= k), (na[k] - S[k] + R[k]) / (1 + r[k] - d))
    return na


def reconstruct_net_assets(f):
    """Net assets are reported only at month 3, so lagged NA for months 1-3 is rebuilt from
        NA_m = NA_{m-1}(1+r_m) - D_m + S_m + RI_m - R_m.
    Cash distributions D_m are not reported. They enter as a leakage rate d = (D-RI)/NA_{m-1}:
        NA_m = NA_{m-1}(1 + r_m - d) + S_m - R_m.

    Anchored path (preferred, no future information for the first lag): start from the
    previous filing's reported NA, which sits at month-end j = 3 - gap of this filing when
    the previous filing is 1-3 months earlier (3 = quarterly, 1 = monthly public filing).
    The unadjusted (d = 0) anchored path ends at a month-3 value we can compare with the
    reported one: that 'closure error' is the main check on units, timing and returns.
    If it is within BRIDGE_MAX_CLOSURE, d is solved so the path closes exactly ('bridged').
    Otherwise d = the series' median bridged d (0 if none).

    Backward path (fallback, per month): from this filing's reported NA with the same d,
    used for any month where the anchored path is missing (no usable previous filing, or a
    missing flow/return breaks the forward chain)."""
    f = f.sort_values(["SERIES_ID", "rmonth"]).reset_index(drop=True)
    mi = month_index(f["rmonth"])
    gap = mi - mi.groupby(f["SERIES_ID"]).shift()
    prev_na = f.groupby("SERIES_ID")["NET_ASSETS"].shift()
    j_prev = (3 - gap).where(gap.between(1, 3) & prev_na.notna())
    j_rep = pd.Series(3.0, index=f.index)
    na3 = f["NET_ASSETS"]
    S = {k: f[f"SALES_FLOW_MON{k}"] for k in MON}
    R = {k: f[f"REDEMPTION_FLOW_MON{k}"] for k in MON}
    r = {k: f[f"ret_ew_{k}"] for k in MON}
    f["prev_gap"] = gap

    raw = na_path(S, R, r, j_prev, prev_na, 0.0)
    f["closure_err"] = raw[3] / na3 - 1
    f["flag_large_closure"] = f["closure_err"].abs() > C.BRIDGE_MAX_CLOSURE
    can_bridge = na3.gt(0) & (f["closure_err"].abs() <= C.BRIDGE_MAX_CLOSURE)

    # Newton steps on d (NA_3 is a polynomial of degree <= 3 in d).
    d, h = pd.Series(0.0, index=f.index), 1e-6
    for _ in range(8):
        e0 = na_path(S, R, r, j_prev, prev_na, d)[3] - na3
        e1 = na_path(S, R, r, j_prev, prev_na, d + h)[3] - na3
        d = d - e0 / ((e1 - e0) / h)
    d_bridge = d.where(can_bridge & np.isfinite(d))
    d_series = d_bridge.groupby(f["SERIES_ID"]).transform("median")
    d_use = d_bridge.fillna(d_series).fillna(0.0)
    f["dist_rate"] = d_use
    f["dist_src"] = np.select([d_bridge.notna(), d_series.notna()], ["bridged", "series_median"], "none")
    lo, hi = C.DIST_RATE_BOUNDS
    f["flag_bad_na"] = f["flag_large_closure"] | ~d_use.between(lo, hi)

    A = na_path(S, R, r, j_prev, prev_na, d_use)
    B = na_path(S, R, r, j_rep, na3, d_use)
    for k in MON:
        a, b = A[k - 1], B[k - 1]
        f[f"na_lag_{k}"] = a.fillna(b)
        f[f"na_end_{k}"] = na3 if k == 3 else A[k].fillna(B[k])
        f[f"na_method_{k}"] = np.select([a.notna() & d_bridge.notna(), a.notna(), b.notna()],
                                        ["bridged", "anchored", "backward"], "none")
    return f


def to_long(f):
    keep = ["SERIES_ID", "SERIES_NAME", "CIK", "REGISTRANT_NAME", "ACCESSION_NUMBER",
            "filing_date", "rmonth", "IS_LAST_FILING", "n_classes", "closure_err",
            "flag_large_closure", "flag_bad_na", "dist_rate", "dist_src", "prev_gap"]
    parts = []
    for k in MON:
        d = f[keep].copy()
        d["month"] = f["rmonth"] - (3 - k)
        d["mon_in_filing"] = k
        d["sales"] = f[f"SALES_FLOW_MON{k}"]
        d["reinvest"] = f[f"REINVESTMENT_FLOW_MON{k}"]
        d["redemp"] = f[f"REDEMPTION_FLOW_MON{k}"]
        d["ret"] = f[f"ret_ew_{k}"]
        d["ret_all_classes"] = f[f"ret_ew_all_{k}"]
        d["ret_med"] = f[f"ret_med_{k}"]
        d["n_cls_dropped"] = f[f"n_cls_dropped_{k}"]
        d["ret_class_spread"] = f[f"ret_spread_{k}"]
        d["na_lag"] = f[f"na_lag_{k}"]
        d["na_end"] = f[f"na_end_{k}"]
        d["na_method"] = f[f"na_method_{k}"]
        parts.append(d)
    p = pd.concat(parts, ignore_index=True)
    # A month can appear in several filings (fiscal-year change; monthly public filing).
    # Keep the filing in which it is latest in the quarter (closest to a reported NA);
    # ties (should not happen after amendment de-duplication) go to the latest filing.
    p = p.sort_values(["SERIES_ID", "month", "mon_in_filing", "filing_date", "ACCESSION_NUMBER"],
                      na_position="first")
    dup = p.duplicated(["SERIES_ID", "month"], keep="last")
    stage("series-months covered by >1 filing (kept one)", dup.sum())
    return p[~dup].copy()


def classify(f):
    comp = load_all_quarters(C.INTERIM, "composition").drop(columns="src_q")
    if not {"pct_cash", "pct_sov"} <= set(comp.columns):
        raise SystemExit("Composition tables predate the pct_cash/pct_sov fields: delete "
                         f"{C.INTERIM} and re-run nportflows.extract.")
    c = f[["ACCESSION_NUMBER", "SERIES_ID", "report_date"]].merge(comp, on="ACCESSION_NUMBER")
    debt = c["pct_debt"].replace(0, np.nan)
    for t in ("gov", "sov", "muni", "corp"):
        c[f"{t}_share"] = c[f"pct_{t}"] / debt
    # No look-ahead into the tightening: classify on holdings up to CLASSIFY_CUTOFF.
    # Funds first seen after the cutoff use their first filing only (flagged).
    c["pre"] = c["report_date"] <= pd.Timestamp(C.CLASSIFY_CUTOFF)
    has_pre = c.groupby("SERIES_ID")["pre"].transform("any")
    first = c["report_date"].eq(c.groupby("SERIES_ID")["report_date"].transform("min"))
    use = (has_pre & c["pre"]) | (~has_pre & first)
    cols = ["pct_all", "pct_debt", "pct_cash", "pct_equity",
            "gov_share", "sov_share", "muni_share", "corp_share"]
    cl = c[use].groupby("SERIES_ID")[cols].median().add_prefix("cls_")
    src = has_pre[use].groupby(c.loc[use, "SERIES_ID"]).first().reindex(cl.index)
    cl["cls_source"] = np.where(src, "median_pre_cutoff", "first_filing_post_cutoff")
    cl["is_bond"] = ((cl["cls_pct_debt"] + cl["cls_pct_cash"].fillna(0) >= C.BOND_MIN_DEBT_PCT)
                     & (cl["cls_pct_debt"] >= C.BOND_MIN_DEBT_ONLY_PCT)
                     & (cl["cls_pct_equity"] <= C.BOND_MAX_EQUITY_PCT))
    t = C.SUBTYPE_MIN_SHARE
    cl["bond_type"] = np.select(
        [~cl["is_bond"], cl["cls_muni_share"] >= t, cl["cls_gov_share"] >= t,
         cl["cls_sov_share"] >= t, cl["cls_corp_share"] >= t],
        ["not_bond", "muni", "gov", "sovereign_nonus", "corp"], default="mixed")
    return cl.reset_index()


def sample_end(p):
    """Last month kept: SAMPLE_END, or with "auto" the last month whose number of reporting
    series is at least COVERAGE_MIN_SHARE of the median over the 12 months before it."""
    if C.SAMPLE_END != "auto":
        end = pd.Period(C.SAMPLE_END, "M")
    else:
        cnt = p.groupby("month")["SERIES_ID"].nunique().sort_index()
        ref = cnt.shift(1).rolling(12, min_periods=3).median()
        ok = ~(cnt < C.COVERAGE_MIN_SHARE * ref)          # no reference yet -> ok
        end = ok[ok].index.max()
        stage("months dropped at the end (incomplete filing coverage)", (cnt.index > end).sum())
    meta["sample_end"] = str(end)
    print(f"  sample end: {end}")
    return end


def main():
    print("Building panel")
    f = load_filings()
    f = f.merge(class_returns(f), on="ACCESSION_NUMBER", how="left")
    stage("filings with no class returns", f["n_classes"].isna().sum())
    f = reconstruct_net_assets(f)
    stage("filings with NA bridged to the previous filing", f["dist_src"].eq("bridged").sum())
    stage(f"filings with |closure error| > {C.BRIDGE_MAX_CLOSURE:.0%} (not bridged)",
          f["flag_large_closure"].sum())
    stage("filings with implausible NA reconstruction (flag_bad_na)", f["flag_bad_na"].sum())
    save(f, C.PROCESSED / "filings")

    p = to_long(f)
    p["flow"] = (p["sales"] - p["redemp"]) / p["na_lag"]                      # primary
    p["flow_incl_reinv"] = (p["sales"] + p["reinvest"] - p["redemp"]) / p["na_lag"]

    p = p.merge(classify(f), on="SERIES_ID", how="left")
    p["bond_type"] = p["bond_type"].fillna("unclassified")
    is_bond = p["bond_type"].isin(C.BOND_TYPES)

    # Flags (filters are applied in the regression step, not here).
    etf_name = p["SERIES_NAME"].fillna("").str.contains(C.ETF_NAME_RE, case=False, regex=True)
    p["flag_etf_name"] = etf_name.groupby(p["SERIES_ID"]).transform("any")
    activity = p.groupby("SERIES_ID")[["sales", "redemp"]].transform("sum").sum(axis=1)
    p["flag_no_flow_activity"] = activity.eq(0)          # likely closed-end / non-redeemable
    p["flag_last_filing"] = (p["IS_LAST_FILING"].astype("string").str.strip().str.upper()
                             .isin(C.LAST_FILING_YES).fillna(False).astype(bool))
    p["flag_extreme_flow"] = p["flow"].abs() > C.EXTREME_FLOW
    p["flag_bad_na_lag"] = ~(p["na_lag"] > 0)
    p["size_ok"] = p["na_lag"] >= C.MIN_LAG_NA
    p["size_ok_robust"] = p["na_lag"] >= C.MIN_LAG_NA_ROBUST
    p["flag_extreme_ret"] = p["ret"].abs() > C.EXTREME_RET
    p["flag_class_outlier"] = p["n_cls_dropped"].fillna(0) > 0
    end = sample_end(p)
    p["in_sample"] = p["month"].between(pd.Period(C.SAMPLE_START, "M"), end)
    excl_etf = p["flag_etf_name"] & C.EXCLUDE_ETF_NAME

    # Category-adjusted return: own return minus the mean return of PEERS in the same bond
    # type and month (peers: size_ok, redeemable, not ETF-named, not an extreme return),
    # leaving the fund itself out.
    has_ret = p["ret"].notna() & is_bond
    peer = (has_ret & p["size_ok"] & ~p["flag_no_flow_activity"] & ~excl_etf
            & ~p["flag_extreme_ret"])
    g = p["ret"].where(peer).groupby([p["bond_type"], p["month"]])
    s, n = g.transform("sum"), g.transform("count")
    denom = n - peer.astype(int)
    peer_mean = (s - p["ret"].where(peer, 0.0)) / denom.where(denom > 0)
    p["ret_rel"] = (p["ret"] - peer_mean).where(has_ret)

    # Lags by CALENDAR month (a row shift would misalign across gaps between filings).
    lag = p[["SERIES_ID", "month", "ret", "ret_rel", "flow"]].copy()
    lag["month"] = lag["month"] + 1
    p = p.merge(lag.rename(columns={"ret": "ret_lag", "ret_rel": "ret_rel_lag", "flow": "flow_lag"}),
                on=["SERIES_ID", "month"], how="left")

    mi = month_index(p["month"])
    p["months_observed"] = mi - mi.groupby(p["SERIES_ID"]).transform("min")
    excl_xf = p["flag_extreme_flow"] & C.EXCLUDE_EXTREME_FLOW
    excl_etf = p["flag_etf_name"] & C.EXCLUDE_ETF_NAME
    excl_na = p["flag_bad_na"].fillna(False).astype(bool) & C.EXCLUDE_BAD_NA
    p["eligible"] = (p["in_sample"] & p["bond_type"].isin(C.BOND_TYPES)
                     & p["size_ok"] & ~p["flag_no_flow_activity"] & ~p["flag_bad_na_lag"]
                     & ~excl_etf & ~excl_xf & ~excl_na & p["flow"].notna()
                     & p["ret_lag"].notna() & ~(p["ret_lag"].abs() > C.EXTREME_RET))

    assert not p.duplicated(["SERIES_ID", "month"]).any(), "panel key not unique"
    p["month"] = p["month"].dt.to_timestamp()            # storage-friendly
    p = p.sort_values(["SERIES_ID", "month"]).reset_index(drop=True)
    stage("panel series-months (all funds)", len(p))
    stage("series flagged as ETF by name", p.loc[p["flag_etf_name"], "SERIES_ID"].nunique())
    stage("panel series-months eligible (bond, size, lagged ret)", p["eligible"].sum())
    stage("bond funds eligible in >= 1 month", p.loc[p["eligible"], "SERIES_ID"].nunique())
    save(p, C.PROCESSED / "panel")
    C.REPORTS.mkdir(parents=True, exist_ok=True)
    (C.REPORTS / "build_stages.json").write_text(json.dumps(stages, indent=2))
    (C.REPORTS / "build_meta.json").write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
