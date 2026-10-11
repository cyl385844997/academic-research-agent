"""Web 网络检索工具：优先 Tavily（需 key），回退 DuckDuckGo（ddgs，免 key）。

用于市场调研、竞品分析、政策与最新动态搜索——这类信息没有学术 DOI，
需靠 Web 检索覆盖。同样导出纯函数 `search_web(...)` 与 CrewAI 工具 `web_search`。
"""
import os
import requests
from crewai.tools import tool


def search_web(query: str, max_results: int = 8) -> str:
    """检索互联网网页，返回标题、链接与摘要片段。

    优先使用 Tavily API；未配置时回退到 DuckDuckGo（ddgs）。
    """
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": tavily_key, "query": query, "max_results": max_results},
                timeout=30,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            return "\n".join(
                f"- {i.get('title', '')}: {i.get('url', '')}\n  {(i.get('content') or '')[:280]}"
                for i in results
            ) or "Tavily 未返回结果。"
        except Exception as exc:  # noqa: BLE001
            return f"Tavily 检索失败：{exc}（可配置 TAVILY_API_KEY 或安装 ddgs 回退）"

    # 回退 DuckDuckGo
    try:
        from ddgs import DDGS
    except ImportError:
        return "未配置 TAVILY_API_KEY，且未安装 ddgs。请执行 `pip install ddgs` 或配置 Tavily key。"
    try:
        out = []
        with DDGS() as ddgs:
            for i in ddgs.text(query, max_results=max_results):
                out.append(f"- {i.get('title', '')}: {i.get('href', '')}\n  {(i.get('body') or '')[:280]}")
        return "\n".join(out) or "DuckDuckGo 未返回结果。"
    except Exception as exc:  # noqa: BLE001
        return f"DuckDuckGo 检索失败：{exc}"


# 给 CrewAI 用的工具包装
web_search = tool("Web 网络检索")(search_web)
