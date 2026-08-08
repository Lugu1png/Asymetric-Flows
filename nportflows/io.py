"""Table storage: parquet when pyarrow is installed (normal case), pickle otherwise."""
from pathlib import Path
import pandas as pd

try:
    import pyarrow  # noqa: F401
    EXT = ".parquet"
except ImportError:  # pragma: no cover
    EXT = ".pkl"


def save(df: pd.DataFrame, path_no_ext: Path) -> Path:
    p = Path(str(path_no_ext) + EXT)
    p.parent.mkdir(parents=True, exist_ok=True)
    if EXT == ".parquet":
        df.to_parquet(p, index=False)
    else:
        df.to_pickle(p)
    return p


def load(path_no_ext: Path) -> pd.DataFrame:
    p = Path(str(path_no_ext) + EXT)
    return pd.read_parquet(p) if EXT == ".parquet" else pd.read_pickle(p)


def load_all_quarters(interim: Path, table: str) -> pd.DataFrame:
    files = sorted(interim.glob(f"*/{table}{EXT}"))
    if not files:
        raise FileNotFoundError(f"No extracted '{table}' tables under {interim}")
    return pd.concat([load(f.with_suffix("")).assign(src_q=f.parent.name) for f in files],
                     ignore_index=True)
