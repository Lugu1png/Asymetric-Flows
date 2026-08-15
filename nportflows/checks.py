"""Step 4: data-quality report -> reports/data_quality.md (+ CSVs).

Each check prints a value and, where there is a defensible expectation, PASS/WARN.
WARN means "look at this before running regressions", not "the data are wrong".

Usage:  python -m nportflows.checks
"""
import json

import numpy as np
import pandas as pd

from . import config as C
from .io import load, load_all_quarters

lines = []


def h(t):
    lines.append(f"\n## {t}\n")


def item(name, value, ok=None):
    tag = "" if ok is None else (" — PASS" if ok else " — **WARN**")
    lines.append(f"- {name}: {value}{tag}")


def q(s, ps=(0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)):
    return ", ".join(f"p{int(p*100)}={v:.4g}" for p, v in s.quantile(list(ps)).items())


def main():
    p = load(C.PROCESSED / "panel")
    f = load(C.PROCESSED / "filings")
    p["month"] = pd.to_datetime(p["month"])
    e = p[p["eligible"]]
    bond = p[p["bond_type"].isin(C.BOND_TYPES) & p["in_sample"]]
    lines.append("# N-PORT panel: data-quality report\n")

    h("Pipeline stages")
    stages = json.loads((C.REPORTS / "build_stages.json").read_text())
    for k, v in stages.items():
        item(k, f"{v:,}")
    try:
        log = pd.read_csv(C.REPORTS / "extract_log.csv")
        bad = int(log["bad_accession_rows"].sum())
        item("rows with malformed ACCESSION_NUMBER (parse corruption)", bad, bad == 0)
        if "dropped_rows" in log:
            dr = int(log["dropped_rows"].fillna(0).clip(lower=0).sum())
            item("raw lines rejected by the TSV parser (lost rows)", f"{dr:,}", dr == 0)
        if "missing_cols" in log:
            miss = log[log["missing_cols"].fillna("").ne("")]
            item("expected columns missing from a quarter's file",
                 "none" if miss.empty else "; ".join(f"{r.quarter} {r.table}: {r.missing_cols}"
                                                     for r in miss.itertuples()), miss.empty)
    except FileNotFoundError:
        pass

    h("Keys and coverage")
    item("(SERIES_ID, month) unique", not p.duplicated(["SERIES_ID", "month"]).any(),
         not p.duplicated(["SERIES_ID", "month"]).any())
    cov = (p[p["in_sample"]].groupby("month")
             .agg(series=("SERIES_ID", "nunique"),
                  bond_series=("bond_type", lambda s: s.isin(C.BOND_TYPES).sum()),
                  eligible=("eligible", "sum")))
    cov.to_csv(C.REPORTS / "coverage_by_month.csv")
    jump = cov["series"].pct_change().abs().max()
    item("max month-on-month change in #series", f"{jump:.1%} (phase-in of smaller fund groups or "
         "missing filings show up here; inspect coverage_by_month.csv)", jump < 0.10)
    item("bond-type counts (series)", p.drop_duplicates("SERIES_ID")["bond_type"].value_counts().to_dict())
    item("classification source (series)",
         p.drop_duplicates("SERIES_ID")["cls_source"].value_counts(dropna=False).to_dict())

    item("series flagged as ETF by name (excluded from eligible)" if C.EXCLUDE_ETF_NAME
         else "series flagged as ETF by name", int(p.loc[p["flag_etf_name"], "SERIES_ID"].nunique()))

    h("Returns (units, class aggregation)")
    try:
        bm = json.loads((C.REPORTS / "build_meta.json").read_text())
        item("return units used", f"{'percent' if bm['returns_in_percent'] else 'decimals'} "
             f"({bm['returns_units_source']}; median |raw value| = {bm['returns_median_abs_raw']:.4g})")
        item("sample", f"{C.SAMPLE_START} to {bm['sample_end']} (SAMPLE_END={C.SAMPLE_END})")
    except FileNotFoundError:
        pass
    med = bond["ret"].abs().median()
    item("median |monthly return|, bond funds", f"{med:.4f}  (expect ~0.002-0.01 in decimals; "
         "~100x larger means RETURNS_IN_PERCENT is wrong)", 0.0005 < med < 0.03)
    big = bond["flag_extreme_ret"].mean()
    item(f"share bond fund-months with |return| > {C.EXTREME_RET:.0%} (lagged ones not eligible)",
         f"{big:.4%}", big < 0.002)
    sp = bond["ret_class_spread"].dropna()
    item("class return spread (max-min) within fund", q(sp))
    item("share with raw class spread > 1pp (misreported class?)", f"{(sp > 0.01).mean():.3%}")
    multi = bond["n_classes"] >= 2
    item(f"fund-months where outlier classes (> {C.CLASS_OUTLIER:.1%} from class median) were dropped",
         f"{bond.loc[multi, 'flag_class_outlier'].mean():.3%} of multi-class fund-months")
    conflict = bond["ret"].isna() & bond["ret_all_classes"].notna()
    item("fund-months with return set to missing (classes disagree, no majority)",
         f"{conflict.mean():.3%}", conflict.mean() < 0.01)
    rest = bond["ret"].notna() & bond["ret_all_classes"].notna()
    diff = (bond.loc[rest, "ret"] - bond.loc[rest, "ret_all_classes"]).abs()
    item("|fund return change| from dropping outlier classes, where it changed",
         q(diff[diff > 1e-12]) if (diff > 1e-12).any() else "none")
    item("share bond fund-months with missing return", f"{bond['ret'].isna().mean():.3%}")

    h("Net assets: accounting closure (anchored reconstruction vs reported NA)")
    fb = f[f["SERIES_ID"].isin(bond["SERIES_ID"].unique())]
    ce = fb["closure_err"].replace([np.inf, -np.inf], np.nan).dropna()
    item("filings with closure check", f"{len(ce):,} of {len(fb):,} bond filings "
         f"(rest have no filing 1-3 months earlier -> backward method)")
    item("|closure error| before distribution adjustment", q(ce.abs()))
    within = (ce.abs() < 0.01).mean()
    item("share with |closure error| < 1%", f"{within:.1%}", within > 0.9)
    large = (ce.abs() > C.BRIDGE_MAX_CLOSURE).mean()
    item(f"share with |closure error| > {C.BRIDGE_MAX_CLOSURE:.0%} (not bridged; mergers? errors?)",
         f"{large:.1%}", large < 0.02)
    dr = fb.loc[fb["dist_src"].eq("bridged"), "dist_rate"]
    item("implied monthly cash-distribution leakage d (bridged filings)", q(dr) + "  (bond funds: "
         "expect roughly 0 to 0.004; large |d| means flows or returns do not add up)")
    item("source of d (bond filings)", fb["dist_src"].value_counts().to_dict())
    lo, hi = C.DIST_RATE_BOUNDS
    bad = fb["flag_bad_na"].mean()
    item(f"bond filings with flag_bad_na (not bridged, or d outside [{lo}, {hi}])",
         f"{bad:.1%}" + (" (excluded from eligible)" if C.EXCLUDE_BAD_NA else ""), bad < 0.05)
    item("NA method (bond fund-months)", bond["na_method"].value_counts().to_dict())
    item("non-positive / missing lagged NA (bond)", f"{bond['flag_bad_na_lag'].mean():.3%}")

    h("Flows")
    item("flow, eligible obs", q(e["flow"]))
    item("flow incl. reinvestment, eligible obs", q(e["flow_incl_reinv"]))
    xf = e["flag_extreme_flow"].mean()
    item(f"share eligible with |flow| > {C.EXTREME_FLOW:.0%}", f"{xf:.3%} (mergers, launches, "
         "liquidations, reporting errors: inspect before winsorising)", xf < 0.005)
    neg = ((p["sales"] < 0) | (p["redemp"] < 0)).mean()
    item("share with negative sales or redemptions (redemptions already made positive)",
         f"{neg:.4%}", neg < 0.005)
    item("series flagged no flow activity (closed-end-like)",
         int(p.loc[p["flag_no_flow_activity"], "SERIES_ID"].nunique()))
    item("eligible obs in a last-filing month", int(e["flag_last_filing"].sum()))
    e.nlargest(25, "flow")[["SERIES_ID", "SERIES_NAME", "month", "flow", "na_lag", "sales", "redemp"]] \
        .to_csv(C.REPORTS / "top_inflows.csv", index=False)
    e.nsmallest(25, "flow")[["SERIES_ID", "SERIES_NAME", "month", "flow", "na_lag", "sales", "redemp"]] \
        .to_csv(C.REPORTS / "top_outflows.csv", index=False)

    h("Timing")
    item("share bond in-sample obs with lagged return available", f"{bond['ret_lag'].notna().mean():.1%}")
    item("lagged return = own return of calendar month t-1 (by construction: merge on month+1)", "yes")

    h("Holdings composition")
    comp = f.merge(load_all_quarters(C.INTERIM, "composition"), on="ACCESSION_NUMBER")
    pa = comp["pct_all"]
    item("sum of PERCENTAGE per filing", q(pa))
    out = ((pa < 90) | (pa > 110)).mean()
    item("share filings with holdings summing outside 90-110% of NA", f"{out:.1%} "
         "(leverage, shorts and derivatives make some of this legitimate)", out < 0.2)
    codes = load_all_quarters(C.INTERIM, "codes").groupby(["field", "code"])["n"].sum().reset_index()
    codes.sort_values(["field", "n"], ascending=[True, False]).to_csv(C.REPORTS / "code_frequencies.csv", index=False)
    known = C.DEBT_CATS | C.CASH_CATS | C.EQUITY_CATS | C.DERIV_CATS
    ac = codes[codes["field"] == "ASSET_CAT"]
    unk = ac.loc[~ac["code"].isin(known), "n"].sum() / ac["n"].sum()
    top = ac.loc[~ac["code"].isin(known)].nlargest(8, "n")
    item("share of holdings with ASSET_CAT outside debt/cash/equity/derivative lists", f"{unk:.1%}; top: "
         + ", ".join(f"{c} ({n:,})" for c, n in zip(top["code"], top["n"]))
         + " — confirm none of these is a debt category missing from DEBT_CATS")

    h("External validation (do this by hand)")
    agg = (e.assign(net=e["sales"] - e["redemp"]).groupby(["month", "bond_type"])["net"].sum()
             .unstack().div(1e9))
    agg.to_csv(C.REPORTS / "aggregate_net_flows_bn.csv")
    item("aggregate bond-fund net flows by month ($bn)", "reports/aggregate_net_flows_bn.csv — compare "
         "with ICI monthly bond-fund flows; 2022 should show large, persistent outflows")

    (C.REPORTS / "data_quality.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
