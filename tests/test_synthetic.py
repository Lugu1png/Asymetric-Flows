"""End-to-end test on synthetic N-PORT zips with known true flows and returns.

It writes zips in the documented layout (tab-separated tables, readme field names),
runs extract -> build_panel -> checks, and asserts the panel recovers the truth.
Covers: offset fiscal quarters, multi-class returns, an amendment filed in a later zip,
a closed-end fund, an equity fund, Oracle-style dates, returns in percent, redemptions reported as negatives, cash
distributions that differ from reinvestments (D != RI), a missing filing (gap), a missing
flow and a missing return, a non-US sovereign fund holding repo, and a monthly-filing ETF.

Run:  python tests/test_synthetic.py      (or: pytest tests/)
"""
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
MONTHS = pd.period_range("2019-04", "2021-03", freq="M")
P = lambda s: pd.Period(s, "M")  # noqa: E731
QUARTERLY = {3, 6, 9, 12}

FUNDS = {  # series: report months of filings, n classes, holdings type, has flows, name
    "S000000001": (QUARTERLY, 1, "corp", True, "Fund 1"),
    "S000000002": ({1, 4, 7, 10}, 2, "gov", True, "Fund 2"),   # fiscal year ending January
    "S000000003": (QUARTERLY, 1, "equity", True, "Fund 3"),
    "S000000004": (QUARTERLY, 3, "muni", True, "Fund 4"),      # gets an amendment; one bad class
    "S000000005": (QUARTERLY, 1, "corp", False, "Fund 5"),     # closed-end-like: no sales/redemptions
    "S000000006": (QUARTERLY, 1, "sov", True, "Fund 6"),       # non-US sovereign + repo; gap; missing flow
    "S000000007": (set(range(1, 13)), 1, "corp", True, "Fund 7 Bond ETF"),  # monthly public filer
}
AMEND = ("S000000004", P("2020-06"))
SKIP = {("S000000006", P("2020-09"))}                  # filing never made -> 6-month gap
NO_SALES1 = ("S000000006", P("2020-06"))               # SALES_FLOW_MON1 blank -> flow for 2020-04 unknown
NO_RET2 = ("S000000001", P("2020-03"))                 # MONTHLY_TOTAL_RETURN2 blank -> 2020-02 return unknown
BAD_CLASS = ("S000000004", P("2020-12"), 1, 3)         # class 1 of 3 off by 5pp in month 3 -> dropped
CONFLICT = ("S000000002", P("2020-07"), 1, 2)          # class 1 of 2 off by 3pp in month 2 -> return missing
LEAK = 0.001   # cash distributions net of reinvestment, share of NA per month


def simulate(seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for sid, (_, _, kind, flows, _) in FUNDS.items():
        na = 500e6
        for m in MONTHS:
            r = rng.normal(0.002, 0.01)
            s = na * rng.uniform(0.01, 0.04) if flows else 0.0
            red = na * rng.uniform(0.01, 0.05) if flows else 0.0
            ri = na * 0.002 if flows else 0.0          # reinvested distributions
            dist = ri + na * LEAK                      # paid distributions: D - RI = LEAK * NA
            na_new = na * (1 + r) - dist + s + ri - red
            rows.append(dict(sid=sid, month=m, r=r, sales=s, redemp=red, reinv=ri,
                             na_lag=na, na_end=na_new, flow=(s - red) / na))
            na = na_new
    return pd.DataFrame(rows)


def tsv(df):
    return df.to_csv(sep="\t", index=False, na_rep="")


def build_zips(truth, raw: Path):
    acc_n = [0]
    by_q = {}

    def acc():
        acc_n[0] += 1
        return f"0000000000-20-{acc_n[0]:06d}"

    def add(q, table, row):
        by_q.setdefault(q, {}).setdefault(table, []).append(row)

    hold_by_kind = {"corp": [("DBT", "CORP", 80), ("DBT", "UST", 15), ("STIV", "RF", 5)],
                    "gov": [("DBT", "UST", 60), ("ABS-MBS", "USGSE", 35), ("STIV", "RF", 5)],
                    "muni": [("DBT", "MUN", 97), ("STIV", "RF", 3)],
                    "equity": [("EC", "CORP", 98), ("STIV", "RF", 2)],
                    # debt 62% < 70%, but debt + repo/MMF = 100%: a bond fund; sovereign share 1.0
                    "sov": [("DBT", "NUSS", 62), ("RA", "CORP", 25), ("STIV", "RF", 13)]}

    for sid, (qmonths, ncls, kind, _, name) in FUNDS.items():
        t = truth[truth.sid == sid].set_index("month")
        for m3 in MONTHS:
            if m3.month not in qmonths or m3 - 2 < MONTHS[0] or (sid, m3) in SKIP:
                continue
            versions = [("NPORT-P", 55, 1.0)]
            if (sid, m3) == AMEND:
                versions = [("NPORT-P", 55, 10.0), ("NPORT-P/A", 150, 1.0)]  # wrong, then fixed
            for subtype, lag_days, sales_err in versions:
                fdate = m3.to_timestamp(how="end") + pd.Timedelta(days=lag_days)
                if not (pd.Timestamp("2019-10-01") <= fdate <= pd.Timestamp("2021-06-30")):
                    continue
                q = f"{fdate.year}q{(fdate.month - 1) // 3 + 1}"
                a = acc()
                ms = [m3 - 2, m3 - 1, m3]
                add(q, "SUBMISSION", dict(ACCESSION_NUMBER=a, FILING_DATE=fdate.strftime("%d-%b-%Y").upper(),
                                          FILE_NUM="811-00001", SUB_TYPE=subtype, REPORT_ENDING_PERIOD="",
                                          REPORT_DATE=m3.to_timestamp(how="end").strftime("%d-%b-%Y").upper(),
                                          IS_LAST_FILING="N"))
                add(q, "REGISTRANT", dict(ACCESSION_NUMBER=a, CIK="0000000001", REGISTRANT_NAME='Trust "X"'))
                fri = dict(ACCESSION_NUMBER=a, SERIES_NAME=name, SERIES_ID=sid,
                           SERIES_LEI="", TOTAL_ASSETS=t.loc[m3, "na_end"] * 1.01,
                           TOTAL_LIABILITIES=t.loc[m3, "na_end"] * 0.01, NET_ASSETS=t.loc[m3, "na_end"])
                for k, m in enumerate(ms, 1):
                    fri[f"SALES_FLOW_MON{k}"] = t.loc[m, "sales"] * (sales_err if k == 2 else 1)
                    fri[f"REINVESTMENT_FLOW_MON{k}"] = t.loc[m, "reinv"]
                    # Some filers report redemptions as negative numbers (seen in real data).
                    fri[f"REDEMPTION_FLOW_MON{k}"] = t.loc[m, "redemp"] * (-1 if sid == "S000000002" else 1)
                if (sid, m3) == NO_SALES1:
                    fri["SALES_FLOW_MON1"] = np.nan
                add(q, "FUND_REPORTED_INFO", fri)
                for c in range(ncls):
                    off = (c - (ncls - 1) / 2) * 0.002              # class returns average to fund return
                    row = dict(ACCESSION_NUMBER=a, MONTHLY_TOTAL_RETURN_ID=c, CLASS_ID=f"C{sid[-4:]}{c}")
                    for k, m in enumerate(ms, 1):
                        row[f"MONTHLY_TOTAL_RETURN{k}"] = round(100 * (t.loc[m, "r"] + off), 10)
                    if (sid, m3) == NO_RET2:
                        row["MONTHLY_TOTAL_RETURN2"] = np.nan
                    for bad, err in ((BAD_CLASS, 5.0), (CONFLICT, 3.0)):
                        if (sid, m3, c) == bad[:3]:
                            row[f"MONTHLY_TOTAL_RETURN{bad[3]}"] += err
                    add(q, "MONTHLY_TOTAL_RETURN", row)
                for i, (cat, iss, pct) in enumerate(hold_by_kind[kind]):
                    add(q, "FUND_REPORTED_HOLDING", dict(ACCESSION_NUMBER=a, HOLDING_ID=f"{a}{i}",
                        ISSUER_NAME='Issuer "quoted" name', PERCENTAGE=pct, PAYOFF_PROFILE="Long",
                        ASSET_CAT=cat, ISSUER_TYPE=iss, DERIVATIVE_CAT=""))
                add(q, "FUND_REPORTED_HOLDING", dict(ACCESSION_NUMBER=a, HOLDING_ID=f"{a}d",
                    ISSUER_NAME="Swap", PERCENTAGE=0.3, PAYOFF_PROFILE="N/A", ASSET_CAT="DIR",
                    ISSUER_TYPE="CORP", DERIVATIVE_CAT="SWP"))
    raw.mkdir(parents=True, exist_ok=True)
    for q, tables in by_q.items():
        with zipfile.ZipFile(raw / f"{q}_nport.zip", "w", zipfile.ZIP_DEFLATED) as zf:
            for name, rows in tables.items():
                zf.writestr(f"{q}_nport/{name}.tsv", tsv(pd.DataFrame(rows)))
    return sorted(by_q)


def run(mod, env, *args):
    r = subprocess.run([sys.executable, "-m", f"nportflows.{mod}", *args], cwd=REPO, env=env,
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise RuntimeError(f"{mod} failed")
    return r.stdout


def test_end_to_end():
    truth = simulate()
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "NPORT_ROOT": d, "PYTHONPATH": str(REPO)}
        qs = build_zips(truth, Path(d) / "data" / "raw")
        print("synthetic quarters:", qs)
        out = run("run", env, "--skip-download")
        print(out[-2500:])
        assert "Done. Report" in out
        again = run("run", env, "--skip-download")
        assert "No new data" in again and "Building panel" not in again, again
        sys.path.insert(0, str(REPO))
        os.environ["NPORT_ROOT"] = d
        from nportflows.io import load
        p = load(Path(d) / "data" / "processed" / "panel")
        f = load(Path(d) / "data" / "processed" / "filings")
        log = pd.read_csv(Path(d) / "reports" / "extract_log.csv")
        meta = json.loads((Path(d) / "reports" / "build_meta.json").read_text())

    # Fund 2's fiscal year ends in January, so Feb-Mar 2021 lack it: the sample ends 2021-01.
    assert meta["sample_end"] == "2021-01", meta

    assert log["dropped_rows"].eq(0).all() and log["missing_cols"].isna().all(), log
    p["month"] = pd.to_datetime(p["month"]).dt.to_period("M")
    m = p.merge(truth.rename(columns={"sid": "SERIES_ID"}), on=["SERIES_ID", "month"],
                suffixes=("", "_true"), validate="one_to_one")
    key = lambda s, mo: (m.SERIES_ID == s) & (m.month == mo)  # noqa: E731

    # Flows: exact despite D != RI, gaps, a missing flow, a missing return, monthly filing.
    flows = m[m["SERIES_ID"] != "S000000005"]
    assert len(flows) > 50
    unknown = flows["flow"].isna()
    assert unknown.sum() == 1 and key(NO_SALES1[0], NO_SALES1[1] - 2)[unknown.index[unknown]].all(), \
        "only the month with the blank sales field should lack a flow"
    assert np.allclose(flows.loc[~unknown, "flow"], flows.loc[~unknown, "flow_true"], rtol=1e-7, atol=1e-10), \
        "flows not recovered"
    for s, mo in [(NO_SALES1[0], NO_SALES1[1] - 1), (NO_SALES1[0], NO_SALES1[1]),   # backward fallback
                  (NO_RET2[0], NO_RET2[1]),                                        # r2 missing
                  ("S000000006", P("2020-10"))]:                                   # after the gap
        assert key(s, mo).sum() == 1 and m.loc[key(s, mo), "flow"].notna().all(), (s, mo)

    # Returns: the blank return and the 2-class conflict are missing; everything else exact,
    # including the 3-class fund whose bad class is dropped.
    has = m["ret"].notna()
    missing = key(NO_RET2[0], NO_RET2[1] - 1) | key(CONFLICT[0], CONFLICT[1] - 3 + CONFLICT[3])
    assert (~has == missing).all(), m.loc[~has, ["SERIES_ID", "month"]]
    assert np.allclose(m.loc[has, "ret"], m.loc[has, "r"], atol=1e-9), "returns not recovered"
    bad = key(BAD_CLASS[0], BAD_CLASS[1] - 3 + BAD_CLASS[3])
    conflict = key(CONFLICT[0], CONFLICT[1] - 3 + CONFLICT[3])
    assert (m["flag_class_outlier"] == (bad | conflict)).all(), "class outliers misflagged"
    assert not np.isclose(m.loc[bad, "ret_all_classes"], m.loc[bad, "r"]).any()
    lag = truth.assign(month=truth["month"] + 1).rename(columns={"sid": "SERIES_ID", "r": "r_prev"})
    ml = m.merge(lag[["SERIES_ID", "month", "r_prev"]], on=["SERIES_ID", "month"])
    ok = ml["ret_lag"].notna()
    assert ok.mean() > 0.9 and np.allclose(ml.loc[ok, "ret_lag"], ml.loc[ok, "r_prev"]), "lag misaligned"

    # Net-asset reconstruction: the raw identity does NOT close (cash distributions), the
    # bridge recovers the leakage rate, and every method is exercised.
    q3 = f[f["prev_gap"].eq(3)]
    assert q3["closure_err"].abs().median() > 1e-3, "synthetic data should have D != RI"
    bridged = f.loc[f["dist_src"].eq("bridged"), "dist_rate"]
    assert len(bridged) > 20 and np.allclose(bridged, LEAK, atol=1e-9), "leakage not recovered"
    assert {"bridged", "backward"} <= set(p["na_method"]), set(p["na_method"])
    assert f["prev_gap"].eq(1).any(), "monthly filer not anchored on the previous month"

    amend = m[(m.SERIES_ID == AMEND[0]) & (m.month == AMEND[1] - 1)]
    assert np.isclose(amend["sales"].iloc[0], amend["sales_true"].iloc[0]), "amendment not applied"
    types = p.drop_duplicates("SERIES_ID").set_index("SERIES_ID")["bond_type"].to_dict()
    assert types == {"S000000001": "corp", "S000000002": "gov", "S000000003": "not_bond",
                     "S000000004": "muni", "S000000005": "corp", "S000000006": "sovereign_nonus",
                     "S000000007": "corp"}, types
    assert not p.loc[p.SERIES_ID == "S000000005", "eligible"].any(), "closed-end fund not excluded"
    assert p["flag_no_flow_activity"].sum() > 0
    etf = p.SERIES_ID == "S000000007"
    assert p.loc[etf, "flag_etf_name"].all() and not p.loc[~etf, "flag_etf_name"].any()
    assert not p.loc[etf, "eligible"].any(), "ETF-named fund not excluded"
    assert p.loc[p.SERIES_ID == "S000000006", "eligible"].any(), "sovereign bond fund not eligible"
    print("ALL SYNTHETIC CHECKS PASSED")


if __name__ == "__main__":
    test_end_to_end()
