"""Semantic Scholar 学术文献检索工具（返回真实可溯源的论文记录）。

设计原则：所有文献记录均来自真实学术数据库（Semantic Scholar，覆盖 2 亿+ 论文），
返回真实 DOI / 作者 / 年份 / 期刊 / 被引次数，天然杜绝编造文献。

模块同时导出：
- `search_literature(...)`：纯函数，main.py 直接调用以抓取真实数据（可溯源铁律的基准）。
- `literature_search`：经 `@tool` 包装的 CrewAI 工具对象，供 Agent 在 Crew 内调用。
"""
import os
import time
import requests
from crewai.tools import tool


def search_literature(query: str, limit: int = 15) -> str:
    """在 Semantic Scholar 中检索真实存在的学术论文。

    返回每篇论文的标题、作者、年份、期刊/会议、DOI、被引次数、摘要片段。
    所有记录均可点开 DOI 溯源，适用于文献综述、立项依据参考文献收集等场景。
    """
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    fields = "title,year,authors,doi,citationCount,abstract,venue,externalIds"
    params = {"query": query, "limit": min(limit, 100), "fields": fields}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    headers = {"x-api-key": api_key} if api_key else {}

    # 免费接口常因频率限制返回 429，做简单退避重试以提升稳定性
    data = None
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 429:
                time.sleep(3 * (2 ** attempt))
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 3:
                return f"检索失败：{exc}"
            time.sleep(2)
    if data is None:
        return "检索失败：多次重试后仍无法获取数据，请稍后重试或配置 SEMANTIC_SCHOLAR_API_KEY。"

    papers = data.get("data", [])
    if not papers:
        return "未检索到相关论文，请调整关键词。"

    lines = []
    for p in papers:
        authors = ", ".join(a.get("name", "") for a in p.get("authors", [])[:3])
        doi = p.get("doi") or (p.get("externalIds") or {}).get("DOI") or "N/A"
        abstract = (p.get("abstract") or "")[:280].replace("\n", " ")
        lines.append(
            f"- {p.get('title', '?')} ({p.get('year', '?')}) | {authors} | "
            f"{p.get('venue', '?')} | DOI:{doi} | 被引:{p.get('citationCount', '?')}\n"
            f"  摘要: {abstract}"
        )
    header = f"# Semantic Scholar 检索结果（query='{query}', 共 {len(papers)} 篇）\n"
    return header + "\n".join(lines)


# 给 CrewAI 用的工具包装
literature_search = tool("Semantic Scholar 学术文献检索")(search_literature)
