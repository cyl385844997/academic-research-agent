"""学术前期研究 Agent - 入口 CLI。

用法：
  python src/main.py --mode literature --topic "side-stream EBPR wet weather overflow"
  python src/main.py --mode market    --topic "AI 基金申请书 产品 2026"

依赖（在项目根目录执行）：
  pip install -r requirements.txt
  cp .env.example .env   # 然后填入你的 API key
"""
import os
import re
import sys
import argparse

# 确保项目根目录在 sys.path 中，使 `from src...` 在任何启动方式下都能解析
# （直接 `python src/main.py` 时 Python 只把 src/ 放进路径，会找不到顶层 src 包）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import dotenv

# 显式从项目根目录加载 .env，避免依赖当前工作目录
dotenv.load_dotenv(os.path.join(_ROOT, ".env"))

from crewai import LLM

from src.crews.literature_crew import build_literature_crew
from src.crews.market_crew import build_market_crew
from src.tools.literature_tool import literature_search, search_literature
from src.tools.web_tool import web_search, search_web


def get_llm():
    """构造 LLM。默认 OpenAI；若配置 OPENAI_BASE_URL 则走兼容端点（如 Agnes）。

    注意：CrewAI 1.x 的 Agent 只接受自家 `crewai.LLM` 包装（不接受裸 LangChain ChatModel），
    因此这里统一返回 LLM 实例；`openai/` 前缀强制走 OpenAI 兼容协议。
    """
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    kwargs = dict(
        model=f"openai/{model}",
        api_key=os.getenv("OPENAI_API_KEY", ""),
        temperature=0.3,
    )
    base = os.getenv("OPENAI_BASE_URL")
    if base:
        kwargs["base_url"] = base
    return LLM(**kwargs)


def parse_ss_papers(raw: str):
    """从 literature_search 的真实返回中解析出结构化文献列表（标题/年份/作者/DOI/期刊/被引）。"""
    papers = []
    for line in raw.splitlines():
        s = line.strip()
        if not s.startswith("- "):
            continue
        body = s[2:].strip()
        if " | " not in body:
            continue
        parts = [p.strip() for p in body.split(" | ")]
        if len(parts) < 5:
            continue
        tp = parts[0]
        m = re.match(r"^(.*?)\s*\((\d{4})\)\s*$", tp)
        title = m.group(1) if m else tp
        year = m.group(2) if m else ""
        authors = parts[1]
        venue = parts[2]
        doi = parts[3].replace("DOI:", "", 1).strip()
        cit = parts[4].replace("被引:", "", 1).strip()
        if not doi or doi == "N/A":
            continue
        papers.append(
            {"title": title, "year": year, "authors": authors, "doi": doi, "venue": venue, "citations": cit}
        )
    return papers


def parse_web_results(raw: str):
    """从 web_search 的真实返回中解析出结构化来源列表（标题/URL/摘要）。"""
    items = []
    lines = raw.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if not (s.startswith("- ") and "http" in s):
            continue
        body = s[2:].strip()
        if ": " not in body:
            continue
        title, url = body.split(": ", 1)
        url = url.strip()
        snippet = ""
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if nxt.startswith("摘要:"):
            snippet = nxt[len("摘要:"):].strip()
        if url.startswith("http"):
            items.append({"title": title.strip(), "url": url, "snippet": snippet})
    return items


def append_grounded_refs(report_path: str, block: str):
    """把系统生成的真实文献/来源表追加到报告末尾，并剥离撰稿员可能自行生成的伪造表。"""
    if not os.path.exists(report_path):
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(block + "\n")
        return
    with open(report_path, encoding="utf-8") as f:
        content = f.read()
    # 剥离可能由 LLM 自行编造的文献/来源区块（保留正文分析）
    content = re.sub(r"##\s*TSV?\s*文献表.*?```\s*", "", content, flags=re.DOTALL)
    content = re.sub(r"##\s*来源链接表.*?```\s*", "", content, flags=re.DOTALL)
    content = re.sub(r"##\s*参考(文献|链接|来源).*?```\s*", "", content, flags=re.DOTALL)
    content = content.rstrip() + "\n\n" + block + "\n"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    parser = argparse.ArgumentParser(description="学术前期研究 Agent（论文检索 / 市场调研）")
    parser.add_argument(
        "--mode",
        choices=["literature", "market"],
        required=True,
        help="literature=论文检索综述；market=市场/竞品调研",
    )
    parser.add_argument("--topic", required=True, help="研究主题 / 检索词")
    args = parser.parse_args()

    llm = get_llm()
    tools = [literature_search, web_search]
    os.makedirs("reports", exist_ok=True)

    if args.mode == "literature":
        # 1) 真实检索：可溯源铁律的基准数据（由代码持有，LLM 不碰）
        raw = search_literature(args.topic, 15)
        papers = parse_ss_papers(raw)
        ref_tsv = os.path.join("reports", "literature_references.tsv")
        tsv_lines = ["标题\t年份\t作者\tDOI\t期刊\t被引"]
        for p in papers:
            tsv_lines.append(f"{p['title']}\t{p['year']}\t{p['authors']}\t{p['doi']}\t{p['venue']}\t{p['citations']}")
        with open(ref_tsv, "w", encoding="utf-8") as f:
            f.write("\n".join(tsv_lines) + "\n")
        # 2) 注入真实结果运行 Crew（只做分析，不生成文献表）
        crew = build_literature_crew(args.topic, llm, tools, search_results=raw)
        crew.kickoff()
        # 3) 后处理：剥离可能伪造的 TSV，追加真实 TSV
        report_path = os.path.join("reports", "literature_report.md")
        tsv_block = (
            "## TSV 文献表（真实检索结果，系统自动生成，绝不编造）\n\n```\n"
            + "\n".join(tsv_lines)
            + "\n```"
        )
        append_grounded_refs(report_path, tsv_block)
        print(f"\n===== 完成：报告={report_path}，真实文献 {len(papers)} 篇，TSV={ref_tsv} =====\n")

    else:  # market
        raw = search_web(args.topic, 8)
        items = parse_web_results(raw)
        ref_tsv = os.path.join("reports", "market_references.tsv")
        tsv_lines = ["标题\tURL\t摘要"]
        for it in items:
            tsv_lines.append(f"{it['title']}\t{it['url']}\t{it['snippet']}")
        with open(ref_tsv, "w", encoding="utf-8") as f:
            f.write("\n".join(tsv_lines) + "\n")
        crew = build_market_crew(args.topic, llm, tools, search_results=raw)
        crew.kickoff()
        report_path = os.path.join("reports", "market_report.md")
        tsv_block = (
            "## 来源链接表（真实检索结果，系统自动生成，绝不编造）\n\n```\n"
            + "\n".join(tsv_lines)
            + "\n```"
        )
        append_grounded_refs(report_path, tsv_block)
        print(f"\n===== 完成：报告={report_path}，真实来源 {len(items)} 条，TSV={ref_tsv} =====\n")


if __name__ == "__main__":
    main()
