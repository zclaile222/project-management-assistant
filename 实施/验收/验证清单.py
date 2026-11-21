"""Offline regression checks against real export shapes. No Feishu or scheduler calls."""
import copy
import argparse
import csv
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import re
from datetime import date, timedelta
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("ledger_check",BASE/"提醒工具.py")
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
DAY=date(2026,11,18)
passed=[]

def export(cols, rows, start=1, revision=317):
    s=io.StringIO(newline=""); w=csv.writer(s,lineterminator="\n")
    for n,row in enumerate(rows,start):
        r=[str(x) for x in row]; r[0]=f"[row={n}] "+r[0];w.writerow(r)
    ns=list(range(start,start+len(rows)))
    return dict(annotated_csv=s.getvalue(),col_indices=list(cols),row_indices=ns,
            actual_range=f"{cols[0]}{ns[0]}:{cols[-1]}{ns[-1]}",revision=revision,
            has_more=False,token=g.CFG["ledger"]["spreadsheet_token"])

def pe_count(rows):
    # parked + field exceptions, read from the rows rather than typed in each assertion
    return sum(1 for r in rows[1:] if r[11] in ('搁置','待设置','待核实'))
def ref(ids,count,rev=317,asof=DAY):
    vals=["正式表今日应提醒",len(ids),"正式表搁置/核实",count,"计算日期",asof.isoformat(),"验算结果（模拟）","旧案例非业务","今日必提醒编号","、".join(ids) or "无"]
    return export("L",[[v] for v in vals],revision=rev)

def item(id_,title,mark,*,state='项目',switch='开启',step='当前动作',k='2026-11-18'):
    return [state,title,"","", "", "", step,"",id_,switch,k,mark]

base_rows=[g.HEAD,
            item('ZC-0001','示例报告','1',step='发布稿件\n历史步骤，保留'),
            item('ZC-0002','示例任务B','1'),
            item('ZC-0003','客户画像','1',step='进博会展商对接'),
            item('ZC-0004','搁置事项','搁置',switch='搁置',k=''),
            item('ZC-0009','漏填提醒日','待设置',k=''),
            item('ZC-0005','已转交','0',state='已转交结项'),
            item('','缺编号','待核实'),
            item('ZC-dup','重号一','待核实'),item('zc-DUP','重号二','待核实'),
            item('ZC-0008','已停催','0',switch='关闭'),['']*12]
base=[export('ABCDEFGHIJKL',base_rows)]
# parked + field exceptions are counted from the fixture itself, not typed by hand:
_pe=sum(1 for r in base_rows[1:] if r[11] in ('搁置','待设置','待核实'))
audit=ref(['ZC-0001','ZC-0002','ZC-0003'],_pe)
hold=dict(id="ZC-0003",title="客户画像",row=4,column="G",quote="进博会展商对接",reason="事项名与展商动作错配")
def run(p=None,c=None,**kwargs):
    return g.checked_block(base if p is None else p,audit if c is None else c,
            kwargs.get('grid',len(base_rows)),kwargs.get('day',DAY),kwargs.get('draft'),kwargs.get('session'))
def body_lines(txt):
    """The lines after the summary line and the health line. Found by content, not by position."""
    lines=txt.splitlines()
    return [x for x in lines[1:] if not x.startswith("数据已核对，今天")]
def assert_ok(ok,name):
    if not ok:raise AssertionError(name)
    passed.append(name)
def reject(name,call):
    try: call()
    except (ValueError,KeyError,TypeError):passed.append(name)
    else: raise AssertionError("应拒绝："+name)
def altered(obj,**changes): return dict(obj,**changes)
def draft(ids):return dict(revision=317,items=[dict(id=i,title=dict((r[8],r[1]) for r in base_rows).get(i,'其他')) for i in ids])
def wide(rows,marks=None,head=None):
    # The same rows as a sheet that has the V3.2 columns M:O; marks maps a task id to its N cell.
    marks=marks or dict()
    out=[list(rows[0])+list(g.EXTRA_HEAD if head is None else head)]
    for r in rows[1:]:
        out.append(list(r)+["",marks.get(r[8],""),""])
    return [export('ABCDEFGHIJKLMNO',out)]

block=run()
SUMMARY="应覆盖 3｜正常列出 3｜到日待核 0｜搁置 1｜表内异常 4"
assert_ok(block.splitlines()[0]==SUMMARY and
            "已停催" not in block and "已转交" not in block and "发布稿件" in block and "历史步骤" not in block,"原样固定清单、置顶动作，搁置与字段异常分开计数")
_row=lambda n: base_rows.index(n)+1   # physical row = list position + 1 (row 1 is the header)
# Rows without a usable ID are found by their title in the "需要先补的事" part. The row number is no longer printed.
_fill_part=block.split("需要先补的事")[1] if "需要先补的事" in block else ""
_empty_title=next(r[1] for r in base_rows if r[8]=='')
_dup_titles=[next(r[1] for r in base_rows if r[8]=='ZC-dup'),next(r[1] for r in base_rows if r[8]=='zc-DUP')]
assert_ok(_fill_part and _empty_title in _fill_part and all(t in _fill_part for t in _dup_titles),"缺号与两个重号的行都在“需要先补的事”里，靠事项名可找到")
assert_ok("本次行" not in block,"输出不再印行号，只印编号和事项名")
assert_ok("搁置 1 件（没约日子）" in block and "- [ZC-0004] 搁置事项｜当前动作" in block and "需要先补的事" in block and block.index("搁置 1 件")<block.index("需要先补的事"),"不带场次时搁置逐条列出，排在需要先补的事之前")
# The summary line also contains 表内异常; split on the section heading that now holds the fill-in items.
_parked_part=block.split("搁置 1 件")[1].split("需要先补的事")[0]
_exc_part=block.split("需要先补的事")[1]
assert_ok("ZC-0009" not in _parked_part and "[ZC-0009] 漏填提醒日：没填提醒日，约个日子或改成搁置" in _exc_part,"开启但没有提醒日的，归入需要先补的事（漏填），不进搁置")
for name in ('morning','evening'):
    txt=run(session=name)
    assert_ok(txt.splitlines()[0]==SUMMARY and "搁置 1 件（没约日子），这几天不逐条列出" in txt and "ZC-0004" not in txt and
            all(f"[{i}]" in txt for i in ('ZC-0001','ZC-0002','ZC-0003')) and "需要先补的事" in txt and next(r[1] for r in base_rows if r[8]=='') in txt.split("需要先补的事")[1],name+" 场搁置只报件数，到日项、字段异常与计数不变")
assert_ok(run(session='weekly')==block,"周复盘逐条列出搁置")
reject("未知场次",lambda:run(session='noon'))
held_order=dict(draft(['ZC-0002','ZC-0001']),review=[hold])
block=run(draft=held_order)
assert_ok("正常列出 2｜到日待核 1｜搁置 1｜表内异常 4" in block and block.count('[ZC-0003]')==1 and
            "｜进博会展商对接" not in block and block.index('[ZC-0002]')<block.index('[ZC-0001]'),"错配只列一次，暂缓不冒充已催；允许安全排序")
for name,ids in [('等数量但重复/漏项',['ZC-0001','ZC-0002','ZC-0002']),('草稿漏项',['ZC-0001']),
            ('混入未来或已闭环项',['ZC-0001','ZC-0002','ZC-0003','ZC-0005'])]:
    reject(name,lambda ids=ids:run(draft=draft(ids)))
x=draft(['ZC-0001','ZC-0002','ZC-0003']);x['items'][0]['title']='错标题'
reject("标题与编号错配",lambda:run(draft=x))
for label,bad in [('待核证据不在本行',dict(quote='不存在的原话')),('待核行坐标已过时',dict(row=2)),
            ('待核理由空白',dict(reason='  ')),('待核目标不在本轮',dict(id='ZC-0008'))]:
    reject(label,lambda bad=bad:run(draft=dict(revision=317,review=[dict(hold,**bad)])))
reject("待核组重复",lambda:run(draft=dict(revision=317,review=[hold,hold])))
reject("正常与到日待核相互污染",lambda:run(draft=dict(draft(['ZC-0001','ZC-0002','ZC-0003']),review=[hold])))
reject("草稿快照版本不符",lambda:run(draft=dict(revision=316)))
for label,replace in [('截断',dict(has_more=True)),('版本漂移',dict(revision=316)),('错误工作簿',dict(token='other')),
            ('隐藏列未读',dict(col_indices=list('ABCDEFGHIJK'))),('缺行坐标',dict(row_indices=[1,2,4])),
            ('坐标范围不符',dict(actual_range='A1:L9')),('实际行标注错位',dict(annotated_csv=base[0]['annotated_csv'].replace('[row=2]','[row=3]',1)))]:
    reject(label,lambda replace=replace:run([altered(base[0],**replace)]))
reject("核对页日期过期",lambda:run(day=date(2026,11,19)))
reject("核对页计数不符",lambda:run(c=ref(['ZC-0001','ZC-0002','ZC-0003'],3)))
reject("核对页编号同数量但错误",lambda:run(c=ref(['ZC-0001','ZC-0002','ZC-0002'],4)))
reject("分页有重叠",lambda:run([base[0],base[0]]))
reject("固定范围被误认为全表",lambda:run(grid=201))
rr=copy.deepcopy(base_rows);rr[5][-1]='1'
reject("终态误留开启仍进入清单",lambda:run([export('ABCDEFGHIJKL',rr)]))
rr=copy.deepcopy(base_rows);rr[2][-1]=''
reject("业务行 L 缺失",lambda:run([export('ABCDEFGHIJKL',rr)]))
rr=copy.deepcopy(base_rows);rr[-1][-1]='0'
reject("完全空行被错计",lambda:run([export('ABCDEFGHIJKL',rr)]))
rr=[g.HEAD]+[['']*12 for _ in range(199)]+[item('ZC-0201','跨过空行后的任务','1')]
pg=[export('ABCDEFGHIJKL',rr[:100]),export('ABCDEFGHIJKL',rr[100:],101)]
assert_ok("跨过空行后的任务" in run(pg,ref(['ZC-0201'],0),grid=201),"同版本分片覆盖第201行及中间空行")
assert_ok("应覆盖 0" in run([export('ABCDEFGHIJKL',[g.HEAD,['']*12])],ref([],0),grid=2),"真实空表可报告零")
emptyrefs=[['正式表今日应提醒'],['0'],['正式表搁置/核实'],['0'],['计算日期'],[DAY.isoformat()],['验算结果'],['旧案例'],['今日必提醒编号'],['']]
reject("空集合与被清掉的 L10 不混淆",lambda:run([export('ABCDEFGHIJKL',[g.HEAD,['']*12])],export('L',emptyrefs),grid=2))
rr=copy.deepcopy(base_rows);rr[1][6]="1. ✅ 示例工具已修好\n示例报告尚未发布"
txt=run([export('ABCDEFGHIJKL',rr)])
assert_ok("置顶步骤已标完成" in txt and "✅ 示例工具" not in txt,"不把已勾掉的置顶步骤重新当成剩余动作")
# V3.2 columns M:O (结束日期, 重点, 周期). 重点 changes order and display only, never what is covered.
plain=run()
assert_ok(run(wide(base_rows))==plain,"加了三列表头但没有标记时，清单与旧表完全一样")
txt=run(wide(base_rows,dict([('ZC-0002','是')])));rows_out=body_lines(txt)
assert_ok(txt.splitlines()[0]==SUMMARY and rows_out[0].startswith("- [ZC-0002] 示例任务B") and "重点" not in rows_out and
            txt.count("[ZC-0002]")==1 and all(f"[{i}]" in txt for i in ('ZC-0001','ZC-0003')),"重点事项排在到日的最前、只列一次，不另起小标题，覆盖与计数不变")
assert_ok(run(wide(base_rows,dict([('ZC-0005','是'),('ZC-0008','是')])))==plain,"重点不让已结束或已停催的事重新出现")
txt=run(wide(base_rows,dict([('ZC-0004','是')])),session='morning')
assert_ok("这几天不逐条列出" in txt and "搁置中的重点" in txt and "- [ZC-0004] 搁置事项｜当前动作" in txt,"搁置里的重点在工作日仍逐条可见")
assert_ok("- [ZC-0004] 搁置事项（重点）｜当前动作" in run(wide(base_rows,dict([('ZC-0004','是')]))),"完整列出搁置时标明其中的重点")
txt=run(wide(base_rows,dict([('ZC-0001','重要')])))
assert_ok("- [ZC-0001] 示例报告" in txt and "需要先补的事" in txt and "重点这一列填了别的内容" in txt.split("需要先补的事")[1] and "ZC-0001" in txt.split("需要先补的事")[1],"重点列写了别的值：照常列出，不当成重点，并在需要先补的事里说明")
txt=run(wide(base_rows,dict([('ZC-0003','是')])),draft=dict(revision=317,review=[hold]))
assert_ok(txt.count("[ZC-0003]")==1 and "\n重点\n" not in txt and "需要先补的事" in txt and "ZC-0003" in txt.split("需要先补的事")[1],"到日待核的事即使标了重点也只列一次，并在需要先补的事里说明")
reject("M:O 表头不是约定的三列",lambda:run(wide(base_rows,head=["重点","结束日期","周期"])))
reject("旧的两列表头不再被接受",lambda:run(wide(base_rows,head=["结束日期","重点"])))
reject("只读到部分新增列",lambda:run([export('ABCDEFGHIJKLMN',[list(r)+["",""] for r in base_rows])]))
reject("分片读到的列范围不一致",lambda:run([export('ABCDEFGHIJKL',base_rows[:5]),export('ABCDEFGHIJKLMNO',[list(r)+["","",""] for r in base_rows[5:]],6)]))

# 周期 (cycle): the next period is computed by the tool, never by the assistant.
def d(s): return date.fromisoformat(s)
FRI=date(2026,11,20)   # a Friday
assert_ok(g.next_period('每周',d('2026-11-06'),d('2026-11-18'))==d('2026-11-20'),"每周：过期两期以上也落在今天之后的下一个同星期")
assert_ok(g.next_period('每周',d('2026-11-13'),d('2026-11-18'))==d('2026-11-20'),"每周：落后不到一期，下一期是提醒日加七天")
assert_ok(g.next_period('每周',d('2026-11-18'),d('2026-11-18'))==d('2026-11-25'),"每周：提醒日就是今天，下一期是一周后而不是今天")
assert_ok(g.next_period('每两周',d('2026-11-04'),d('2026-11-18'))==d('2026-12-02'),"每两周：刚好满两周时落到再下一期")
assert_ok(g.next_period('每两周',d('2026-11-04'),d('2026-11-13'))==d('2026-11-18'),"每两周：落后九天，下一期是提醒日加十四天")
assert_ok(g.next_period('每工作日',d('2026-11-13'),d('2026-11-13'))==d('2026-11-16'),"每工作日：周五之后跳到周一")
assert_ok(g.next_period('每工作日',d('2026-11-02'),d('2026-11-18'))==d('2026-11-19'),"每工作日：落后多天，下一期是今天之后的第一个工作日")
assert_ok(g.next_period('每工作日',d('2026-11-14'),d('2026-11-14'))==d('2026-11-16'),"每工作日：周六也是周一")
assert_ok(g.next_period('每月',d('2026-10-09'),d('2026-11-13'))==d('2026-12-09'),"每月：提醒日加整月数后第一个晚于今天的同日")
assert_ok(g.next_period('每月',d('2026-01-31'),d('2026-02-10'))==d('2026-02-28'),"每月：月底日在短月落到当月最后一天")
assert_ok(g.next_period('每月',d('2026-01-31'),d('2026-03-01'))==d('2026-03-31'),"每月：短月之后回到月底")
assert_ok(g.next_period('每周',d('2026-11-30'),d('2026-11-18'))==d('2026-12-07'),"提醒日在将来时不退回过去")
reject("未知的周期",lambda:g.next_period('每天两次',d('2026-11-13'),d('2026-11-18')))

def cyc(rows_,**cycles):
    # rows with the given cycle strings and reminder dates; cycles maps id -> (cycle, reminder date)
    out=[list(rows_[0])+list(g.EXTRA_HEAD)]
    for r in rows_[1:]:
        r=list(r)
        if r[8] in cycles: r[10]=cycles[r[8]][1]
        out.append(r+["","",cycles.get(r[8],("",""))[0]])
    return [export('ABCDEFGHIJKLMNO',out)]
txt=run(cyc(base_rows,**{'ZC-0002':('每周','2026-11-06'),'ZC-0001':('每两周','2026-11-04')}))
line=[x for x in txt.splitlines() if x.startswith('- [ZC-0002]')][0]
assert_ok("每周，这一期应是2026-11-06，已落后12天" in line and "提醒日可改到2026-11-20" in line,"周期事项落后时在行内写出已落后天数和下一期日期")
line=[x for x in txt.splitlines() if x.startswith('- [ZC-0001]')][0]
assert_ok("每两周，这一期应是2026-11-04，已落后14天" in line and "提醒日可改到2026-12-02" in line,"每两周的下一期也由工具给出")
line=[x for x in run(cyc(base_rows,**{'ZC-0002':('每周','2026-11-18')})).splitlines() if x.startswith('- [ZC-0002]')][0]
assert_ok("已落后" not in line and "提醒日可改到" not in line,"周期事项提醒日就是今天时不算落后")
txt=run(cyc(base_rows,**{'ZC-0002':('每天两次','2026-11-18')}))
assert_ok("需要先补的事" in txt and "ZC-0002" in txt.split("需要先补的事")[1] and "周期这一列填了别的内容" in txt.split("需要先补的事")[1] and "提醒日可改到" not in txt,"周期列写了不认的值：不当成周期，并在需要先补的事里说明")
assert_ok(run(wide(base_rows))==plain,"没有周期时清单不变")

# 截止日 (deadline): only a full date is ever compared. Text and month-day cells are never read as a date.
def dl(deadline,state='项目'):
    rr=copy.deepcopy(base_rows); rr[2][4]=deadline; rr[2][0]=state
    return [export('ABCDEFGHIJKL',rr)]
line=[x for x in run(dl('2026-11-15')).splitlines() if x.startswith('- [ZC-0002]')][0]
assert_ok("已过截止日3天：改日期、取消，还是换成别的事？" in line,"截止日是真日期且已过：提醒改问改日期、取消还是换事")
line=[x for x in run(dl('46351')).splitlines() if x.startswith('- [ZC-0002]')][0]
assert_ok("已过截止日" not in line,"序列号形式的将来日期不算已过")
for text in ('待定','暂无','每周','持续','11月15日','10月23日（下周五）',''):
    line=[x for x in run(dl(text)).splitlines() if x.startswith('- [ZC-0002]')][0]
    assert_ok("已过截止日" not in line,f"截止日写成“{text or '空'}”时不当作日期，不标逾期")
assert_ok(g.cell_day('46330')==date(2026,11,4) and g.cell_day('2026-11-04')==date(2026,11,4) and g.cell_day('2026/11/4')==date(2026,11,4) and
            g.cell_day('11月4日') is None and g.cell_day('待定') is None and g.cell_day('2026-13-40') is None,"只认完整日期，月日和文字不猜年份")

# Tidy-up (整理): evening lists a short ranked pool, Saturday lists all, the morning lists none. Cycle items are left out.
def stale(*ids_days,starred=(),cycles=None,ended=()):
    rr=[list(base_rows[0])+list(g.EXTRA_HEAD)]
    for r in base_rows[1:]:
        r=list(r); rr.append(r+["","",""])
    for i,(tid,k,state) in enumerate(ids_days):
        rr.append(item(tid,'旧事'+tid,'1',state=state,k=k)+["","",""])
    for tid,end in ended:
        rr.append(item(tid,'刚结束'+tid,'0',state='已完成')+[end,"",""])
    for row in rr[1:]:
        if row[8] in starred: row[13]='是'
        if cycles and row[8] in cycles: row[14]=cycles[row[8]]
    return rr
ids=[('ZC-1%03d'%i,(DAY-timedelta(days=8+i)).isoformat(),'(待处理)') for i in range(9)]
rr=stale(*ids,ended=[('ZC-2001',(DAY-timedelta(days=2)).isoformat()),('ZC-2002',(DAY-timedelta(days=30)).isoformat())])
all_due=['ZC-0001','ZC-0002','ZC-0003']+[x[0] for x in ids]
sheet=[export('ABCDEFGHIJKLMNO',rr)]; ctl=ref(all_due,pe_count(rr)); n=len(rr)
morning=run(sheet,ctl,grid=n,session='morning')
assert_ok("可以考虑整理的事" not in morning and "最近完成的事" not in morning,"早间不做整理")
evening=run(sheet,ctl,grid=n,session='evening')
cand=[x for x in evening.splitlines() if x.startswith('- [ZC-1')]
ranked=[x for x in cand if '提醒日落后' in x]
assert_ok(evening.splitlines()[0].startswith("应覆盖 12｜") and "可以考虑整理的事" in evening and len(ranked)==9 and "全部列出" in evening and "留给周六" not in evening,"晚间整理名单完整列出全部候选，不截断，也不说留给周六")
assert_ok(ranked[0].startswith("- [ZC-1008]") and "提醒日落后16天" in ranked[0],"可以考虑整理的事里落后最久的排在最前")
assert_ok("[ZC-2001]" in evening and "结束于"+(DAY-timedelta(days=2)).isoformat() in evening and "[ZC-2002]" not in evening,"最近完成的事列出，更早的不列")
weekly=run(sheet,ctl,grid=n,session='weekly')
assert_ok(len([x for x in weekly.splitlines() if x.startswith('- [ZC-1') and '提醒日落后' in x])==9 and "留给周六" not in weekly,"周六整理列出全部候选")
assert_ok([x for x in evening.splitlines() if x.startswith('- [ZC-1')]==[x for x in weekly.splitlines() if x.startswith('- [ZC-1')],"晚间与周六的整理名单完全相同，晚间不因时段缩短")
# A long list is printed in full: 30 candidates, none dropped.
long_ids=[('ZC-3%03d'%i,(DAY-timedelta(days=8+i)).isoformat(),'(待处理)') for i in range(30)]
rr_long=stale(*long_ids)
# rr_long holds the base rows from stale() plus the 30 new items. Its L=1 set is the 30 new items plus the base's
# three due rows, so the checklist count must match exactly that set, read from the sheet rather than typed by hand.
long_due=[r[8] for r in rr_long[1:] if r[11]=='1' and r[8]]
long_parked_or_exc=sum(1 for r in rr_long[1:] if r[11] in ('搁置','待设置','待核实'))
ev_long=run([export('ABCDEFGHIJKLMNO',rr_long)],ref(long_due,long_parked_or_exc),grid=len(rr_long),session='evening')
# The same thirty items appear once in the normal list and once in the tidy-up block. Only the tidy-up block counts here.
tidy_part=ev_long[ev_long.index("可以考虑整理的事"):]
listed=[x for x in tidy_part.splitlines() if x.startswith('- [ZC-3')]
assert_ok(len(listed)==30 and f"共 {len(long_ids)} 件，全部列出" in ev_long and "留给周六" not in ev_long,"三十件候选全部列出，不截断")
assert_ok("最近完成的事（对照一下，看是否和上面的事相关）：共 1 件，全部列出" in evening,"最近结束的事全部列出（本用例里只有一件在十四天内）")
rr2=stale(*ids,starred=('ZC-1000',))
ev2=run([export('ABCDEFGHIJKLMNO',rr2)],ref(all_due,pe_count(rr2)),grid=len(rr2),session='evening')
cand2=[x for x in ev2.splitlines() if x.startswith('- [ZC-1') and '提醒日落后' in x]
assert_ok(cand2[0].startswith("- [ZC-1000]") and "（重点）" in cand2[0],"可以考虑整理的事里的重点排在最前，不论落后几天")
rr3=stale(*ids,cycles=dict((x[0],'每周') for x in ids))
ev3=run([export('ABCDEFGHIJKLMNO',rr3)],ref(all_due,pe_count(rr3)),grid=len(rr3),session='evening')
assert_ok("可以考虑整理的事" not in ev3 and "每周，这一期应是" in ev3,"周期事项不进可以考虑整理的事，由行内的周期提示处理")
rr4=stale(('ZC-1500',(DAY-timedelta(days=3)).isoformat(),'(待处理)'))
ev4=run([export('ABCDEFGHIJKLMNO',rr4)],ref(['ZC-0001','ZC-0002','ZC-0003','ZC-1500'],pe_count(rr4)),grid=len(rr4),session='evening')
assert_ok("可以考虑整理的事" not in ev4,"落后不到一周且没过截止日的事不进可以考虑整理的事")
rr5=stale(('ZC-1501',(DAY-timedelta(days=2)).isoformat(),'(待处理)'))
rr5[-1][4]=(DAY-timedelta(days=4)).isoformat()
ev5=run([export('ABCDEFGHIJKLMNO',rr5)],ref(['ZC-0001','ZC-0002','ZC-0003','ZC-1501'],pe_count(rr5)),grid=len(rr5),session='evening')
assert_ok("[ZC-1501]" in ev5 and "已过截止日4天" in ev5 and "可以考虑整理的事" in ev5,"已过截止日的事进可以考虑整理的事")
# The tidy-up block never changes coverage or the count line.
assert_ok(evening.splitlines()[0]==weekly.splitlines()[0]==run(sheet,ctl,grid=n).splitlines()[0],"整理不改变计数行")

# The new 下一期 subcommand, through the command line.
with tempfile.TemporaryDirectory() as dd:
    r=subprocess.run([sys.executable,'-X','utf8',str(BASE/'提醒工具.py'),'下一期','--周期','每两周','--提醒日','2026-11-04'],capture_output=True)
    shown=r.stdout.decode('utf-8').strip()
    assert_ok(r.returncode==0 and re.fullmatch(r"\d{4}-\d{2}-\d{2}",shown) is not None,"命令行：下一期输出一个完整日期")
    r=subprocess.run([sys.executable,'-X','utf8',str(BASE/'提醒工具.py'),'下一期','--周期','每两周','--提醒日','11月4日'],capture_output=True)
    assert_ok(r.returncode!=0 and not r.stdout and bool(r.stderr),"命令行：提醒日没有年份时拒绝，不猜年份")
    r=subprocess.run([sys.executable,'-X','utf8',str(BASE/'提醒工具.py'),'下一期','--周期','每天两次','--提醒日','2026-11-04'],capture_output=True)
    assert_ok(r.returncode!=0 and not r.stdout,"命令行：不认的周期被拒绝")

parser=argparse.ArgumentParser();parser.add_argument('--历史回放',action='store_true')
if parser.parse_args().历史回放:
    archive=BASE.parent/'历史材料'/'20261116_结构收缩'
    hist=json.loads((archive/'实施'/'提醒字段迁移记录.json').read_text(encoding='utf-8-sig'))
    raw=g.read(archive/'zhangchi-after-fields.json')
    # The 2026-11-05 snapshot was written when the parked state was called 待安排. Replay reads it under the current
    # name 搁置. Only the in-memory copy handed to the tool is changed; the archived file is never rewritten.
    _OLD_PARKED_L="待安排"
    # Parse the whole CSV, rename the L value, and write it back whole. Cells can span physical lines (H 列的多条进展),
    # so the snapshot is never split on "\n".
    _recs=list(csv.reader(io.StringIO(raw["annotated_csv"],newline="")))
    _renamed=0
    for _rec in _recs:
        if len(_rec)>=12 and _rec[11]==_OLD_PARKED_L:
            _rec[11]=g.PARKED; _renamed+=1
    _out=io.StringIO(newline=""); _w=csv.writer(_out,lineterminator="\n")
    for _rec in _recs: _w.writerow(_rec)
    raw=dict(raw,annotated_csv=_out.getvalue())
    assert_ok(_renamed==sum(1 for x in hist if str(x['expected_on_2026_11_05'])=='待安排') and
              all(not(len(c)>=12 and c[11]==_OLD_PARKED_L) for c in csv.reader(io.StringIO(raw["annotated_csv"],newline=""))),
              "历史快照的旧 L 值已全部按新名读取")
    # The migration record keeps the 2026-11-05 wording (待安排). Expected counts use the current name (搁置),
    # the same mapping the snapshot went through above, so both sides count one thing.
    marks=[(g.PARKED if str(r['expected_on_2026_11_05'])=='待安排' else str(r['expected_on_2026_11_05'])) for r in hist]
    expect=[r['id'] for r in hist if str(r['expected_on_2026_11_05'])=='1']
    exc=sum(x in g.EXCEPTIONS for x in marks);parked=marks.count(g.PARKED)
    out=g.checked_block([raw],ref(expect,exc,raw['revision'],date(2026,11,5)),raw['row_count'],date(2026,11,5))
    assert_ok(exc==59 and f"应覆盖 25｜正常列出 25｜到日待核 0｜搁置 {parked}｜表内异常 {exc-parked}" in out,"原生历史原表导出＋独立迁移预期核对（仅测试数量与编号）")
for name in ['chat','morning','evening','weekly']:
    val=g.entry(name); assert_ok(str(BASE/'个人助理工作规范.md') in val and str(BASE/'运行配置.json') in val,name+" 入口绑定实际根目录")
windows=g.CFG['entries']
assert_ok(g.CFG['timezone']=='Asia/Shanghai' and
            [(windows[k]['weekdays'],windows[k]['time']) for k in ('morning','evening','weekly')]==
            [([1,2,3,4,5],'08:30'),([1,2,3,4,5],'17:30'),([6],'10:00')],"早晚、周六单场、周日静默是同一份配置")
assert_ok(g.FOLDED==set(k for k in windows if windows[k]['weekdays']!=[6]),"只报搁置件数的场次正是配置里的工作日场次")

# Exercise the CLI failure path: it must not leak a partial success list to stdout.
with tempfile.TemporaryDirectory() as d:
    p=Path(d);(p/'坏.json').write_text(json.dumps(dict()),encoding='utf-8')
    bad=[sys.executable,str(BASE/'提醒工具.py'),'清单','--台账',str(p/'坏.json'),'--核对页',str(p/'坏.json'),'--网格行数','2']
    r=subprocess.run(bad,capture_output=True)
    assert_ok(r.returncode!=0 and not r.stdout and bool(r.stderr),"失败时非零退出且不输出正常正文")
    r=subprocess.run(bad+['--场次','noon'],capture_output=True)
    assert_ok(r.returncode!=0 and not r.stdout and bool(r.stderr),"命令行拒绝未知场次")
    moved=p/'新位置 有空格'/'实施';moved.mkdir(parents=True)
    for fn in ['提醒工具.py','运行配置.json','个人助理工作规范.md','早间计划.txt','晚间复盘.txt','周复盘.txt','今日应提醒公式.txt','核对页公式.json']:
        shutil.copy2(BASE/fn,moved/fn)
    shutil.copy2(BASE.parent/'规则定稿_20261105.md',moved.parent/'规则定稿_20261105.md')
    for role in ('chat','morning','evening','weekly'):
        r=subprocess.run([sys.executable,'-X','utf8',str(moved/'提醒工具.py'),'入口',role],cwd=p,capture_output=True)
        txt=r.stdout.decode('utf-8')
        assert_ok(r.returncode==0 and str(moved/'个人助理工作规范.md') in txt and str(BASE) not in txt,role+" 异地中文空格目录绑定")
# Health line and deadline blind spots (规则第 3 节, 计划完成时间 readability).
# Build a fixture where the E column of selected rows carries each kind of text.
def with_e(rows_in, values):
    out=[list(r) for r in rows_in]
    for n,v in values.items():
        out[n][4]=v
    return out
e_rows=with_e(base_rows,{2:'2026-11-20',3:'7月9日',4:'待定',5:'暂无',6:'9月26-30日（活动执行）',7:'8月',8:'46098',9:'持续（每周五）'})
e_txt=run([export('ABCDEFGHIJKL',e_rows)],audit,grid=len(e_rows))
lines=e_txt.splitlines()
health=[x for x in lines if x.startswith('数据已核对，今天')]
assert_ok(len(health)==1 and lines[-1]==health[0] and health[0]==f"数据已核对，今天 {DAY.strftime('%m-%d')}，3 处日期看不懂，不影响提醒","核对行只出现一次，放在最后，计算日期取自今天，一句人话")
assert_ok("，3 处日期看不懂，不影响提醒" in health[0],"无法识别格数只算真正的盲区：7月9日、区间、只有月份（三格，纯占位词和周期说法都不计）")
assert_ok("截止日写的是「7月9日」" in e_txt and "截止日写的是「9月26-30日（活动执行）」" in e_txt and "截止日写的是「8月」" in e_txt,"看不懂的截止日逐条列出，写明原文")
assert_ok("截止日写的是「待定」" not in e_txt and "截止日写的是「暂无」" not in e_txt and "截止日写的是「持续（每周五）」" not in e_txt and "截止日写的是「46098」" not in e_txt and "截止日写的是「2026-11-20」" not in e_txt,"纯占位词、周期说法、完整日期、序列号不被误报为看不懂")
assert_ok(lines[0]==SUMMARY,"盲区不改变首行计数：E 列怎么写，不影响应覆盖、正常列出、搁置、表内异常的数字")
assert_ok(all(x in e_txt for x in ["- [ZC-0001] 示例报告","- [ZC-0002] 示例任务B"]),"盲区不改变清单行本身")
clean_txt=run([export('ABCDEFGHIJKL',base_rows)],audit,grid=len(base_rows))
assert_ok(clean_txt.splitlines()[-1].startswith("数据已核对，今天") and "看不懂" not in clean_txt.splitlines()[-1] and "截止日写的是「" not in clean_txt,"没有看不懂的日期时，核对行不提这一部分，也不列明细")
# The tool's cycle-wording reader must agree with the local tidy plan's reader on the same inputs.
# Two copies of one rule are only safe if a check fails when they diverge.
_tidy_spec=importlib.util.spec_from_file_location("tidy_deadlines_check",BASE.parent/"本地表"/"tidy_deadlines.py")
_tidy=importlib.util.module_from_spec(_tidy_spec); _tidy_spec.loader.exec_module(_tidy)
_probe=['每工作日','每周','每周一','每周五','每两周','每月','持续（每两周）','持续（每周五）','持续（每周五）；首份诊断报告10月17日','待定','暂无','持续','7月9日','8月','每天','每周六日']
_disagree=[s for s in _probe if g.is_cycle_wording(s) != (_tidy.cycle_of(s) is not None)]
assert_ok(not _disagree,"工具与本地整理对周期说法的判断一致："+("" if not _disagree else str(_disagree)))
# The tool computes L itself (规则第 4 节). Each branch of the current rule gets one case.
_day=DAY
def _l(a,b,i,j,k,ids=1):
    return g.compute_l([a,b,'','','','','','',i,j,k],ids,_day)
assert_ok(_l('跟进中','事','ZC-1','开启',_day.isoformat())=='1',"计算：到日且开启 → 1")
assert_ok(_l('跟进中','事','ZC-1','开启',(_day+timedelta(days=3)).isoformat())=='0',"计算：未到日且开启 → 0")
assert_ok(_l('已完成','事','ZC-1','开启',_day.isoformat())=='0',"计算：已完成（结束状态）→ 0，不论开关")
assert_ok(_l('已取消','事','ZC-1','开启','')=='0',"计算：已取消 → 0")
assert_ok(_l('已转交结项','事','ZC-1','开启','')=='0',"计算：已转交结项 → 0")
assert_ok(_l('已归并','事','ZC-1','开启','')=='0',"计算：已归并 → 0")
assert_ok(_l('跟进中','事','ZC-1','关闭',_day.isoformat())=='0',"计算：关闭 → 0，即使日期已到")
assert_ok(_l('跟进中','事','ZC-1','搁置','')==g.PARKED,"计算：J=搁置 → L 显示搁置，K 不参与")
assert_ok(_l('跟进中','事','ZC-1','搁置',_day.isoformat())==g.PARKED,"计算：J=搁置时即使 K 有日期，L 仍显示搁置")
assert_ok(_l('跟进中','事','ZC-1','开启','')=='待设置',"计算：开启但 K 空 → 待设置（漏填，不是搁置）")
assert_ok(_l('跟进中','事','ZC-1','未定义','')=='待设置',"计算：J 不是三种值之一 → 待设置")
assert_ok(_l('中优先','事','ZC-1','开启',_day.isoformat())=='待核实',"计算：状态不在规则列表 → 待核实，不当作在办")
assert_ok(_l('跟进中','事','ZC-1','开启','待定')=='待核实',"计算：K 不是日期 → 待核实")
assert_ok(_l('跟进中','事','ZC-1','开启',_day.isoformat(),ids=2)=='待核实',"计算：编号重复 → 待核实")
assert_ok(_l('跟进中','','ZC-1','开启',_day.isoformat())=='待核实',"计算：事项名为空 → 待核实")
assert_ok(_l('','','','','')=='',"计算：整行空白 → 空")
print(json.dumps(dict(checked=len(passed),cases=passed,production_access=False),ensure_ascii=True))
