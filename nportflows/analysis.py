"""Step 5: flow-performance regressions -> reports/regressions.md (+ regressions.csv).

Piecewise-linear flow-performance relation (Goldstein, Jiang & Ng 2017):
    flow_{i,t} = b1 perf_{i,t-1} + b2 perf_{i,t-1} 1[perf_{i,t-1} < 0] + controls + FE + e
Slope above zero = b1, below zero = b1 + b2. Concavity (outflows react more to bad
performance than inflows to good performance) means b2 > 0.
Tightening: the same terms interacted with TIGHT (TIGHT_START..TIGHT_END); b4 on
perf x neg x tight > 0 means the concavity strengthened during the tightening.

Fixed effects are absorbed by alternating demeaning; standard errors are clustered by fund.
Sample: rows with `eligible` (see build_panel). Flows and performance are winsorised.

Usage:  python -m nportflows.analysis
"""
import math

import numpy as np
import pandas as pd

from . import config as C
from .io import load

CONTROLS = ["flow_lag", "log_na_lag"]


def winsor(s, p=C.WINSOR):
    lo, hi = s.quantile([p, 1 - p])
    return s.clip(lo, hi)


def demean(d, cols, fe, tol=1e-10, max_iter=1000):
    """Within transformation for one or more sets of fixed effects (alternating projections)."""
    X = d[cols].to_numpy(float).copy()
    if not fe:
        return X - X.mean(0)
    codes = [pd.factorize(d[g])[0] for g in fe]
    counts = [np.bincount(c) for c in codes]
    scale = np.abs(X).max(0) + 1e-300
    for _ in range(max_iter):
        prev = X.copy()
        for c, n in zip(codes, counts):
            for j in range(X.shape[1]):
                X[:, j] -= (np.bincount(c, X[:, j]) / n)[c]
        if len(fe) == 1 or (np.abs(X - prev).max(0) / scale).max() < tol:
            break
    return X


def ols(d, y, xs, fe, cluster="SERIES_ID"):
    d = d.dropna(subset=[y] + xs)
    M = demean(d, [y] + xs, fe)
    yv, X = M[:, 0], M[:, 1:]
    n, k = X.shape
    flat = [x for x, v in zip(xs, X.var(0)) if v < 1e-20]
    if flat or n <= k:
        raise ValueError(f"not identified (no variation in {flat or 'sample'})")
    inv = np.linalg.inv(X.T @ X)
    b = inv @ X.T @ yv
    u = yv - X @ b
    g = pd.factorize(d[cluster])[0]
    G = g.max() + 1
    sg = np.zeros((G, k))
    np.add.at(sg, g, X * u[:, None])
    V = inv @ (sg.T @ sg) @ inv * (G / (G - 1)) * ((n - 1) / (n - k))
    return {"b": pd.Series(b, xs), "V": pd.DataFrame(V, xs, xs), "n": n, "funds": G,
            "r2_within": 1 - (u @ u) / (yv @ yv)}


def lincomb(res, w):
    """Estimate, SE and two-sided p-value (normal) of sum(w_j * b_j)."""
    w = pd.Series(w).reindex(res["b"].index, fill_value=0.0)
    est = float(w @ res["b"])
    se = float(np.sqrt(w @ res["V"] @ w))
    return est, se, math.erfc(abs(est / se) / math.sqrt(2))


def stars(p):
    return "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""


def prepare(p, perf):
    d = p[p["eligible"]].copy()
    d["flow"] = winsor(d["flow"])
    d["flow_lag"] = winsor(d["flow_lag"])
    d["perf"] = winsor(d[perf])
    d["log_na_lag"] = np.log(d["na_lag"])
    d["neg"] = (d["perf"] < 0).astype(float)
    d["tight"] = d["month"].between(pd.Timestamp(C.TIGHT_START),
                                    pd.Timestamp(C.TIGHT_END) + pd.offsets.MonthEnd(0)).astype(float)
    d["perf_neg"] = d["perf"] * d["neg"]
    d["perf_tight"] = d["perf"] * d["tight"]
    d["perf_neg_tight"] = d["perf_neg"] * d["tight"]
    return d


def run_spec(name, d, tight, fe):
    xs = ["perf", "perf_neg"] + (["perf_tight", "perf_neg_tight"] if tight else []) + CONTROLS
    r = ols(d, "flow", xs, fe)
    row = {"spec": name, "fe": "+".join(fe), "n": r["n"], "funds": r["funds"],
           "r2_within": r["r2_within"]}
    combos = {"slope_above (b1)": {"perf": 1},
              "slope_below (b1+b2)": {"perf": 1, "perf_neg": 1},
              "concavity (b2)": {"perf_neg": 1}}
    if tight:
        combos.update({
            "tight: slope_above": {"perf": 1, "perf_tight": 1},
            "tight: slope_below": {"perf": 1, "perf_neg": 1, "perf_tight": 1, "perf_neg_tight": 1},
            "tight: concavity (b2+b4)": {"perf_neg": 1, "perf_neg_tight": 1},
            "change in concavity (b4)": {"perf_neg_tight": 1}})
    for lab, w in combos.items():
        est, se, pv = lincomb(r, w)
        row[lab] = est
        row[lab + " se"] = se
        row[lab + " p"] = pv
    return row


def main():
    p = load(C.PROCESSED / "panel")
    p["month"] = pd.to_datetime(p["month"])
    rel, raw = prepare(p, "ret_rel_lag"), prepare(p, "ret_lag")
    FM = ["SERIES_ID", "month"]
    specs = [
        ("1 base, month FE", rel, False, ["month"]),
        ("2 base, fund+month FE", rel, False, FM),
        ("3 tightening, fund+month FE (main)", rel, True, FM),
        ("4 = 3 with raw return", raw, True, FM),
        ("5 = 3, funds >= $50m", rel[rel["size_ok_robust"]], True, FM),
        ("6 = 3, no fund FE", rel, True, ["month"]),
    ] + [(f"7 = 3, {t} only", rel[rel["bond_type"] == t], True, FM) for t in ("corp", "gov", "muni")]
    rows = []
    for name, d, tight, fe in specs:
        print(f"  {name}")
        try:
            rows.append(run_spec(name, d, tight, fe))
        except (ValueError, np.linalg.LinAlgError) as e:
            print(f"    skipped: {e}")
            rows.append({"spec": f"{name} (skipped: {e})", "n": 0, "funds": 0})
    res = pd.DataFrame(rows)
    C.REPORTS.mkdir(parents=True, exist_ok=True)
    res.to_csv(C.REPORTS / "regressions.csv", index=False)

    keys = ["slope_above (b1)", "slope_below (b1+b2)", "concavity (b2)",
            "tight: slope_above", "tight: slope_below", "change in concavity (b4)"]
    cell = lambda r, k: ("" if pd.isna(r.get(k)) else  # noqa: E731
                         f"{r[k]:.3f}{stars(r[k + ' p'])} ({r[k + ' se']:.3f})")
    out = ["# Flow-performance regressions\n",
           f"Dependent variable: monthly net flow (share of lagged NA). Performance: lagged "
           f"category-adjusted monthly return unless stated. Controls: lagged flow, log lagged NA. "
           f"Tightening = {C.TIGHT_START} to {C.TIGHT_END}. SE clustered by fund in parentheses; "
           f"* p<0.1, ** p<0.05, *** p<0.01. Flows and performance winsorised at "
           f"{C.WINSOR:.0%}/{1 - C.WINSOR:.0%}.\n",
           "| spec | " + " | ".join(keys) + " | N | funds |",
           "|---" * (len(keys) + 3) + "|"]
    for _, r in res.iterrows():
        out.append(f"| {r['spec']} | " + " | ".join(cell(r, k) for k in keys)
                   + f" | {r['n']:,} | {r['funds']:,} |")
    out.append("\nReading: a slope of 0.5 means a 1pp higher return last month goes with 0.5pp "
               "more net flow this month. Concavity b2 > 0: flows react more to "
               "underperformance than to outperformance. b4 > 0: stronger during tightening.")
    (C.REPORTS / "regressions.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
