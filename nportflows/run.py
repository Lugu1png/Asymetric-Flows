"""Run the whole pipeline: download -> extract -> build_panel -> checks -> analysis.

Each step skips work already done (zips with a matching checksum, quarters already
extracted), and the panel is rebuilt only when there is new data or no panel yet, so the
same command both builds everything the first time and brings it up to date later.

Usage:  python -m nportflows.run [--skip-download] [--rebuild]
"""
import argparse

from . import analysis, build_panel, checks, config as C, download, extract
from .io import EXT


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-download", action="store_true",
                    help="use the zips already in data/raw (no network)")
    ap.add_argument("--rebuild", action="store_true",
                    help="rebuild the panel and report even if no new data arrived")
    a = ap.parse_args(argv)

    new = [] if a.skip_download else download.main()
    print(f"\n== extract ({len(new)} new quarter(s) downloaded)")
    extracted = extract.main()       # also catches zips downloaded by an earlier, interrupted run
    if not (extracted or a.rebuild or not (C.PROCESSED / f"panel{EXT}").exists()):
        print("\nNo new data: panel and report are up to date (use --rebuild to force).")
        return
    print("\n== build_panel")
    build_panel.main()
    print("\n== checks")
    checks.main()
    print("\n== analysis")
    analysis.main()
    print(f"\nDone. Reports: {C.REPORTS / 'data_quality.md'}, {C.REPORTS / 'regressions.md'}")


if __name__ == "__main__":
    main()
