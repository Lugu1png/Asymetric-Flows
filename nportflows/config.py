"""Central configuration. Every analytical choice lives here so it is visible and versioned."""
import calendar
import os
from datetime import date, timedelta
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
# "auto" = the current calendar quarter. Quarters the SEC has not published yet are skipped
# and picked up by a later run, so re-running the pipeline collects new data automatically.
LAST_QUARTER = os.environ.get("NPORT_LAST_Q", "auto")
# A zip appears some weeks after its quarter ends. Quarters that ended less than this many
# days ago are tried once and skipped on any HTTP error instead of failing the run.
PUBLICATION_LAG_DAYS = 120
BASE_URL = "https://www.sec.gov/files/dera/data/form-n-port-data-sets/{q}_nport.zip"
# SEC fair-access policy requires a descriptive User-Agent with a contact address.
USER_AGENT = os.environ.get("SEC_USER_AGENT", "")   # e.g. "Luiz Ganem <you@uni.lu>"
DOWNLOAD_TRIES = 5           # attempts per zip; waits 10s, 20s, 40s, ... between them

# --- Units -----------------------------------------------------------------
# MONTHLY_TOTAL_RETURN is believed to be reported in percent (0.52 = 0.52%), but the
# readme does not state units. "auto" decides from the median |raw return| across all
# classes (> 0.1 -> percent); True / False force a choice and only warn on a mismatch.
RETURNS_IN_PERCENT = "auto"

# --- Sample ----------------------------------------------------------------
SAMPLE_START = "2020-01"                  # first month kept for estimation
# Last month kept. "auto" = the last month whose number of reporting series is at least
# COVERAGE_MIN_SHARE of the median of the 12 months before it. The newest months are
# incomplete because funds with later fiscal quarters have not filed yet.
SAMPLE_END = "auto"
COVERAGE_MIN_SHARE = 0.95
CLASSIFY_CUTOFF = "2021-12-31"            # classify funds on pre-tightening holdings only

# --- Fund returns from class returns ----------------------------------------
# Classes share one portfolio, so their returns differ only by fees (< 0.1pp/month).
# A class more than this far from the fund's median class return is dropped before
# averaging; with two classes that disagree by more than 2x this, the fund return is
# set to missing (no way to tell which class is right).
CLASS_OUTLIER = 0.005
EXTREME_RET = 0.2            # |monthly fund return| > 20%: flagged; lagged ones not eligible

# --- Net-asset reconstruction ---------------------------------------------
# Cash distributions are not reported, so NA_m = NA_{m-1}(1 + r_m - d) + S_m - R_m with a
# per-filing leakage rate d (cash distributions net of reinvestment, as a share of NA).
# d is solved so the path from the previous reported NA closes on this filing's reported
# NA, but only if the unadjusted closure error is at most BRIDGE_MAX_CLOSURE (larger gaps
# suggest mergers or reporting errors, which d should not absorb).
BRIDGE_MAX_CLOSURE = 0.05
# Plausible range for d (per month). Cash distributions cannot be negative, so d well below
# zero means unexplained growth (merger, misreported flows); far above the yield means
# unexplained shrinkage. Filings outside the range, or not bridged, get flag_bad_na.
DIST_RATE_BOUNDS = (-0.005, 0.01)
EXCLUDE_BAD_NA = True        # ... and are left out of `eligible`

# --- Bond-fund classification (holdings in % of net assets, long, non-derivative)
BOND_MIN_DEBT_PCT = 70.0       # debt + cash-like (repo, MMF shares) >= 70% of net assets
BOND_MIN_DEBT_ONLY_PCT = 50.0  # ... of which debt securities alone >= 50%
BOND_MAX_EQUITY_PCT = 10.0     # equity <= 10% of net assets (drops allocation funds)
SUBTYPE_MIN_SHARE = 0.5        # gov / muni / sovereign / corp if >= 50% of the debt book
BOND_TYPES = ("gov", "corp", "muni", "sovereign_nonus", "mixed")

# --- Filters / flags (flags only; nothing analytical is dropped at build time)
MIN_LAG_NA = 10e6            # primary size filter, applied on LAGGED net assets
MIN_LAG_NA_ROBUST = 50e6
EXTREME_FLOW = 0.5           # |monthly flow| > 50% of lagged NA is flagged
EXCLUDE_EXTREME_FLOW = True  # ... and left out of `eligible`
# N-PORT has no ETF flag. Series whose name matches this are flagged as ETFs, left out of
# `eligible` and out of the peer group for category-adjusted returns. Misses ETFs that are
# a share class of a mutual-fund series (e.g. Vanguard), whose name does not say ETF.
ETF_NAME_RE = r"\bETFs?\b|EXCHANGE[- ]TRADED"
EXCLUDE_ETF_NAME = True
LAST_FILING_YES = {"Y", "YES", "TRUE", "T", "1"}   # accepted spellings of IS_LAST_FILING

# Asset / issuer codes used for classification. VERIFY against
# reports/code_frequencies.csv after extraction: the readme gives field names
# but not the code lists, which come from the N-PORT XML technical spec.
DEBT_CATS = {"DBT", "ABS-MBS", "ABS-ASBS", "ABS-CBDO", "ABS-APCP", "ABS-O", "LON", "SN"}
CASH_CATS = {"RA", "STIV"}   # repurchase agreements, short-term investment vehicles
EQUITY_CATS = {"EC", "EP"}
DERIV_CATS = {"DCO", "DCR", "DE", "DFE", "DIR", "DO"}
GOV_ISSUERS = {"UST", "USGA", "USGSE"}
SOV_ISSUERS = {"NUSS"}       # non-US sovereign: kept apart from US government
MUNI_ISSUERS = {"MUN"}
CORP_ISSUERS = {"CORP"}

HOLDINGS_CHUNK = 2_000_000

# --- Regressions (analysis.py) ----------------------------------------------
# Fed tightening: first hike (March 2022) to last hike (July 2023).
TIGHT_START = "2022-03"
TIGHT_END = "2023-07"
WINSOR = 0.01                # flows and performance winsorised at 1% / 99% each month-pooled


def current_quarter(today=None):
    d = today or date.today()
    return f"{d.year}q{(d.month - 1) // 3 + 1}"


def quarter_end(q):
    y, m = int(q[:4]), 3 * int(q[-1])
    return date(y, m, calendar.monthrange(y, m)[1])


def maybe_unpublished(q, today=None):
    return (today or date.today()) - quarter_end(q) < timedelta(days=PUBLICATION_LAG_DAYS)


def quarters(first=FIRST_QUARTER, last=LAST_QUARTER):
    if last == "auto":
        last = current_quarter()
    y, q = int(first[:4]), int(first[-1])
    ly, lq = int(last[:4]), int(last[-1])
    out = []
    while (y, q) <= (ly, lq):
        out.append(f"{y}q{q}")
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out
