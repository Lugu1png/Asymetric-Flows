"""Central configuration. Every analytical choice lives here so it is visible and versioned."""
import os
from pathlib import Path

ROOT = Path(os.environ.get("NPORT_ROOT", Path(__file__).resolve().parents[1]))
RAW = ROOT / "data" / "raw"            # untouched SEC zips + manifest
INTERIM = ROOT / "data" / "interim"    # per-quarter extracted tables
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"

# --- Download --------------------------------------------------------------
# Zips are labelled by FILING quarter, not report period. 2019q4 is the first
# set; it is needed to get lagged net assets/returns for early 2020.
FIRST_QUARTER = os.environ.get("NPORT_FIRST_Q", "2019q4")
LAST_QUARTER = os.environ.get("NPORT_LAST_Q", "2026q2")
BASE_URL = "https://www.sec.gov/files/dera/data/form-n-port-data-sets/{q}_nport.zip"
# SEC fair-access policy requires a descriptive User-Agent with a contact address.
USER_AGENT = os.environ.get("SEC_USER_AGENT", "")   # e.g. "Luiz Ganem <you@uni.lu>"

# --- Units -----------------------------------------------------------------
# MONTHLY_TOTAL_RETURN is believed to be reported in percent (0.52 = 0.52%).
# The readme does not state units: checks.py reports the distribution so you
# can confirm before trusting this.
RETURNS_IN_PERCENT = True

# --- Sample ----------------------------------------------------------------
SAMPLE_START = "2020-01"                  # first month kept for estimation
CLASSIFY_CUTOFF = "2021-12-31"            # classify funds on pre-tightening holdings only

# --- Bond-fund classification (holdings in % of net assets, long, non-derivative)
BOND_MIN_DEBT_PCT = 70.0     # debt securities >= 70% of net assets
BOND_MAX_EQUITY_PCT = 10.0   # equity <= 10% of net assets (drops allocation funds)
SUBTYPE_MIN_SHARE = 0.5      # gov / muni / corp if >= 50% of the debt book

# --- Filters / flags (flags only; nothing analytical is dropped at build time)
MIN_LAG_NA = 10e6            # primary size filter, applied on LAGGED net assets
MIN_LAG_NA_ROBUST = 50e6
EXTREME_FLOW = 0.5           # |monthly flow| > 50% of lagged NA is flagged

# Asset / issuer codes used for classification. VERIFY against
# reports/code_frequencies.csv after extraction: the readme gives field names
# but not the code lists, which come from the N-PORT XML technical spec.
DEBT_CATS = {"DBT", "ABS-MBS", "ABS-ASBS", "ABS-CBDO", "ABS-O", "LON"}
EQUITY_CATS = {"EC", "EP"}
DERIV_CATS = {"DCO", "DCR", "DE", "DFE", "DIR", "DO"}
GOV_ISSUERS = {"UST", "USGA", "USGSE", "NUSS"}
MUNI_ISSUERS = {"MUN"}
CORP_ISSUERS = {"CORP"}

HOLDINGS_CHUNK = 2_000_000


def quarters(first=FIRST_QUARTER, last=LAST_QUARTER):
    y, q = int(first[:4]), int(first[-1])
    ly, lq = int(last[:4]), int(last[-1])
    out = []
    while (y, q) <= (ly, lq):
        out.append(f"{y}q{q}")
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out
