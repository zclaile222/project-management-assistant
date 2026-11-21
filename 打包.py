"""Build the deliverable package into 交付包/ from the project's files.

Principles:
- Whitelist only. Nothing is copied unless it is named below.
- Source files are read, never changed.
- Business examples are replaced by neutral ones from a checked list. A replacement that matches
  nothing is an error, so a stale list cannot silently ship old wording.
- The ledger identity (token, sheet ids, title) is removed from the shipped config and replaced by
  placeholders the install step fills in.
- After writing, the build scans the whole package for forbidden text (personal paths, the
  project's real ledger identity, business names). Any hit fails the build.

Run: python 打包.py            (writes 交付包/)
     python 打包.py --check    (rebuilds into a temp folder and only verifies)
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "实施"
OUT = ROOT / "交付包"

# ---- 1. whitelist: (source, destination inside the package) -------------------------------------
WHITELIST = [
    (ROOT / "规则定稿_20261105.md", "01-规则/规则定稿.md"),
    (SRC / "个人助理工作规范.md", "02-指令/通用指令.md"),
    (SRC / "早间计划.txt", "02-指令/早间计划.txt"),
    (SRC / "晚间复盘.txt", "02-指令/晚间复盘.txt"),
    (SRC / "周复盘.txt", "02-指令/周复盘.txt"),
    (SRC / "今日应提醒公式.txt", "03-表格/今日应提醒公式.txt"),
    (SRC / "提醒工具.py", "04-工具/提醒工具.py"),
    # The agent's entry point. Hand-written, so it lives in its own source folder, not in 实施/.
    (ROOT / "交付包源" / "START-HERE.md", "START-HERE.md"),
    # Version note for this release: what changed, what was verified, what is still open.
    (ROOT / "交付包源" / "CHANGELOG-v0.2.md", "CHANGELOG-v0.2.md"),
    # The first-run example table, generated fresh from the sample data on every build (see build()).
    (ROOT / "交付包源" / "示例表输出" / "示例表.csv", "05-示例/示例表.csv"),
    # The self-contained acceptance checklist, derived from the full one (交付包源/生成验收子集.py).
    # It sits in 05-验收 so that its parents[1] is the package root, which is what it expects.
    (ROOT / "交付包源" / "验收" / "验证清单.py", "06-验收/验证清单.py"),
    # The weekly-review skill: the manual trigger for the Saturday review (定时 + 手动 share one procedure).
    (ROOT / "交付包源" / "技能" / "周六复盘" / "SKILL.md", "07-技能/周六复盘/SKILL.md"),
    # 核对页公式.json is deliberately NOT shipped: the daily package is one table (规则第 3 节).
    # Acceptance keeps it in the project, outside the daily set.
]

# ---- 2. neutral examples: exact text -> replacement. Every entry must match at least once. ----
# Each source phrase is a business example. The replacement keeps the sentence's shape.
REPLACEMENTS = {
    "规则定稿_20261105.md": [
    ],
}

# ---- 3. forbidden text: must not appear anywhere in the package ---------------------------------
# The list itself is machine-local (打包_本机禁止词.txt, not in the repository): it names this maintainer's real
# ledger identifiers and personal paths, which must not be published. Without the file the build refuses to run,
# so a package can never be checked against an empty list by mistake.
LOCAL_FORBIDDEN = ROOT / "打包_本机禁止词.txt"

def load_forbidden() -> list[str]:
    if not LOCAL_FORBIDDEN.is_file():
        raise SystemExit(
            f"缺少本机禁止词文件：{LOCAL_FORBIDDEN.name}。\n"
            "该文件记录本机的真实标识和个人路径，不进仓库。没有它不能打包，否则无法验证交付包是否干净。\n"
            "请按 打包_本机禁止词.txt 的格式（每行一个词，# 开头为注释）创建它。")
    terms = [ln.strip() for ln in LOCAL_FORBIDDEN.read_text(encoding="utf-8").splitlines()]
    terms = [t for t in terms if t and not t.startswith("#")]
    if not terms:
        raise SystemExit(f"{LOCAL_FORBIDDEN.name} 为空，不能打包：空禁止表无法证明交付包干净。")
    return terms

FORBIDDEN = load_forbidden()

# Connection commands may appear as teaching, but must not point at the maintainer's real ledger.
# The identity check above already covers that; this list only documents what the scan allows.
ALLOWED_CONNECTION_TEACHING = ["lark-cli", "larksuite", "sheets +", "cells-get", "csv-get", "workbook-info",
                               "--spreadsheet-token", "--sheet-id"]

# ---- 4. config: ledger identity is replaced by placeholders -----------------------------------
PLACEHOLDER = "<安装时填写>"


def build_config(src: Path) -> str:
    cfg = json.loads(src.read_text(encoding="utf-8-sig"))
    # One table only: no audit sheet identity is shipped.
    cfg["ledger"] = {
        "spreadsheet_token": PLACEHOLDER,
        "sheet_id": PLACEHOLDER,
        "title": PLACEHOLDER,
    }
    # The tool resolves every path from its own folder (04-工具/). Each path below is relative to that folder.
    cfg["rules"] = "../01-规则/规则定稿.md"
    cfg["common"] = "../02-指令/通用指令.md"
    cfg["formula"] = "../03-表格/今日应提醒公式.txt"
    cfg.pop("control_formulas", None)
    for e in cfg["entries"].values():
        e["file"] = "../02-指令/" + e["file"]
    return json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"


def apply_replacements(name: str, text: str) -> str:
    for old, new in REPLACEMENTS.get(name, []):
        if old not in text:
            raise SystemExit(f"替换没有命中（过期或拼写不一致）：{name}: {old[:40]}…")
        text = text.replace(old, new)
    return text


def refresh_sample_table() -> None:
    """Regenerate the example CSV from the sample data, so the package never ships a stale copy."""
    gen = ROOT / "交付包源" / "生成示例表.py"
    out_dir = ROOT / "交付包源" / "示例表输出"
    if not gen.is_file():
        raise SystemExit(f"示例表生成器缺失：{gen}")
    import subprocess
    r = subprocess.run([sys.executable, "-X", "utf8", str(gen), str(out_dir)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"示例表生成失败，不能打包：{r.stderr.strip()[-300:]}")


def refresh_acceptance() -> None:
    """Re-derive the shipped checklist from the full one, so the package never carries a stale copy."""
    gen = ROOT / "交付包源" / "生成验收子集.py"
    if not gen.is_file():
        raise SystemExit(f"验收子集生成器缺失：{gen}")
    import subprocess
    r = subprocess.run([sys.executable, "-X", "utf8", str(gen)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"验收子集生成失败，不能打包：{(r.stderr or r.stdout).strip()[-300:]}")


def build(dest: Path) -> list[str]:
    refresh_sample_table()
    refresh_acceptance()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    written = []
    for src, rel in WHITELIST:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not src.is_file():
            raise SystemExit(f"白名单文件不存在：{src}")
        if src.suffix in (".md", ".txt", ".py", ".json"):
            text = src.read_text(encoding="utf-8")
            if src.name in REPLACEMENTS:
                text = apply_replacements(src.name, text)
            target.write_text(text, encoding="utf-8", newline="\n")
        else:
            shutil.copy2(src, target)
        written.append(rel)
    # the shipped config: a placeholder version of 运行配置.json, placed in 04-工具
    # The real config (ledger identity) lives only on the maintainer's machine. Without it, the structure-only
    # template is used. build_config() replaces every identity value anyway, so the packaged output is the same.
    cfg_src = SRC / "运行配置.json" if (SRC / "运行配置.json").is_file() else SRC / "运行配置.模板.json"
    cfg_target = dest / "04-工具" / "运行配置.json"
    cfg_target.write_text(build_config(cfg_src), encoding="utf-8", newline="\n")
    written.append("04-工具/运行配置.json")
    return written


def scan(dest: Path) -> list[str]:
    hits = []
    for f in sorted(dest.rglob("*")):
        if not f.is_file():
            continue
        if f.suffix not in (".md", ".txt", ".py", ".json"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for pat in FORBIDDEN:
            if pat in text:
                hits.append(f"{f.relative_to(dest)} 含禁止内容：{pat}")
    return hits


def main() -> int:
    check_only = "--check" in sys.argv
    if check_only:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "交付包"
            files = build(dest)
            hits = scan(dest)
            print(f"verified {len(files)} files in a temp build; forbidden hits: {len(hits)}")
            for h in hits:
                print("  ", h)
            return 1 if hits else 0
    files = build(OUT)
    hits = scan(OUT)
    print(f"wrote {len(files)} files to {OUT}")
    for f in files:
        print("  ", f)
    if hits:
        print("FORBIDDEN TEXT FOUND, package is not clean:")
        for h in hits:
            print("  ", h)
        return 1
    print("scan clean: no personal paths, no project ledger identity, no business names")
    return 0


if __name__ == "__main__":
    sys.exit(main())
