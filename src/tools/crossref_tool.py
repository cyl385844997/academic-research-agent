"""备用学术文献检索（第二回退源）：Crossref（api.crossref.org，免 key）。

Crossref 是 DOI 注册库，覆盖极广（含 Water Research / ES&T 等期刊），
但也会混入「审稿意见 / 编辑决定信」等非论文记录，故本模块做关键词过滤。

模块导出：
- `search_crossref(...)`：纯函数
- `crossref_search`：经 `@tool` 包装的 CrewAI 工具对象
"""
import requests
from crewai.tools import tool

CROSSREF_API = "https://api.crossref.org/works"
MAILTO = "ylin_000@163.com"

# 过滤掉审稿意见、决定信、勘误、撤稿等非论文类记录
_EXCLUDE_KEYWORDS = (
    "review for",
    "decision letter",
    "author response",
    "reviewer",
    "referee report",
    "erratum",
    "corrigendum",
    "retraction",
    "withdrawn",
    "editorial",
    "front matter",
    "back matter",
    "contents of",
    "call for papers",
)


def search_crossref(query: str, limit: int = 15) -> str:
    """在 Crossref 中检索真实存在的学术文献，返回可溯源记录。

    输出格式与其它源保持一致：
    `- {title} ({year}) | {authors} | {venue} | DOI:{doi} | 被引:{n}`
    """
    params = {
        "query": query,
        "rows": max(limit * 3, 30),  # 多取一些，过滤后仍能凑够 limit
        "mailto": MAILTO,
        "select": "DOI,title,author,issued,container-title,is-referenced-by-count,type",
    }
    headers = {"User-Agent": f"academic-research-agent/0.1 (mailto:{MAILTO})"}
    try:
        resp = requests.get(CROSSREF_API, params=params, headers=headers, timeout=40)
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])
    except Exception as exc:  # noqa: BLE001
        return f"Crossref 检索失败：{exc}"

    lines = []
    for it in items:
        title = (it.get("title") or ["?"])[0]
        low = title.lower()
        # 过滤非论文记录
        if any(k in low for k in _EXCLUDE_KEYWORDS):
            continue
        # 只保留期刊论文等正式文献类型
        itype = it.get("type", "")
        if itype not in ("journal-article", "proceedings-article", "posted-content", "book-chapter"):
            continue

        parts = (it.get("issued", {}).get("date-parts") or [[None]])[0]
        year = parts[0] if parts else "?"
        venue = (it.get("container-title") or ["?"])[0]
        authors = ", ".join(
            " ".join(filter(None, [a.get("given"), a.get("family")])).strip()
            for a in (it.get("author") or [])[:3]
        )
        doi = it.get("DOI", "N/A")
        cited = it.get("is-referenced-by-count", "?")
        lines.append(
            f"- {title} ({year}) | {authors} | {venue} | DOI:{doi} | 被引:{cited}"
        )
        if len(lines) >= limit:
            break

    if not lines:
        return "Crossref 未检索到相关论文，请调整关键词。"
    header = f"# Crossref 检索结果（query='{query}', 共 {len(lines)} 篇）\n"
    return header + "\n".join(lines)


# 给 CrewAI 用的工具包装
crossref_search = tool("Crossref 学术文献检索（回退源）")(search_crossref)
