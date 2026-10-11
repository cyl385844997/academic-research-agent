"""备用学术文献检索：OpenAlex（openalex.org，免 key、日限宽松）。

作为 Semantic Scholar 的容错回退：当 S2 限流（429）或不可用时自动启用，
同样只返回**真实可溯源**的论文记录（标题/作者/年份/期刊/DOI/被引）。

模块导出：
- `search_openalex(...)`：纯函数
- `openalex_search`：经 `@tool` 包装的 CrewAI 工具对象
"""
import requests
from crewai.tools import tool

OPENALEX_API = "https://api.openalex.org/works"
# OpenAlex 建议带上 mailto 进入更宽松的礼貌池
MAILTO = "ylin_000@163.com"


def search_openalex(query: str, limit: int = 15) -> str:
    """在 OpenAlex 中检索真实存在的学术论文，返回可溯源记录。

    返回每篇论文的标题、作者、年份、期刊、DOI、被引次数。
    """
    params = {"search": query, "per-page": min(limit, 50), "mailto": MAILTO}
    headers = {"User-Agent": f"academic-research-agent/0.1 (mailto:{MAILTO})"}
    try:
        resp = requests.get(OPENALEX_API, params=params, headers=headers, timeout=40)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return f"OpenAlex 检索失败：{exc}"

    works = data.get("results", [])
    if not works:
        return "OpenAlex 未检索到相关论文，请调整关键词。"

    lines = []
    for w in works:
        title = w.get("title") or w.get("display_name") or "?"
        year = w.get("publication_year") or "?"
        venue = (
            (w.get("primary_location") or {}).get("source")
            or {}
        ).get("display_name", "?")
        authors = ", ".join(
            a.get("author", {}).get("display_name", "")
            for a in (w.get("authorships") or [])[:3]
            if a.get("author")
        )
        doi = w.get("doi") or ""
        # OpenAlex 的 DOI 形如 https://doi.org/10.xxxx/xxxx，去掉前缀
        if doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/"):]
        if not doi:
            doi = "N/A"
        cited = w.get("cited_by_count", "?")
        lines.append(
            f"- {title} ({year}) | {authors} | {venue} | DOI:{doi} | 被引:{cited}"
        )
    header = f"# OpenAlex 检索结果（query='{query}', 共 {len(works)} 篇）\n"
    return header + "\n".join(lines)


# 给 CrewAI 用的工具包装
openalex_search = tool("OpenAlex 学术文献检索（备用源）")(search_openalex)
