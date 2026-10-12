"""学术线报告重生成（复用缓存检索结果 + 引用级护栏）。

为什么需要重生成：旧版 reports/literature_report.md（2026-10-12 00:36）引用的
51 个 DOI 里只有 1 个能在真实检索清单中找到，其余 50 个系撰稿员凭参数记忆生成
（tools=[] 时 Crew 会编造引用）。本次重生成叠加三道修复：
  1. 检索结果改为复用已缓存的 91 篇（reports/academic_results.json，抓取于
     2026-10-12，检索式已修复：全部等价词 + 对象⊕条件组合）；
  2. Crew 不再设「文献检索员」角色（tools=[] 时该角色会编造文献清单并
     经 context 污染下游），只保留 分析员 → 撰稿员；
  3. 写稿后跑 sanitize_report_citations()：凡 DOI 不在真实检索结果内，
     一律替换为「〔DOI 不可溯源，已剔除〕」并计数告警。

用法（仓库根目录）：python -u scripts/run_literature_real.py [--refresh]
  --refresh  重新实时抓取学术库（覆盖缓存），约 4-5 分钟
"""
import json
import os
import sys
import time

import dotenv

dotenv.load_dotenv(".env")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.crews.literature_crew import build_literature_crew
from src.main import (_is_thesis, append_grounded_refs, fetch_literature_grounded,
                      get_llm, sanitize_report_citations)
from src.tools.memory_store import build_memory_block

TOPIC = "排水管网高水位状态下的检测与诊断"
CACHE = os.path.join(ROOT, "reports", "academic_results.json")
REPORT = os.path.join(ROOT, "reports", "literature_report.md")


def load_papers(refresh=False):
    """优先用缓存的检索结果（真实数据由代码持有，不重新抓取）。"""
    if os.path.exists(CACHE) and not refresh:
        with open(CACHE, encoding="utf-8") as f:
            data = json.load(f)
        print(f"  复用缓存检索结果：{len(data['papers'])} 篇"
              f"（抓取于 {data['fetched_at']}，来源：{data['source']}）")
        return data["papers"], data["source"], data.get("trace", []), data.get("warn")
    _raw, source, papers, warn = fetch_literature_grounded(TOPIC, limit=15)
    import src.main as main_mod
    trace = list(getattr(main_mod, "_LAST_TRACE", []))
    return papers, source, trace, warn


def build_ctx(papers):
    """按 fetch_literature_grounded 的同一格式重建注入给 Crew 的上下文。"""
    lines = ["# 真实检索结果（严禁编造、严禁替换）"]
    for p in papers:
        kind = ""
        if p.get("lang") == "zh" and _is_thesis(p.get("venue", "")):
            kind = "（类型：学位论文，授予单位）"
        lines.append(
            f"- {p['title']} ({p['year']}) | {p['authors']} | {p['venue']}{kind} | "
            f"DOI:{p['doi']} | 被引:{p['citations']} | 语言:{p['lang']}"
        )
    return "\n".join(lines)


def main():
    refresh = "--refresh" in sys.argv
    print("[1/3] 载入真实检索结果（代码持有，LLM 不参与检索）...")
    papers, source, trace, warn = load_papers(refresh)
    if warn:
        print(f"  警告：{warn}")
    n_zh = sum(1 for p in papers if p.get("lang") == "zh")
    print(f"  共 {len(papers)} 篇（中文 {n_zh} / 英文 {len(papers)-n_zh}）")

    print("[2/3] 运行 CrewAI（分析员 → 撰稿员，无检索员角色）...")
    t0 = time.time()
    llm = get_llm()
    mem_block = build_memory_block(TOPIC, limit=8)
    crew = build_literature_crew(TOPIC, llm, tools=[], search_results=build_ctx(papers),
                                 memory=mem_block)
    crew.kickoff()
    print(f"  Crew 完成（{time.time()-t0:.0f}s）")

    print("[3/3] 引用级护栏 + 附真实文献表...")
    dropped = sanitize_report_citations(
        REPORT, allowed_dois=[p["doi"] for p in papers if p.get("doi")])
    n_valid = len({p["doi"].lower() for p in papers if p.get("doi")})
    print(f"  引用对账：白名单 {n_valid} 个真实 DOI，剔除编造 {len(dropped)} 个")

    tsv_lines = ["标题\t年份\t作者\tDOI\t期刊\t被引\t语种"]
    for p in papers:
        tsv_lines.append(
            f"{p['title']}\t{p['year']}\t{p['authors']}\t{p['doi']}\t"
            f"{p['venue']}\t{p['citations']}\t{p['lang']}"
        )
    trace_md = "\n".join(trace) if trace else "（无溯源记录）"
    tsv_block = (
        "## 检索过程溯源\n\n"
        "本节记录程序如何理解检索主题、构造了哪些检索式、各级降级结果——"
        "**若理解有误，可据此判断并换词重跑**。\n\n"
        f"{trace_md}\n\n"
        "## 文献表（真实检索结果，系统按代码生成，绝不编造）\n\n"
        f"来源：{source}｜中文 {n_zh} 篇 + 英文 {len(papers)-n_zh} 篇\n\n```\n"
        + "\n".join(tsv_lines) + "\n```"
    )
    append_grounded_refs(REPORT, tsv_block)
    print(f"\n===== 完成：{REPORT}（真实文献 {len(papers)} 篇，剔除编造引用 {len(dropped)} 个）=====")


if __name__ == "__main__":
    main()