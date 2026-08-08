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
    bond = p[p["bond_type"].isin(["gov", "corp", "muni", "mixed"]) & p["in_sample"]]
    lines.append("# N-PORT panel: data-quality report\n")

    h("Pipeline stages")
    stages = json.loads((C.REPORTS / "build_stages.json").read_text())
    for k, v in stages.items():
        item(k, f"{v:,}")
    try:
        log = pd.read_csv(C.REPORTS / "extract_log.csv")
        bad = int(log["bad_accession_rows"].sum())
        item("rows with malformed ACCESSION_NUMBER (parse corruption)", bad, bad == 0)
    except FileNotFoundError:
        pass

    h("Keys and coverage")
    item("(SERIES_ID, month) unique", not p.duplicated(["SERIES_ID", "month"]).any(),
         not p.duplicated(["SERIES_ID", "month"]).any())
    cov = (p[p["in_sample"]].groupby("month")
             .agg(series=("SERIES_ID", "nunique"),
                  bond_series=("bond_type", lambda s: s.isin(["gov", "corp", "muni", "mixed"]).sum()),
                  eligible=("eligible", "sum")))
    cov.to_csv(C.REPORTS / "coverage_by_month.csv")
    jump = cov["series"].pct_change().abs().max()
    item("max month-on-month change in #series", f"{jump:.1%} (phase-in of smaller fund groups or "
         "missing filings show up here; inspect coverage_by_month.csv)", jump < 0.10)
    item("bond-type counts (series)", p.drop_duplicates("SERIES_ID")["bond_type"].value_counts().to_dict())
    item("classification source (series)",
         p.drop_duplicates("SERIES_ID")["cls_source"].value_counts(dropna=False).to_dict())

    h("Returns (units, class aggregation)")
    med = bond["ret"].abs().median()
    item("median |monthly return|, bond funds", f"{med:.4f}  (expect ~0.002-0.01 in decimals; "
         "~100x larger means RETURNS_IN_PERCENT is wrong)", 0.0005 < med < 0.03)
    big = (bond["ret"].abs() > 0.2).mean()
    item("share bond fund-months with |return| > 20%", f"{big:.4%}", big < 0.001)
    sp = bond["ret_class_spread"].dropna()
    item("class return spread (max-min) within fund", q(sp))
    item("share with class spread > 1pp (misreported class?)", f"{(sp > 0.01).mean():.3%}",
         (sp > 0.01).mean() < 0.01)
    item("share bond fund-months with missing return", f"{bond['ret'].isna().mean():.3%}")

    h("Net assets: accounting closure (forward reconstruction vs reported NA)")
    fb = f[f["SERIES_ID"].isin(bond["SERIES_ID"].unique())]
    ce = fb["closure_err"].replace([np.inf, -np.inf], np.nan).dropna()
    item("filings with closure check", f"{len(ce):,} of {len(fb):,} bond filings "
         f"(rest have no filing 3 months earlier -> backward method)")
    item("|closure error| distribution", q(ce.abs()))
    within = (ce.abs() < 0.01).mean()
    item("share with |closure error| < 1%", f"{within:.1%}", within > 0.9)
    item("NA method (bond fund-months)", bond["na_method"].value_counts().to_dict())
    item("non-positive / missing lagged NA (bond)", f"{bond['flag_bad_na_lag'].mean():.3%}")

    h("Flows")
    item("flow, eligible obs", q(e["flow"]))
    item("flow incl. reinvestment, eligible obs", q(e["flow_incl_reinv"]))
    xf = e["flag_extreme_flow"].mean()
    item(f"share eligible with |flow| > {C.EXTREME_FLOW:.0%}", f"{xf:.3%} (mergers, launches, "
         "liquidations, reporting errors: inspect before winsorising)", xf < 0.005)
    neg = ((p["sales"] < 0) | (p["redemp"] < 0)).mean()
    item("share with negative sales or redemptions", f"{neg:.4%}", neg == 0)
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
    known = C.DEBT_CATS | C.EQUITY_CATS | C.DERIV_CATS
    ac = codes[codes["field"] == "ASSET_CAT"]
    unk = ac.loc[~ac["code"].isin(known), "n"].sum() / ac["n"].sum()
    top = ac.loc[~ac["code"].isin(known)].nlargest(8, "n")
    item("share of holdings with ASSET_CAT outside debt/equity/derivative lists", f"{unk:.1%}; top: "
         + ", ".join(f"{c} ({n:,})" for c, n in zip(top["code"], top["n"]))
         + " — confirm none of these is a debt category missing from DEBT_CATS")

    h("External validation (do this by hand)")
    agg = (e.assign(net=e["sales"] - e["redemp"]).groupby(["month", "bond_type"])["net"].sum()
             .unstack().div(1e9))
    agg.to_csv(C.REPORTS / "aggregate_net_flows_bn.csv")
    item("aggregate bond-fund net flows by month ($bn)", "reports/aggregate_net_flows_bn.csv — compare "
         "with ICI monthly bond-fund flows; 2022 should show large, persistent outflows")

    (C.REPORTS / "data_quality.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
