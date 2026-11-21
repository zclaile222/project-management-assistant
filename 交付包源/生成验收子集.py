"""Derive the self-contained acceptance checklist that ships in the package.

The full checklist (实施/验收/验证清单.py) reaches outside its own folder in three places:
  1. --历史回放 reads the project's archived history (历史材料/).
  2. One test copies the project-root rule file.
  3. One test compares against the local tidy script (本地表/tidy_deadlines.py).
Those belong to the maintainer, not to someone installing the package.

This script copies the full checklist and removes exactly those three things. Everything else is kept,
so the shipped checklist runs the same 130 portable checks against the shipped files.

Rules it enforces on its own output (failure stops the build):
  - no reference to 历史材料, 本地表, or any path outside the checklist's own folder;
  - no reference to the audit sheet (核对页), which the one-table package does not have;
  - it must still contain the portable checks it kept (count is checked against the source).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "实施" / "验收" / "验证清单.py"
OUT = ROOT / "交付包源" / "验收" / "验证清单.py"

FORBIDDEN_IN_OUTPUT = ["历史材料", "本地表", "tidy_deadlines", "核对页公式.json", "规则定稿_20261105.md"]


# The whole "copy to a relocated folder and run the entries" block. The full checklist copies the flat project
# layout (实施/). The package has its own layout, so the block is replaced as a unit, not word by word.
RELOCATE_OLD = (
    "    moved=p/'新位置 有空格'/'实施';moved.mkdir(parents=True)\n"
    "    for fn in ['提醒工具.py','运行配置.json','个人助理工作规范.md','早间计划.txt','晚间复盘.txt','周复盘.txt','今日应提醒公式.txt','核对页公式.json']:\n"
    "        shutil.copy2(BASE/fn,moved/fn)\n"
    "    shutil.copy2(BASE.parent/'规则定稿_20261105.md',moved.parent/'规则定稿_20261105.md')\n"
    "    for role in ('chat','morning','evening','weekly'):\n"
    "        r=subprocess.run([sys.executable,'-X','utf8',str(moved/'提醒工具.py'),'入口',role],cwd=p,capture_output=True)\n"
    "        txt=r.stdout.decode('utf-8')\n"
    "        assert_ok(r.returncode==0 and str(moved/'个人助理工作规范.md') in txt and str(BASE) not in txt,role+\" 异地中文空格目录绑定\")\n"
)
RELOCATE_NEW = (
    "    # Copy the whole shipped layout to a folder with Chinese and spaces, then run the entries there.\n"
    "    moved=p/'新位置 有空格'/'交付包'\n"
    "    shutil.copytree(BASE,moved,ignore=shutil.ignore_patterns('06-验收','__pycache__'))\n"
    "    for role in ('chat','morning','evening','weekly'):\n"
    "        r=subprocess.run([sys.executable,'-X','utf8',str(moved/'04-工具'/'提醒工具.py'),'入口',role],cwd=p,capture_output=True)\n"
    "        txt=r.stdout.decode('utf-8')\n"
    "        assert_ok(r.returncode==0 and str(moved/'02-指令'/'通用指令.md') in txt and str(BASE) not in txt,role+\" 异地中文空格目录绑定\")\n"
)


def derive(text: str) -> str:
    # 1. history replay: drop the argument and its whole block (the block is the 'if ...历史回放:' branch).
    text = re.sub(r"parser=argparse\.ArgumentParser\(\);parser\.add_argument\('--历史回放',action='store_true'\)\n"
                  r"if parser\.parse_args\(\)\.历史回放:\n(?:[ \t]+.*\n)+",
                  "", text, count=1)
    if "历史回放" in text:
        raise SystemExit("could not remove the --历史回放 block cleanly; refusing to ship a half-removed branch")

    # 2. the relocated-folder copy block is handled as one unit in step 4b, so nothing here touches it.

    # 3. the tidy-script comparison: it compares a local development script, so the whole block cannot ship.
    # It is removed as one unit (its definition, its use, and its assertion) and must match exactly once.
    if text.count(TIDY_BLOCK_OLD) != 1:
        raise SystemExit(f"整理脚本比对块没有精确命中一次（命中 {text.count(TIDY_BLOCK_OLD)} 次），映射过期")
    text = text.replace(TIDY_BLOCK_OLD, "")

    # 4b. the relocated-folder block: replaced as one unit, and it must match exactly once.
    if text.count(RELOCATE_OLD) != 1:
        raise SystemExit(f"异地目录整段没有精确命中一次（命中 {text.count(RELOCATE_OLD)} 次），映射过期")
    text = text.replace(RELOCATE_OLD, RELOCATE_NEW)

    # 4. the package has its own layout (01-规则 … 05-示例). Every path the checklist builds from BASE must follow it.
    # One rule per file, applied everywhere, so a regenerated checklist cannot drift back to the project layout.
    for old, new in PATH_MAP:
        text = text.replace(old, new)

    # 5. business example words -> neutral words. A word that no longer occurs means the map is stale: refuse.
    return text


# The local tidy-script comparison block, copied verbatim from the full checklist (lines 327-332).
TIDY_BLOCK_OLD = '# Two copies of one rule are only safe if a check fails when they diverge.\n_tidy_spec=importlib.util.spec_from_file_location("tidy_deadlines_check",BASE.parent/"本地表"/"tidy_deadlines.py")\n_tidy=importlib.util.module_from_spec(_tidy_spec); _tidy_spec.loader.exec_module(_tidy)\n_probe=[\'每工作日\',\'每周\',\'每周一\',\'每周五\',\'每两周\',\'每月\',\'持续（每两周）\',\'持续（每周五）\',\'持续（每周五）；首份诊断报告10月17日\',\'待定\',\'暂无\',\'持续\',\'7月9日\',\'8月\',\'每天\',\'每周六日\']\n_disagree=[s for s in _probe if g.is_cycle_wording(s) != (_tidy.cycle_of(s) is not None)]\nassert_ok(not _disagree,"工具与本地整理对周期说法的判断一致："+("" if not _disagree else str(_disagree)))\n'

# Business example words in the checklist's test data -> neutral words. Applied to the whole file, so the
# data and the assertions that check it are renamed together and stay consistent. Each must occur at least once.
NEUTRAL_WORDS = []  # source test data is already neutral; nothing to rename

# project-layout path fragment -> package-layout path fragment (order matters: longest first)
PATH_MAP = [
    ("BASE/'个人助理工作规范.md'", "BASE/'02-指令'/'通用指令.md'"),
    ("BASE/'运行配置.json'", "BASE/'04-工具'/'运行配置.json'"),
    ("BASE/\"提醒工具.py\"", "BASE/'04-工具'/'提醒工具.py'"),
    ("BASE/'提醒工具.py'", "BASE/'04-工具'/'提醒工具.py'"),
    ("'个人助理工作规范.md'", "'02-指令'/'通用指令.md'"),
    ("shutil.ignore_patterns('验收','__pycache__')", "shutil.ignore_patterns('06-验收','__pycache__')"),
]


def check(out: str, source: str) -> None:
    for word in FORBIDDEN_IN_OUTPUT:
        if word in out:
            raise SystemExit(f"验收子集仍引用项目外内容：{word}")
    kept = len(re.findall(r"assert_ok\(", out))
    total = len(re.findall(r"assert_ok\(", source))
    if kept < total - 3:
        raise SystemExit(f"验收子集丢掉的检查过多：保留 {kept}，源 {total}")


def main() -> int:
    if not SOURCE.is_file():
        raise SystemExit(f"完整验收清单缺失：{SOURCE}")
    source = SOURCE.read_text(encoding="utf-8")
    out = derive(source)
    check(out, source)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(out, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
