"""End-to-end test on synthetic N-PORT zips with known true flows and returns.

It writes zips in the documented layout (tab-separated tables, readme field names),
runs extract -> build_panel -> checks, and asserts the panel recovers the truth.
Covers: offset fiscal quarters, multi-class returns, an amendment filed in a later zip,
a closed-end fund, an equity fund, Oracle-style dates, returns in percent.

Run:  python tests/test_synthetic.py      (or: pytest tests/)
"""
import io
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

FUNDS = {  # series: (report months of fiscal quarters, n classes, holdings type, has flows)
    "S000000001": ({3, 6, 9, 12}, 1, "corp", True),
    "S000000002": ({1, 4, 7, 10}, 2, "gov", True),    # fiscal year ending January
    "S000000003": ({3, 6, 9, 12}, 1, "equity", True),
    "S000000004": ({3, 6, 9, 12}, 1, "muni", True),   # gets an amendment
    "S000000005": ({3, 6, 9, 12}, 1, "corp", False),  # closed-end-like: no sales/redemptions
}
AMEND = ("S000000004", pd.Period("2020-06", "M"))


def simulate(seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for sid, (_, _, kind, flows) in FUNDS.items():
        na = 500e6
        for m in MONTHS:
            r = rng.normal(0.002, 0.01) - (0.02 if m.year == 2022 else 0)
            s = na * rng.uniform(0.01, 0.04) if flows else 0.0
            red = na * rng.uniform(0.01, 0.05) if flows else 0.0
            ri = na * 0.002 if flows else 0.0          # reinvested = paid distribution (D = RI)
            na_new = na * (1 + r) + s - red            # identity with D = RI
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

    for sid, (qmonths, ncls, kind, _) in FUNDS.items():
        t = truth[truth.sid == sid].set_index("month")
        for m3 in MONTHS:
            if m3.month not in qmonths or m3 - 2 < MONTHS[0]:
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
                fri = dict(ACCESSION_NUMBER=a, SERIES_NAME=f"Fund {sid[-1]}", SERIES_ID=sid,
                           SERIES_LEI="", TOTAL_ASSETS=t.loc[m3, "na_end"] * 1.01,
                           TOTAL_LIABILITIES=t.loc[m3, "na_end"] * 0.01, NET_ASSETS=t.loc[m3, "na_end"])
                for k, m in enumerate(ms, 1):
                    fri[f"SALES_FLOW_MON{k}"] = t.loc[m, "sales"] * (sales_err if k == 2 else 1)
                    fri[f"REINVESTMENT_FLOW_MON{k}"] = t.loc[m, "reinv"]
                    fri[f"REDEMPTION_FLOW_MON{k}"] = t.loc[m, "redemp"]
                add(q, "FUND_REPORTED_INFO", fri)
                for c in range(ncls):
                    off = (c - (ncls - 1) / 2) * 0.002              # class returns average to fund return
                    row = dict(ACCESSION_NUMBER=a, MONTHLY_TOTAL_RETURN_ID=c, CLASS_ID=f"C{sid[-4:]}{c}")
                    for k, m in enumerate(ms, 1):
                        row[f"MONTHLY_TOTAL_RETURN{k}"] = round(100 * (t.loc[m, "r"] + off), 10)
                    add(q, "MONTHLY_TOTAL_RETURN", row)
                hold = {"corp": [("DBT", "CORP", 80), ("DBT", "UST", 15), ("STIV", "RF", 5)],
                        "gov": [("DBT", "UST", 60), ("ABS-MBS", "USGSE", 35), ("STIV", "RF", 5)],
                        "muni": [("DBT", "MUN", 97), ("STIV", "RF", 3)],
                        "equity": [("EC", "CORP", 98), ("STIV", "RF", 2)]}[kind]
                for i, (cat, iss, pct) in enumerate(hold):
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


def run(mod, env):
    r = subprocess.run([sys.executable, "-m", f"nportflows.{mod}"], cwd=REPO, env=env,
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
        for mod in ("extract", "build_panel", "checks"):
            out = run(mod, env)
        print(out[-2500:])
        sys.path.insert(0, str(REPO))
        os.environ["NPORT_ROOT"] = d
        from nportflows.io import load
        p = load(Path(d) / "data" / "processed" / "panel")

    p["month"] = pd.to_datetime(p["month"]).dt.to_period("M")
    m = p.merge(truth.rename(columns={"sid": "SERIES_ID"}), on=["SERIES_ID", "month"],
                suffixes=("", "_true"), validate="one_to_one")
    flows = m[m["SERIES_ID"] != "S000000005"]
    assert len(flows) > 50
    assert np.allclose(flows["flow"], flows["flow_true"], rtol=1e-8, atol=1e-10), "flows not recovered"
    assert np.allclose(m["ret"], m["r"], atol=1e-9), "returns not recovered"
    lag = truth.assign(month=truth["month"] + 1).rename(columns={"sid": "SERIES_ID", "r": "r_prev"})
    ml = m.merge(lag[["SERIES_ID", "month", "r_prev"]], on=["SERIES_ID", "month"])
    ok = ml["ret_lag"].notna()
    assert ok.mean() > 0.9 and np.allclose(ml.loc[ok, "ret_lag"], ml.loc[ok, "r_prev"]), "lag misaligned"
    amend = m[(m.SERIES_ID == AMEND[0]) & (m.month == AMEND[1] - 1)]
    assert np.isclose(amend["sales"].iloc[0], amend["sales_true"].iloc[0]), "amendment not applied"
    types = p.drop_duplicates("SERIES_ID").set_index("SERIES_ID")["bond_type"].to_dict()
    assert types == {"S000000001": "corp", "S000000002": "gov", "S000000003": "not_bond",
                     "S000000004": "muni", "S000000005": "corp"}, types
    assert not p.loc[p.SERIES_ID == "S000000005", "eligible"].any(), "closed-end fund not excluded"
    assert p["flag_no_flow_activity"].sum() > 0
    print("ALL SYNTHETIC CHECKS PASSED")


if __name__ == "__main__":
    test_end_to_end()
