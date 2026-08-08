"""Step 2: pull the tables we need out of each quarterly zip (no analytical choices here,
except the holdings composition, which is aggregated per filing to keep it small).

Tables used (field names from https://www.sec.gov/files/nport_readme.pdf):
  SUBMISSION            ACCESSION_NUMBER, FILING_DATE, SUB_TYPE, REPORT_DATE, IS_LAST_FILING
  REGISTRANT            ACCESSION_NUMBER, CIK, REGISTRANT_NAME
  FUND_REPORTED_INFO    ACCESSION_NUMBER, SERIES_ID, SERIES_NAME, TOTAL_ASSETS, NET_ASSETS,
                        SALES_FLOW_MON{1,2,3}, REINVESTMENT_FLOW_MON{1,2,3}, REDEMPTION_FLOW_MON{1,2,3}
  MONTHLY_TOTAL_RETURN  ACCESSION_NUMBER, CLASS_ID, MONTHLY_TOTAL_RETURN{1,2,3}
  FUND_REPORTED_HOLDING ACCESSION_NUMBER, PERCENTAGE, PAYOFF_PROFILE, ASSET_CAT, ISSUER_TYPE, DERIVATIVE_CAT

Usage:  python -m nportflows.extract
"""
import csv
import re
import sys
from collections import Counter
from pathlib import Path
import zipfile

import pandas as pd

from . import config as C
from .io import save, EXT

ACC_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
MON = (1, 2, 3)
FRI_COLS = (["ACCESSION_NUMBER", "SERIES_NAME", "SERIES_ID", "TOTAL_ASSETS", "NET_ASSETS"]
            + [f"{p}_FLOW_MON{k}" for k in MON for p in ("SALES", "REINVESTMENT", "REDEMPTION")])
SUB_COLS = ["ACCESSION_NUMBER", "FILING_DATE", "SUB_TYPE", "REPORT_ENDING_PERIOD",
            "REPORT_DATE", "IS_LAST_FILING"]
REG_COLS = ["ACCESSION_NUMBER", "CIK", "REGISTRANT_NAME"]
RET_COLS = ["ACCESSION_NUMBER", "CLASS_ID"] + [f"MONTHLY_TOTAL_RETURN{k}" for k in MON]
HOLD_COLS = ["ACCESSION_NUMBER", "PERCENTAGE", "PAYOFF_PROFILE", "ASSET_CAT",
             "ISSUER_TYPE", "DERIVATIVE_CAT"]


def members(zf):
    return {Path(n).name.upper(): n for n in zf.namelist() if n.lower().endswith(".tsv")}


def read(zf, mem, table, usecols, chunksize=None):
    name = mem.get(f"{table}.TSV")
    if name is None:
        raise KeyError(f"{table}.tsv not in zip (members: {sorted(mem)})")
    # TSV, UTF-8 (readme s.4). QUOTE_NONE: quotes in free text (issuer names) are literal;
    # treating them as quoting characters can silently glue rows together.
    return pd.read_csv(zf.open(name), sep="\t", dtype=str, usecols=usecols,
                       chunksize=chunksize, quoting=csv.QUOTE_NONE, keep_default_na=False,
                       na_values=[""], encoding="utf-8", encoding_errors="replace",
                       on_bad_lines="warn")


def strip_quotes(df):
    for c in df.columns:
        df[c] = df[c].str.strip().str.strip('"')
    return df


def check_accessions(df, table, q, log):
    bad = (~df["ACCESSION_NUMBER"].fillna("").str.match(ACC_RE)).sum()
    log.append({"quarter": q, "table": table, "rows": len(df), "bad_accession_rows": int(bad)})


def composition(zf, mem, q, log, codes):
    parts = []
    n = bad = 0
    for ch in read(zf, mem, "FUND_REPORTED_HOLDING", HOLD_COLS, C.HOLDINGS_CHUNK):
        ch = strip_quotes(ch)
        n += len(ch)
        bad += int((~ch["ACCESSION_NUMBER"].fillna("").str.match(ACC_RE)).sum())
        pct = pd.to_numeric(ch["PERCENTAGE"], errors="coerce")
        cat = ch["ASSET_CAT"].fillna("").str.upper()
        iss = ch["ISSUER_TYPE"].fillna("").str.upper()
        codes["ASSET_CAT"].update(cat)
        codes["ISSUER_TYPE"].update(iss)
        deriv = ch["DERIVATIVE_CAT"].notna() | cat.isin(C.DERIV_CATS)
        base = ch["PAYOFF_PROFILE"].fillna("").str.lower().eq("long") & ~deriv
        debt = base & cat.isin(C.DEBT_CATS)
        z = lambda m: pct.where(m, 0.0)  # noqa: E731
        df = pd.DataFrame({
            "ACCESSION_NUMBER": ch["ACCESSION_NUMBER"],
            "pct_all": pct, "pct_long_nonderiv": z(base), "pct_debt": z(debt),
            "pct_equity": z(base & cat.isin(C.EQUITY_CATS)),
            "pct_gov": z(debt & iss.isin(C.GOV_ISSUERS)),
            "pct_muni": z(debt & iss.isin(C.MUNI_ISSUERS)),
            "pct_corp": z(debt & iss.isin(C.CORP_ISSUERS)),
            "n_holdings": 1, "n_pct_missing": pct.isna().astype(int)})
        parts.append(df.groupby("ACCESSION_NUMBER").sum(min_count=1))
    log.append({"quarter": q, "table": "FUND_REPORTED_HOLDING", "rows": n, "bad_accession_rows": bad})
    return pd.concat(parts).groupby(level=0).sum(min_count=1).reset_index()


def extract_quarter(zpath: Path, log, codes):
    q = zpath.name.split("_")[0]
    out = C.INTERIM / q
    if (out / f"composition{EXT}").exists():
        print(f"{q}: already extracted")
        return
    print(f"{q}: extracting")
    with zipfile.ZipFile(zpath) as zf:
        mem = members(zf)
        for table, cols, name in [("SUBMISSION", SUB_COLS, "submission"),
                                  ("REGISTRANT", REG_COLS, "registrant"),
                                  ("FUND_REPORTED_INFO", FRI_COLS, "fund_info"),
                                  ("MONTHLY_TOTAL_RETURN", RET_COLS, "returns")]:
            df = strip_quotes(read(zf, mem, table, cols))
            check_accessions(df, table, q, log)
            save(df, out / name)
        qcodes = {"ASSET_CAT": Counter(), "ISSUER_TYPE": Counter()}
        comp = composition(zf, mem, q, log, qcodes)
        save(pd.DataFrame([{"field": f, "code": k, "n": v} for f, c in qcodes.items()
                           for k, v in c.items()]), out / "codes")
        for f in qcodes:
            codes[f].update(qcodes[f])
        save(comp, out / "composition")   # written last = completion marker


def main():
    zips = sorted(C.RAW.glob("*_nport.zip"))
    if not zips:
        sys.exit(f"No zips in {C.RAW}; run nportflows.download first")
    log, codes = [], {"ASSET_CAT": Counter(), "ISSUER_TYPE": Counter()}
    for z in zips:
        extract_quarter(z, log, codes)
    C.REPORTS.mkdir(parents=True, exist_ok=True)
    if log:   # appended, so re-runs that skip finished quarters keep earlier entries
        p = C.REPORTS / "extract_log.csv"
        new = pd.DataFrame(log)
        if p.exists():
            new = pd.concat([pd.read_csv(p), new]).drop_duplicates(["quarter", "table"], keep="last")
        new.to_csv(p, index=False)


if __name__ == "__main__":
    main()
