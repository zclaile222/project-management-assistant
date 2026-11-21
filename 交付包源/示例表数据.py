"""The sample rows for the first-run example table. Generic examples only, no real business content.

Each row is 12 cells A:L, plus M:O (结束日期、重点、周期) for the extended layout.
Dates are fixed to the sample base date below, so the example is stable and can be checked.
The expected 今天应提醒 (L) is stated per row and verified by the build against the tool's own rule.
"""
from datetime import date, timedelta

BASE = date(2026, 11, 17)
PREFIX = "DEMO"  # replaced by the user's own prefix at install time (START-HERE step 2 / table setup)


def d(offset):
    return (BASE + timedelta(days=offset)).isoformat()


# Columns: A 紧急程度 | B 事项 | C 详情 | D 启动时间 | E 计划完成时间 | F 协同部门/责任人 |
#          G 推进状态 | H 存在问题与协调 | I 任务编号 | J 提醒开关 | K 下次提醒日 | L 今天应提醒 |
#          M 结束日期 | N 重点 | O 周期
# L is left blank here: the tool computes it, and the build checks what it computes.
ROWS = [
    # 1 到日的重点事项：在办、开启、今天到日、标了重点 -> 1，排在清单最前
    dict(A="跟进中", B="示例：准备季度复盘报告", C="示例数据，可删除", D="", E=d(7), F="张三",
         G="1. 收集各项目数据\n2. 写初稿", H=f"{BASE.month}.{BASE.day} 示例：数据已收齐一半，等财务确认", I=f"{PREFIX}-0001",
         J="开启", K=d(0), M="", N="是", O="", expect="1"),
    # 2 到日的普通事项：没有截止日也能提醒 -> 1
    dict(A="高优先", B="示例：整理客户反馈清单", C="示例数据，可删除", D="", E="", F="李四",
         G="1. 汇总反馈", H=f"{BASE.month}.{BASE.day} 示例：反馈已汇入表格", I=f"{PREFIX}-0002",
         J="开启", K=d(0), M="", N="", O="", expect="1"),
    # 3 等待态：在等别人，不算结束，未到日不催 -> 0
    dict(A="已传递", B="示例：等待合作方确认方案", C="示例数据，可删除", D="", E="", F="王五",
         G="1. 等对方回复", H=f"{BASE.month}.{BASE.day} 示例：已发出方案，对方说周三前回复", I=f"{PREFIX}-0003",
         J="开启", K=d(3), M="", N="", O="", expect="0"),
    # 4 周期事项，今天到日 -> 1；O 填每周，K 是这一期的日期
    dict(A="跟进中", B="示例：每周五提交周报", C="示例数据，可删除", D="", E="", F="张三",
         G="1. 整理本周进展", H=f"{BASE.month}.{BASE.day} 示例：本周已提交", I=f"{PREFIX}-0004",
         J="开启", K=d(0), M="", N="", O="每周", expect="1"),
    # 5 周期事项已落后：到期日已过 -> 1，工具会在清单里提示下一期
    dict(A="项目", B="示例：每月对账", C="示例数据，可删除", D="", E="", F="赵六",
         G="1. 核对本月账目", H=f"{BASE.month}.{BASE.day} 示例：上月对账已完成", I=f"{PREFIX}-0005",
         J="开启", K=d(-7), M="", N="", O="每月", expect="1"),
    # 6 明确放一边：搁置 -> 搁置，不催，计入搁置件数
    dict(A="低优先", B="示例：调研行业报告", C="示例数据，可删除", D="", E="", F="孙七",
         G="1. 收集资料", H=f"{BASE.month}.{BASE.day} 示例：先放一边，暂不处理", I=f"{PREFIX}-0006",
         J="搁置", K="", M="", N="", O="", expect="搁置"),
    # 7 漏填提醒日：开启但没有日期 -> 待设置（表内异常，不是搁置）
    dict(A="(待处理)", B="示例：准备年度预算方案", C="示例数据，可删除", D="", E="", F="周八",
         G="1. 列出预算项", H=f"{BASE.month}.{BASE.day} 示例：还没约提醒日", I=f"{PREFIX}-0007",
         J="开启", K="", M="", N="", O="", expect="待设置"),
    # 8 停催但未结束：关闭 -> 0，不等于完成
    dict(A="跟进中", B="示例：更新产品说明文档", C="示例数据，可删除", D="", E="", F="吴九",
         G="1. 修订说明", H=f"{BASE.month}.{BASE.day} 示例：暂时不再提醒，但没有完成", I=f"{PREFIX}-0008",
         J="关闭", K="", M="", N="", O="", expect="0"),
    # 9 整件完成：已完成 -> 0，写结束日期
    dict(A="已完成", B="示例：发布活动海报", C="示例数据，可删除", D="", E=d(-5), F="郑十",
         G="1. 发布", H=f"{BASE.month}.{BASE.day} 示例：海报已发布", I=f"{PREFIX}-0009",
         J="关闭", K="", M=d(-5), N="", O="", expect="0"),
    # 10 整件取消：已取消 -> 0，原因写进 H
    dict(A="已取消", B="示例：评估新供应商", C="示例数据，可删除", D="", E="", F="冯一",
         G="1. 收集报价", H=f"{BASE.month}.{BASE.day} 示例：预算调整，不再推进，经验是先定预算", I=f"{PREFIX}-0010",
         J="关闭", K="", M=d(-10), N="", O="", expect="0"),
    # 11 交给别人结项：已转交结项 -> 0
    dict(A="已转交结项", B="示例：向外部团队交接的任务", C="示例数据，可删除", D="", E="", F="陈二",
         G="1. 已交接", H=f"{BASE.month}.{BASE.day} 示例：已交给外部团队，本人不再跟进", I=f"{PREFIX}-0011",
         J="关闭", K="", M=d(-3), N="", O="", expect="0"),
    # 12 合并到另一任务：已归并 -> 0
    dict(A="已归并", B="示例：与旧任务合并", C="示例数据，可删除", D="", E="", F="褚三",
         G="1. 已并入", H=f"{BASE.month}.{BASE.day} 示例：并入 {PREFIX}-0001", I=f"{PREFIX}-0012",
         J="关闭", K="", M=d(-14), N="", O="", expect="0"),
    # 13 故意的异常：状态不在规则列表里 -> 待核实（证明异常会被看见，不会被吞掉）
    dict(A="待跟进（示例异常）", B="示例：写客户案例", C="示例数据，可删除", D="", E="", F="卫四",
         G="1. 待定", H=f"{BASE.month}.{BASE.day} 示例：状态故意填了一个不认识的值", I=f"{PREFIX}-0013",
         J="开启", K=d(0), M="", N="", O="", expect="待核实"),
]

HEADER_A_TO_L = ["紧急程度", "事项", "详情", "启动时间", "计划完成时间", "协同部门/责任人",
                 "推进状态（数字代表步骤）", "存在问题与协调（数字代表日期）", "任务编号", "提醒开关", "下次提醒日", "今天应提醒"]
HEADER_EXTRA = ["结束日期", "重点", "周期"]
