"""Write the first-run example table as CSV, ready to import into any ledger.

Output: 示例表.csv in the folder given (default: the package's 03-表格 folder).
The CSV has the header row and the 13 sample rows. L is the tool's own computed value, so the file
shows what the rule produces today for the sample dates. A user who imports it sees the same list.

Generic content only. No real business names, no connection details.
"""
import csv
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_rows(tool_path: Path, data_path: Path):
    sample = _load("sample", data_path)
    tool = _load("tool", tool_path)
    today = sample.BASE
    head = sample.HEADER_A_TO_L + sample.HEADER_EXTRA
    ids = {}
    for r in sample.ROWS:
        ids[r["I"].casefold()] = ids.get(r["I"].casefold(), 0) + 1
    body = []
    for r in sample.ROWS:
        ab = [r["A"], r["B"], r["C"], r["D"], r["E"], r["F"], r["G"], r["H"], r["I"], r["J"], r["K"]]
        lval = tool.compute_l(ab, ids[r["I"].casefold()], today)
        body.append(ab + [lval, r["M"], r["N"], r["O"]])
    return [head] + body


def main(out_dir: Path) -> int:
    tool_path = HERE.parent / "实施" / "提醒工具.py"
    data_path = HERE / "示例表数据.py"
    rows = build_rows(tool_path, data_path)
    assert all(len(r) == 15 for r in rows), "every row must have 15 cells (A:O)"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "示例表.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)
    print(f"wrote {out} ({len(rows) - 1} sample rows)")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "交付包源" / "示例表输出"
    sys.exit(main(target))
