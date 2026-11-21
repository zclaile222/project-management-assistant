"""V3.2: bind local paths or check fresh CLI exports. No network, writes, scheduler or delivery."""
import argparse
import calendar
import csv
import io
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
# The real run config holds this maintainer's ledger identity and stays on the local machine. A fresh copy has only the
# structure-only template: the tool still imports (so packaging can check it), but a placeholder token refuses to match
# any real export, so an unconfigured copy never reads a sheet it was not set up for.
_REAL = ROOT / "运行配置.json"
_TEMPLATE = ROOT / "运行配置.模板.json"
CONFIGURED = _REAL.is_file()
CFG = read(_REAL if CONFIGURED else _TEMPLATE)
# 搁置: the user has set the item aside on purpose (J 列 = 搁置). L shows it the same word, so both columns read alike.
# It is never a data error and is not reminded until the user picks a date again.
SHELVED = "搁置"
PARKED = SHELVED  # kept as the name the code already uses for this state
EXCEPTIONS = {SHELVED, "待设置", "待核实"}
ENDED = {"已完成", "完成", "已取消", "已转交结项", "已归并"}
# The in-progress statuses the formula accepts (规则第 3 节). Any other non-blank status is 待核实.
IN_PROGRESS = {"(待处理)", "（待处理）", "待处理", "高优先", "项目", "跟进中", "已传递", "低优先"}
# E written as one of these words means "no deadline"; it is a legitimate reading, not something the tool
# failed to read. Anything else non-blank that cell_day() cannot parse is a true blind spot (规则第 3 节).
PLACEHOLDERS = {"待定", "暂无", "持续", "无", "长期"}
# Cycle wording written into E (before the O column existed). Per 规则第 3 节 these are meant to be moved to O,
# so reading them is not a blind spot. Kept in step with tidy_deadlines.cycle_of() by the offline checks.
CYCLE_WORDS = {"每工作日": "每工作日", "每周": "每周", "每周一": "每周", "每周二": "每周", "每周三": "每周",
               "每周四": "每周", "每周五": "每周", "每周六": "每周", "每周日": "每周", "每两周": "每两周", "每月": "每月"}
_PAREN_CYCLE = re.compile(r"^持续[（(](每.+?)[）)]$")


def is_cycle_wording(text):
    """True when text is a cycle word, or 持续（每…） around one. Anything else is not a cycle."""
    if text in CYCLE_WORDS:
        return True
    m = _PAREN_CYCLE.match(text)
    return bool(m and m[1] in CYCLE_WORDS)
CELL_ERRORS = {"#REF!", "#N/A", "#VALUE!", "#DIV/0!", "#NUM!", "#NAME?", "#NULL!"}
HEAD = ["紧急程度","事项","详情","启动时间","计划完成时间","协同部门/责任人","推进状态（数字代表步骤）","存在问题与协调（数字代表日期）","任务编号","提醒开关","下次提醒日","今天应提醒"]
BASE_COLS = "ABCDEFGHIJKL"
# M:O were added in V3.2. A sheet whose M1:O1 are still empty predates them and is read as having no marks.
EXTRA_COLS = "MNO"
EXTRA_HEAD = ["结束日期", "重点", "周期"]
STAR = "是"
# The only cycles the panel and the assistant write. A cycle item's reminder date is the date of THIS period.
CYCLES = ("每工作日", "每周", "每两周", "每月")
# Weekday sessions report 搁置 as a count. The Saturday review, and a run without --场次, list every item.
FOLDED = {"morning", "evening"}
# The evening and Saturday sessions tidy up: they list items whose reminder date is far behind, plus what ended lately.
TIDY_SESSIONS = {"evening", "weekly"}
STALE_DAYS = 7     # a reminder date this many days behind makes an item a tidy-up candidate
RECENT_DAYS = 14   # items that ended within this many days are shown, to compare direction with the stale ones

def require(ok, msg):
    if not ok:
        raise ValueError(msg)

def payload(source):
    p = source.get("data", source)
    require(isinstance(p,dict) and source.get("ok",True) is not False and
            source.get("complete",True) is not False and not source.get("truncated") and
            p.get("has_more") is False and not p.get("truncated"), "读取失败、截断或非完整导出")
    require(CONFIGURED, "尚未配置台账：请先在本机创建运行配置.json，填入表格标识（见交付包 START-HERE 第 5 步）")
    require(p.get("token")==CFG["ledger"]["spreadsheet_token"] and p.get("revision") is not None,
            "不是配置的工作簿或缺少 revision")
    return p

def page(p, required):
    cols, nums = p["col_indices"], p["row_indices"]
    require(isinstance(cols,list) and len(cols)==len(set(cols)) and all(c in cols for c in required),
            "读表缺列或列重复")
    require(isinstance(nums,list) and nums and nums==list(range(nums[0],nums[-1]+1)), "行缺失、重复或顺序异常")
    bounds = re.fullmatch(r"([A-Z]+)([0-9]+):([A-Z]+)([0-9]+)",p["actual_range"])
    require(bounds and (bounds[1],int(bounds[2]),bounds[3],int(bounds[4]))==
            (cols[0],nums[0],cols[-1],nums[-1]),"实际范围与坐标不符")
    positions = [cols.index(c) for c in required]
    records = list(csv.reader(io.StringIO(p["annotated_csv"],newline=""), strict=True))
    require(len(nums)==len(records),"行坐标与 CSV 不符")
    out = dict()
    for n,r in zip(nums,records):
        require(len(r)==len(cols),"行列不齐")
        m=re.match(r"^\[row=(\d+)\] ?",r[0])
        require(m and int(m[1])==n,"实际行标注缺失或不符")
        r[0]=r[0][m.end():]
        out[n]=[r[i] for i in positions]
    return out

def day(value):
    val=value.strip()
    if re.fullmatch(r"[0-9]{1,7}(?:\.0+)?",val):
        return date(1899,12,30)+timedelta(days=int(float(val)))
    for fmt in ("%Y-%m-%d","%Y/%m/%d"):
        try: return datetime.strptime(val,fmt).date()
        except ValueError: pass
    raise ValueError("核对页 L6 不是可核实的完整日期")

def one_line(value):
    # Keep source text on one physical line, never turn in-cell paragraphs into extra task records.
    return " / ".join(x.strip() for x in str(value).splitlines() if x.strip())

def top_step(text):
    return next((s.strip() for s in text.splitlines() if s.strip()),"")

def cell_day(text):
    """A full date read from a cell's displayed text, or None. A month-day with no year is never guessed."""
    val=text.strip()
    if re.fullmatch(r"\d{5}",val) and 40000<=int(val)<=80000:
        return date(1899,12,30)+timedelta(days=int(val))
    m=re.fullmatch(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?",val)
    if m:
        try: return date(int(m[1]),int(m[2]),int(m[3]))
        except ValueError: return None
    return None

def add_months(d,n):
    m=d.month-1+n; y=d.year+m//12; mo=m%12+1
    return date(y,mo,min(d.day,calendar.monthrange(y,mo)[1]))

def next_period(cycle,k,today):
    """The next date on the cycle that falls after both today and k. k is the date of the period being closed."""
    require(cycle in CYCLES,"周期只认："+"、".join(CYCLES))
    base=max(today,k)
    if cycle=="每工作日":
        d=base+timedelta(days=1)
        while d.weekday()>=5: d+=timedelta(days=1)
        return d
    if cycle in ("每周","每两周"):
        step=7 if cycle=="每周" else 14
        return k+timedelta(days=step*((base-k).days//step+1))
    n=1
    while add_months(k,n)<=base: n+=1
    return add_months(k,n)

def compute_l(row, id_count, today):
    """Today's reminder value for one row, computed by the tool from A, B, I, J, K.

    This is the same decision the sheet formula makes (今日应提醒公式.txt), in the same order, so the tool
    can stand in for the formula. row is the 12-cell A:L record; id_count is how many rows share this row's ID.
    Returns "" for a blank row, "待核实", "0", "1", "搁置", or "待设置".
    """
    a,b,c,d,e,f,g,h,tid,j,k = (row+[""]*12)[:11]
    if not any(str(x).strip() for x in row[:11]):
        return ""
    if not b.strip() or not str(tid).strip() or " " in str(tid) or id_count!=1:
        return "待核实"
    if a in ENDED or j=="关闭":
        return "0"
    if a not in IN_PROGRESS:
        return "待核实"
    if j==SHELVED:
        return PARKED
    if j!="开启":
        return "待设置"
    if not k.strip():
        return "待设置"
    d_ = cell_day(k)
    if d_ is None:
        return "待核实"
    return "1" if d_<=today else "0"

def id_problem(title, tid, count):
    """Why a row's identity cannot be used, in words a person can act on. Checked in the same order as the tool."""
    if not str(title).strip() or title in CELL_ERRORS:
        return "没有事项名，系统不知道这是什么事"
    if not tid or tid in CELL_ERRORS:
        return "没有编号，系统找不到它，请补一个编号"
    if any(c.isspace() for c in tid):
        return "编号里有空格，请去掉"
    if count[tid.casefold()]!=1:
        return "编号和另一件事重复，请换一个"
    return "状态或日期看不懂，需要确认"

def in_progress_not_due(row, today):
    """True when a row is an open item in progress whose reminder date is still in the future.

    This is the group the morning and evening lists summarise in one short paragraph. It uses the same reading
    of A, J and K as compute_l, so the paragraph and the due list never overlap:
      - an end status (已完成 etc.) or J=关闭 is not in progress;
      - J=搁置 belongs to the 搁置 group;
      - J=开启 with K empty is a missing reminder date, and K that is not a date is unreadable: both go to 需要先补的事.
    """
    a,j,k=(row+["","",""])[0],(row+["","",""])[9],(row+["","",""])[10]
    if a in ENDED or j!="开启" or a not in IN_PROGRESS:
        return False
    d_=cell_day(k)
    return d_ is not None and d_>today

def checked_block(sheets, control, grid_rows, today, draft=None, session=None):
    rows=dict(); widths=set()
    # Every main-table page must share one revision. That revision is the version this list is about.
    revision=payload(sheets[0])["revision"]
    require(type(grid_rows) is int and grid_rows>=1,"缺真实网格行数")
    require(session is None or session in CFG["entries"],"未知场次")
    for source in sheets:
        p=payload(source)
        require(p["revision"]==revision,"快照版本不同，重读同一版本")
        cols=p["col_indices"]
        have=[c for c in EXTRA_COLS if isinstance(cols,list) and c in cols]
        require(len(have) in (0,len(EXTRA_COLS)),"主表只读到部分新增列，应同时读到 M、N、O")
        letters=BASE_COLS+"".join(have)
        widths.add(letters)
        part=page(p,letters)
        require(not(rows.keys() & part.keys()),"主表分页重叠")
        rows.update(part)
    require(len(rows)==grid_rows and min(rows,default=0)==1 and max(rows,default=0)==grid_rows,
            "没有覆盖从首行到网格末行的完整表")
    require(len(widths)==1,"主表各分片读到的列范围不一致")
    head=rows.pop(1)
    require(head[:12]==HEAD,"A:L 表头与配置的工作表不符")
    extra=[x.strip() for x in head[12:]]
    require(extra in ([],[""]*len(EXTRA_COLS),EXTRA_HEAD),"M:O 表头不是约定的“结束日期、重点、周期”")
    marked=extra==EXTRA_HEAD
    # The audit page is optional. Acceptance passes it to cross-check the sheet's own totals.
    # Daily use omits it: the counts and the due-ID list are then recomputed from the rows (below).
    ctl=None
    if control is not None:
        m=payload(control)
        require(m["revision"]==revision,"核对页与主表不是同一版本")
        ctl=page(m,["L"])
        require(set(ctl)==set(range(1,11)) and "应提醒" in ctl[1][0] and "编号" in ctl[9][0],
                "核对页不是约定的 L1:L10")
        require(day(ctl[6][0])==today,"核对页日期不等于本次北京时间日期")
    count=Counter(r[8].casefold() for r in rows.values() if r[8])
    due=dict(); starred=set(); parked=[]; problems=[]; odd=[]; odd_cycle=[]; recent=[]; e_blind=[]; ahead_ids=[]; id_reasons={}
    for n,r in sorted(rows.items()):
        a,b,c,d,e,f,g,h,tid,j,k,l=r[:12]
        # Blind spot in the deadline column: text the tool cannot read as a date and that is not a placeholder.
        # Reported, never used for reminders (a deadline never triggers one). Empty and placeholder cells are not reported.
        e_text=e.strip()
        if e_text and e_text not in PLACEHOLDERS and not is_cycle_wording(e_text) and cell_day(e_text) is None:
            e_blind.append((n,tid,b,e_text))
        if not any(r[:11]):
            require(l=="",f"空行 {n} 返回了非空 L");continue
        require(l in EXCEPTIONS|{"0","1"},f"第 {n} 行 L 缺失或错误，不能发正常清单")
        if not b.strip() or b in CELL_ERRORS or not tid or tid in CELL_ERRORS or any(c.isspace() for c in tid) or count[tid.casefold()]!=1:
            require(l=="待核实",f"第 {n} 行标识异常但 L 未标待核实")
            id_reasons[n]=id_problem(b,tid,count)
        elif a in ENDED or j=="关闭":
            require(l=="0",f"第 {n} 行已结束或停催，但 L 不为 0")
        mark=r[13].strip() if marked else ""
        star=mark==STAR
        # An unrecognised mark never hides an item: the item is listed as an ordinary one and the cell is reported.
        if mark and not star: odd.append((n,tid,b))
        cycle=r[14].strip() if marked else ""
        if cycle and cycle not in CYCLES: odd_cycle.append((n,tid,b))
        if marked and l=="0" and a in ENDED:
            end=cell_day(r[12])
            if end and 0<=(today-end).days<=RECENT_DAYS: recent.append((end,n,tid,b))
        if l==PARKED:
            parked.append((n,tid,r,star));continue
        if l in EXCEPTIONS:
            problems.append((n,tid,b,l));continue
        if l=="1":
            due[tid]=(n,r)
            if star: starred.add(tid)
        # Second part of the list: in progress and reminder date still ahead. Read from the same A, J, K as the rule.
        if in_progress_not_due(r[:11], today): ahead_ids.append(tid)
    if ctl is not None:
        def integer(pos):
            v=ctl[pos][0].strip()
            require(bool(re.fullmatch(r"\d+",v)),f"核对页 L{pos} 非整数")
            return int(v)
        require(integer(2)==len(due) and integer(4)==len(parked)+len(problems),
                "核对页与主表的应覆盖数，或搁置加字段异常的行数不符")
        ids=ctl[10][0].strip()
        # Existing workpaper joins IDs with 、; 无 is the empty-set sentinel.
        require(bool(ids),"核对页 L10 缺失，不能把空白当作无任务")
        ref=[] if ids=="无" else [i.strip() for i in ids.split("、")]
        require(Counter(ref)==Counter(due.keys()),"核对页与主表的应覆盖编号不符或重复")
    held=dict()
    if draft is not None:
        require(isinstance(draft,dict) and draft.get("revision")==revision,"草稿并非同一版快照")
        for q in draft.get("review",[]):
            tid=q["id"]
            require(tid in due and tid not in held and q.get("column") in ("C","G","H"),"到日待核项不属于本次集合或重复")
            n,r=due[tid]; col=ord(q["column"])-65
            require(q.get("row")==n and q.get("title")==r[1] and q.get("quote","").strip() and
                    q["quote"] in r[col] and q.get("reason","").strip(),"待核实缺少可回查的本行证据")
            held[tid]=one_line(q["reason"])
    active=[i for i in due if i not in held]
    if draft is not None and "items" in draft:
        wanted=draft["items"]
        require(isinstance(wanted,list) and Counter(x["id"] for x in wanted)==Counter(active),"最终草稿漏项、多项或重复")
        require(all(x["title"]==due[x["id"]][1][1] for x in wanted),"编号与事项标题错配")
        active=[x["id"] for x in wanted]
    def due_line(tid):
        n,r=due[tid]
        step=top_step(r[6])
        if not step:
            action="尚未登记当前动作，这件事接下来怎么处理？"
        elif re.search(r"^(?:\d+[.、)）]\s*)?(?:✅|☑|\[x\])|(?:✅|☑|\[x\])$",step,re.I):
            action="置顶步骤已标完成，剩余工作还需确认。这件事接下来怎么处理？"
        else:
            action=step
        hint=hints(r)
        # One question per line. A cycle or overdue hint, or an action that already asks, carries its own question;
        # only a plain step gets the standard question at the end.
        carries_question = bool(hint) or action.endswith("？")
        question="" if carries_question else "｜今天推哪一步？"
        return f"- [{one_line(tid)}] {one_line(r[1])}｜{action}{question}{hint}"
    def hints(r):
        out=[]
        cycle=r[14].strip() if marked else ""
        k=cell_day(r[10]); e=cell_day(r[4])
        if cycle in CYCLES and k is not None and k<today:
            out.append(f"{cycle}，这一期应是{k.isoformat()}，已落后{(today-k).days}天；这期做了的话，提醒日可改到{next_period(cycle,k,today).isoformat()}")
        # A deadline is only compared when it is a full date. Text such as 待定 or 每周 is never read as a date.
        if e is not None and e<today and r[0] not in ENDED:
            out.append(f"已过截止日{(today-e).days}天：改日期、取消，还是换成别的事？")
        return "｜"+"｜".join(out) if out else ""
    def parked_line(item,tag):
        n,tid,r,star=item
        return f"- [{one_line(tid)}] {one_line(r[1])}{'（重点）' if tag and star else ''}｜{top_step(r[6]) or '尚未登记当前动作'}"
    # Construct fixed output from the checked snapshot. It is not rewritten by the LLM afterwards.
    # Three parts, in order: what to act on today; the in-progress items not yet due (one short paragraph);
    # what needs filling in first (only when there is something). The counts above are unchanged by this layout.
    out=[f"应覆盖 {len(due)}｜正常列出 {len(active)}｜到日待核 {len(held)}｜搁置 {len(parked)}｜表内异常 {len(problems)}"]
    check_text="核对页 通过" if ctl is not None else "行内核对 通过"
    # Part 1: today's items, important first, no sub-headings. Each line ends with the question for that item.
    first=[i for i in active if i in starred]; rest=[i for i in active if i not in starred]
    out.extend(due_line(i) for i in first+rest)
    # Part 2: in progress, reminder date still ahead. One paragraph: the count and the ids, never one line per item.
    # The set comes from in_progress_not_due() applied to every row, so it is the rule's own group, not a guess.
    if ahead_ids:
        ids="、".join(one_line(x) for x in ahead_ids)
        out.append(f"另外还有 {len(ahead_ids)} 件事在进行中，暂时不用管。编号 {ids}")
    if parked and session in FOLDED:
        out.append(f"搁置 {len(parked)} 件（没约日子），这几天不逐条列出，周六一起看。")
        keep=[x for x in parked if x[3]]
        if keep: out.append("搁置中的重点")
        out.extend(parked_line(x,False) for x in keep)
    elif parked:
        out.append(f"搁置 {len(parked)} 件（没约日子）")
        out.extend(parked_line(x,True) for x in sorted(parked,key=lambda x:not x[3]))
    # Part 3: what needs filling in first. Shown only when there is something to fill in.
    # Display only: the L value and the count do not change. 待设置 covers two cases: J is 开启 and K is empty
    # (a missing reminder date), or J holds a value other than 开启, 搁置 or 关闭.
    REASON_TEXT={"待设置":"没填提醒日，约个日子或改成搁置","待核实":"状态或日期看不懂，需要确认"}
    fill=[]
    for tid,why in held.items():
        n,r=due[tid]
        fill.append(f"- {('['+one_line(tid)+']') if tid else '缺编号'} {one_line(r[1]) or '缺事项名'}：{why}，先确认，暂不催它")
    for n,tid,title,reason in problems:
        why=id_reasons.get(n) or REASON_TEXT.get(reason,reason)
        fill.append(f"- {('['+one_line(tid)+']') if tid else '缺编号'} {one_line(title) or '缺事项名'}：{why}")
    for n,tid,title in odd:
        fill.append(f"- {('['+one_line(tid)+']') if tid else '缺编号'} {one_line(title) or '缺事项名'}：重点这一列填了别的内容，只认“{STAR}”")
    for n,tid,title in odd_cycle:
        fill.append(f"- {('['+one_line(tid)+']') if tid else '缺编号'} {one_line(title) or '缺事项名'}：周期这一列填了别的内容，只认"+"、".join(CYCLES))
    for n,tid,title,text in e_blind:
        fill.append(f"- {('['+one_line(tid)+']') if tid else '缺编号'} {one_line(title) or '缺事项名'}：截止日写的是「{one_line(text)}」，看不出年份，系统看不出它有没有过期，不影响提醒")
    if fill:
        out.append(f"需要先补的事（{len(fill)} 件）")
        out.extend(fill)

    if session in TIDY_SESSIONS:
        out.extend(tidy_block(due,parked,starred,recent,today,session))
    require(len(active)+len(held)==len(due) and set(active).isdisjoint(held),"覆盖分组内部错误")
    # Closing line, in plain words: what day it checked, and how many deadlines it could not read. It never changes the list.
    closing=f"数据已核对，今天 {today.strftime('%m-%d')}"
    if e_blind: closing+=f"，{len(e_blind)} 处日期看不懂，不影响提醒"
    out.append(closing)
    return "\n".join(out)

def tidy_block(due,parked,starred,recent,today,session):
    """A ranked list for the evening and Saturday tidy-up. Programme-ranked; the assistant only reads it, never re-ranks.

    Candidates: reminder date at least STALE_DAYS behind, or a full-date deadline already passed. Order: starred first,
    then the largest gap. Cycle items are left out: the 周期 hint on the main list already covers them.
    The whole list is always printed. Nothing is truncated: a cap would hide the items that have waited longest.
    How many items the assistant asks about in one evening is the user's preference, not a property of this list.
    """
    cands=[]
    def consider(n,tid,r,star,listed):
        k=cell_day(r[10]); e=cell_day(r[4])
        late_k=(today-k).days if k is not None and k<today else 0
        late_e=(today-e).days if e is not None and e<today else 0
        cycle=r[14].strip() if len(r)>14 else ""
        if cycle in CYCLES: return
        if late_k>=STALE_DAYS or late_e>0:
            cands.append((not star,-max(late_k,late_e),n,tid,r,star,late_k,late_e))
    for tid,(n,r) in due.items():
        consider(n,tid,r,tid in starred,True)
    ranked=sorted(cands)
    out=[]
    if ranked:
        out.append(f"可以考虑整理的事（提醒日落后超过一周，或已过截止日；重点在前，落后最久的在前）：共 {len(ranked)} 件，全部列出")
        for _,_,n,tid,r,star,late_k,late_e in ranked:
            facts=[]
            if late_k: facts.append(f"提醒日落后{late_k}天")
            if late_e: facts.append(f"已过截止日{late_e}天")
            out.append(f"- [{one_line(tid)}] {one_line(r[1])}{'（重点）' if star else ''}｜{'；'.join(facts)}｜{top_step(r[6]) or '尚未登记当前动作'}")
    recent=sorted(recent,reverse=True)
    if recent:
        out.append(f"最近完成的事（对照一下，看是否和上面的事相关）：共 {len(recent)} 件，全部列出")
        for end,n,tid,b in recent:
            out.append(f"- [{one_line(tid)}] {one_line(b)}｜结束于{end.isoformat()}")
    return out

def entry(key):
    cfg=CFG; e=cfg["entries"].get(key)
    # resolve() removes the ".." that the config's relative paths carry, so the binding text shows a clean path.
    common=(ROOT/cfg["common"]).resolve(); config=(ROOT/"运行配置.json").resolve()
    # control_formulas is optional: a one-table deployment has no audit page, so there is no such file.
    for item in ("common","rules","formula"):
        require((ROOT/cfg[item]).is_file(),f"本机规则/运行文件缺失：{cfg[item]}")
    if "control_formulas" in cfg:
        require((ROOT/cfg["control_formulas"]).is_file(),f"本机规则/运行文件缺失：{cfg['control_formulas']}")
    if key=="chat":
        body="日常自然对话：按通用指令的“对话与写回”办理，查询只读。"
    else:
        require(e is not None,"未知入口")
        body=(ROOT/e["file"]).read_text(encoding="utf-8-sig").strip()
        days="、".join("一二三四五六日"[n-1] for n in e["weekdays"])
        body+=f"\n本入口的预期触发：北京时间周{days} {e['time']}；实际调度在运行定时任务的应用里配置。"
    return f"本机绑定（V{cfg['version']}）：先读取《{common}》及《{config}》。\n"+body

def main():
    cli=argparse.ArgumentParser(description=__doc__); sub=cli.add_subparsers(dest="cmd",required=True)
    b=sub.add_parser("入口"); b.add_argument("key",choices=["chat",*CFG["entries"]])
    c=sub.add_parser("清单"); c.add_argument("--台账",nargs="+",required=True)
    c.add_argument("--核对页",required=False,help="可选。验收时用于交叉核对；日常使用不需要单独的核对表。")
    c.add_argument("--网格行数",required=True,type=int);c.add_argument("--草稿")
    c.add_argument("--场次",choices=list(CFG["entries"]))
    n=sub.add_parser("下一期",help="算周期事项的下一期日期。例：下一期 --周期 每两周 --提醒日 2026-11-04")
    n.add_argument("--周期",required=True,choices=list(CYCLES)); n.add_argument("--提醒日",required=True)
    args=cli.parse_args()
    try:
        require(CFG.get("timezone")=="Asia/Shanghai" and CFG.get("version")=="3.2","配置时区或版本不匹配")
        today=datetime.now(timezone(timedelta(hours=8))).date()
        if args.cmd=="入口": result=entry(args.key)
        elif args.cmd=="下一期":
            k=cell_day(args.提醒日)
            require(k is not None,"提醒日必须是带年份的完整日期，如 2026-11-04")
            result=next_period(args.周期,k,today).isoformat()
        else:
            result=checked_block([read(x) for x in args.台账],read(args.核对页) if args.核对页 else None,args.网格行数,today,
                    read(args.草稿) if args.草稿 else None,args.场次)
        print(result)
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError,OverflowError,csv.Error) as ex:
        print(f"未核齐：{ex}。不发布正常清单。",file=sys.stderr);return 2
    return 0

if __name__=="__main__":
    raise SystemExit(main())
