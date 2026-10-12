"""双线合稿：把文献线综述 + 市场线调研合成**一篇**论文式报告（用户终态需求）。

用户需求原文：「文献检索和市场检索都会生成类似于论文的那种东西，我要把这两个
东西合在一个文档里。」——即两条线各自产出一篇报告后，再合成一篇统一文档，
而不是两份报告并列，也不是把证据表合并。

流程：
  1) 读入两份真实产出——
     reports/literature_report.md（文献综述，已过 DOI 护栏）
     reports/market_report.md（市场调研，已过 URL 护栏）
     reports/dual_line_evidence.md（证据底稿：交叉带/盲区，仅作合稿参照）
  2) 单次 LLM 调用做合稿（按 v0.2「砍三角色」方向：合稿只需一次调用），
     输出固定结构的论文式正文：摘要 / 引言 / 文献线 / 市场线 / 双线交叉讨论 /
     结论与人工对照（结论区留白，Agent 不给立项建议）
  3) 代码级双护栏：sanitize_report_urls（URL 白名单）+ sanitize_report_citations
     （DOI 白名单）——合稿环节同样会编引用，必须再兜一次
  4) 参考文献与检索溯源**由代码生成**追加（LLM 不写参考文献表）

用法（仓库根目录）：python -u scripts/merge_dual_reports.py
"""
import json
import os
import re
import sys
import time

import dotenv

dotenv.load_dotenv(".env")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.main import (append_grounded_refs, get_llm, sanitize_report_citations,
                      sanitize_report_urls)

TOPIC = "排水管网高水位状态下的检测与诊断"
REPORTS = os.path.join(ROOT, "reports")
LIT_PATH = os.path.join(REPORTS, "literature_report.md")
MKT_PATH = os.path.join(REPORTS, "market_report.md")
EVID_PATH = os.path.join(REPORTS, "dual_line_evidence.md")
OUT_PATH = os.path.join(REPORTS, "dual_line_report.md")
ACADEMIC_CACHE = os.path.join(REPORTS, "academic_results.json")
MARKET_CACHE = os.path.join(REPORTS, "market_records.json")

SYSTEM_PROMPT = """你是一名环境工程领域的调研报告合稿编辑。你的唯一任务是把两份**已经写好**的调研报告合成一篇论文式报告。

铁律（违反即作废）：
1. **只做重组与衔接，不做新研究**。所有事实、数字、文献、机构名、技术路线、可信度判断，必须来自我给你的两份输入报告原文。禁止引入任何外部知识、禁止补充两份报告里没有的案例或产品名。
2. **保留可信度标注**。市场线的 A/B/C 分级、「证据不足」「待核实」「社区反馈」等限定词必须原样保留，不得把 C 级线索写成确定结论。
3. **不给立项建议**。结论区只写「证据支持什么 / 证据不支持什么 / 还缺什么证据」，把「该不该我们做」留成空白的人工对照清单。禁止出现「建议立项」「值得投入」这类裁决性表述。
4. **不写参考文献表、不写检索过程**。这两块由系统用代码追加，你写了也会被剥离。
5. 引用格式：学术引用沿用原文写法（作者，年份，DOI:xxx）；市场来源只写原文里的机构/来源名与分级，不要自行拼 URL。

输出严格的 markdown，章节结构如下（标题文字可微调，层级不变）：
# {topic}：文献与市场双线调研报告
## 摘要（300 字以内，概括两线各自的核心发现与最大空白）
## 一、引言：调研范围与方法（说明两条线各答什么、可溯源标准：学术 DOI 级 / 市场 URL+日期+分级）
## 二、文献线：研究现状（能不能做）（只改写文献综述内容，保留其中英文对比与研究空白）
## 三、市场线：产业与工程现状（值不值得做）（只改写市场调研内容，保留分级与证据不足说明）
## 四、双线交叉讨论（同一议题上两条线的对应关系与缺口；可参照我给的证据底稿交叉带，但只能引用两份报告里已出现的内容）
## 五、结论与人工对照（分「证据支持」「证据不支持」「证据缺口」三小节，然后是空的人工对照清单，不要填答案）
"""


DROP_HEADING_KEYS = ("参考文献", "文献表", "检索过程溯源", "来源清单", "附录")


def strip_appended(path):
    """剥离报告里由代码追加的溯源/文献表区块，以及 LLM 自写的参考文献节。

    合稿后这两块都会由系统统一重新生成（代码级），若不剥离会出现
    「正文一份参考文献 + 文末一份参考文献」的重复。按二级标题整节剔除，
    比按字符串 find 更稳（避免正文里偶然出现关键词被误截）。
    """
    if not os.path.exists(path):
        return ""
    lines = open(path, encoding="utf-8").read().splitlines()
    kept, dropping = [], False
    for ln in lines:
        if ln.startswith("## "):
            heading = ln[3:].strip()
            dropping = any(k in heading for k in DROP_HEADING_KEYS)
        if not dropping:
            kept.append(ln)
    return "\n".join(kept).rstrip()


def build_refs_block(academic, market, fetch_date):
    """参考文献区块：完全由代码生成（LLM 不参与），两线分列、各自标度。"""
    L = ["## 参考文献", "",
         "本节由系统按代码从真实检索结果生成，撰稿环节不参与，两线分列、各用各的溯源标准。", ""]
    L.append(f"### 学术文献（DOI 级，共 {len(academic)} 篇）")
    L.append("")
    L.append("| # | 标题 | 年份 | 期刊/学位单位 | 被引 | DOI | 语种 |")
    L.append("|---|---|---|---|---|---|---|")
    for i, p in enumerate(academic, 1):
        L.append("| " + " | ".join([
            str(i),
            " ".join(str(p.get("title") or "—").split()).replace("|", "/"),
            str(p.get("year") or "—"),
            " ".join(str(p.get("venue") or "—").split()).replace("|", "/"),
            str(p.get("citations") if p.get("citations") not in (None, "") else "—"),
            str(p.get("doi") or "（无）"),
            str(p.get("lang") or "—"),
        ]) + " |")
    L.append("")
    L.append(f"### 市场来源（URL + 抓取日期 + 可信度分级，共 {len(market)} 条，"
             f"全部抓取于 {fetch_date}）")
    L.append("")
    L.append("| # | 来源标题 | 分级 | URL | 抓取日期 | 命中检索式 |")
    L.append("|---|---|---|---|---|---|")
    for i, r in enumerate(market, 1):
        L.append("| " + " | ".join([
            str(i),
            " ".join(str(r.get("title") or "—").split()).replace("|", "/"),
            str(r.get("tier") or "—"),
            str(r.get("url") or "—"),
            str(fetch_date or "—"),
            " ".join(str(r.get("query_hit") or "—").split()).replace("|", "/"),
        ]) + " |")
    L.append("")
    return "\n".join(L)


def main():
    for p in (LIT_PATH, MKT_PATH):
        if not os.path.exists(p):
            raise FileNotFoundError(f"缺少输入报告：{p}")
    academic = json.load(open(ACADEMIC_CACHE, encoding="utf-8"))
    market = json.load(open(MARKET_CACHE, encoding="utf-8"))
    papers, records = academic["papers"], market["records"]

    lit = strip_appended(LIT_PATH)
    mkt = strip_appended(MKT_PATH)
    evid = ""
    if os.path.exists(EVID_PATH):
        evid = open(EVID_PATH, encoding="utf-8").read()
        i = evid.find("## 三、双线交叉带")
        j = evid.find("## 五、")
        evid = evid[i:j] if i != -1 and j != -1 else ""

    print(f"[1/3] 输入：文献线 {len(lit)} 字 / 市场线 {len(mkt)} 字 / 交叉带 {len(evid)} 字")
    print(f"      真实来源：学术 {len(papers)} 篇（DOI 白名单）｜市场 {len(records)} 条（URL 白名单）")

    print("[2/3] 单次 LLM 合稿（不新增事实、不写参考文献、不给立项建议）...")
    t0 = time.time()
    llm = get_llm()
    user = (
        f"【文献线报告】\n{lit}\n\n"
        f"【市场线报告】\n{mkt}\n\n"
        f"【证据底稿交叉带（仅供参照，不得引入两份报告之外的内容）】\n{evid}\n\n"
        f"请按系统提示的章节结构合成一篇报告，主题为「{TOPIC}」。"
    )
    out = llm.call([{"role": "system", "content": SYSTEM_PROMPT.format(topic=TOPIC)},
                    {"role": "user", "content": user}])
    body = out if isinstance(out, str) else str(out)
    print(f"  合稿完成（{time.time()-t0:.0f}s，{len(body)} 字）")

    print("[3/3] 双护栏对账 + 代码生成参考文献与溯源...")
    os.makedirs(REPORTS, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(body.rstrip() + "\n\n")

    sanitize_report_urls(OUT_PATH, allowed_urls=[r["url"] for r in records])
    sanitize_report_citations(OUT_PATH, allowed_dois=[p.get("doi") for p in papers])

    refs = build_refs_block(papers, records, market.get("fetch_date"))
    trace = [
        "本节记录两线检索的真实过程，由代码生成。",
        "",
        "**文献线检索式与召回**（来自 fetch_literature_grounded 的 trace）：",
        "",
        *(academic.get("trace") or ["（无）"]),
        "",
        "**市场线检索式与分级**：",
        "",
        *[f"- `{q}`" for q in market.get("queries", [])],
        "- 分级统计：" + "；".join(f"{t} 级 {n} 条" for t, n in sorted(market.get("tier_stat", {}).items())),
        f"- URL 抓取日期：{market.get('fetch_date')}（注入式 WebSearch 采集）",
    ]
    append_grounded_refs(OUT_PATH, refs + "\n\n## 附录：检索过程溯源\n\n" + "\n".join(trace) + "\n")

    final = open(OUT_PATH, encoding="utf-8").read()
    print(f"\n===== 完成：{OUT_PATH}（{len(final.splitlines())} 行）=====")


if __name__ == "__main__":
    main()