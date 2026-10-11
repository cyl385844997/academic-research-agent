"""知网中文文献检索（通过 cnki-mcp，非本项目自行实现）。

**为什么用外部项目**：知网/万方/维普均无公开检索 API。本模块不自行爬取，
而是调用第三方开源项目 [cnki-mcp](https://github.com/SepineTam/cnki-mcp)——
它通过 Playwright 驱动**用户自己完成认证登录后**的浏览器会话进行检索，
性质等同于 Zotero / EndNote 在用户自己的账号下操作。

**合规约束（务必遵守）**：
- 仅做交互式、单主题、低频检索；cnki-mcp 自身已内置每秒 1 次、每日 1000 次配额；
- **不做批量抓取、不下载全文**（cnki-mcp 也不提供全文下载）；
- 本项目**不存储、不转发**任何账号凭证；登录态由 cnki-mcp 自行管理于
  `~/.cnki-mcp/profiles/`，属用户本地目录。

依赖：需先安装 cnki-mcp 并完成 `cnki-mcp init`（用户本人操作，见 README）。
若未安装或未登录，本模块会返回明确的失败提示，由上层如实转述——
**绝不因中文检索失败而编造文献**。
"""
import os
import re
import sys
import shutil
from pathlib import Path

# cnki-mcp 仓库的本地路径（用户克隆位置）
_CNKI_MCP_REPO = os.getenv(
    "CNKI_MCP_REPO",
    str(Path(__file__).resolve().parents[3] / "cnki-mcp"),
)


def _cnki_mcp_available() -> bool:
    """检查 cnki-mcp 是否已就绪（仓库存在 + uv 可用 + CLI 可调用）。"""
    repo = Path(_CNKI_MCP_REPO)
    if not (repo / "pyproject.toml").exists():
        return False
    return shutil.which("uv") is not None


def _run_cli(args: list[str], timeout: int = 180) -> tuple[int, str, str]:
    """在 cnki-mcp 仓库目录内执行 CLI 命令，返回 (退出码, stdout, stderr)。

    浏览器复用 Edge 的补丁已通过 site-packages 中的 .pth 钩子全局生效
    （见 cnki-mcp/edge_patch.py 同源实现），故此处无需额外前缀。
    """
    import subprocess

    try:
        proc = subprocess.run(
            ["uv", "run", "cnki-mcp", *args],
            cwd=str(Path(_CNKI_MCP_REPO)),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"知网检索超时（>{timeout}s），可能未登录或网络受限"
    except Exception as exc:  # noqa: BLE001
        return 1, "", f"知网检索异常：{exc}"


def build_advanced_query(topic: str, journal: str = "") -> str:
    """把普通中文主题词转换为知网专业检索式（显著提升召回质量）。

    实测对比（主题「侧流生物除磷」）：
      - 普通关键词检索            → 只返回 2 篇
      - `SU='侧流' * '除磷'`       → 返回 15 篇，且多为核心刊

    检索式语法（知网官方）：
        SU=主题  TKA=篇关摘  KY=关键词  TI=篇名  AB=摘要
        LY=文献来源  DOI=DOI  CF=被引频次  AU=作者  AF=作者单位
        多词 `*`=与、`+`=或、`-`=非

    切词原则：**不做机械滑窗切分**。实测 2-gram 滑窗会产出「流生」「物除」
    这类跨词垃圾，导致检索式命中 0 篇。改为：
      - 优先用空格/标点分隔的独立词块；
      - 无分隔的长词直接整体作为主题词（知网 SU 支持长词组）；
      - 只有当整体词过长（>8 字）且确需拆分时才用 2-gram 兜底。

    Args:
        topic: 中文主题词，如「侧流生物除磷」
        journal: 可选，限定期刊（配合北大核心白名单精准检索）
    """
    import re as _re

    # 1) 先取空格/标点分隔的独立词块
    blocks = [b for b in _re.split(r"[\s\-/、,，]+", topic or "") if b]
    tokens: list[str] = []
    for b in blocks:
        for seg in _re.findall(r"[\u4e00-\u9fff]+", b):
            if len(seg) <= 8:  # 常规长度的专业词整体保留
                tokens.append(seg)
            else:
                # 超长词才拆分（兜底），并保留原词
                grams = [seg[i : i + 2] for i in range(len(seg) - 1)]
                seen, kept = set(), []
                for g in grams:
                    if g not in seen:
                        seen.add(g)
                        kept.append(g)
                tokens.append(seg)
                tokens.extend(kept[:2])

    # 2) 去重保序 + 剔除过泛词
    generic = {"工艺", "研究", "应用", "分析", "技术", "方法", "实验", "效果", "研究进展"}
    seen, tks = set(), []
    for t in tokens:
        if t and t not in seen and t not in generic:
            seen.add(t)
            tks.append(t)
    tks = tks[:4]

    if len(tks) >= 2:
        # 多词块：用「与」连接（各自作为主题条件）
        expr = "SU=(" + " * ".join(f"'{t}'" for t in tks) + ")"
    elif tks:
        # 单一长词块：叠加「篇关摘」模糊检索，提升召回
        # （实测 SU 整体词召回偏少，TKA 更宽松）
        expr = f"SU='{tks[0]}' or TKA='{tks[0]}'"
    else:
        expr = f"SU='{topic}'"
    if journal:
        expr += f" and LY='{journal}'"
    return expr


def search_cnki(query: str, limit: int = 15) -> str:
    """通过 cnki-mcp 在知网检索真实中文文献。

    输出格式与本项目其它源保持一致：
    `- {title} ({year}) | {authors} | {venue} | DOI:{doi} | 被引:{n} | 语言:zh`

    Args:
        query: 检索式。推荐使用知网专业检索式以精确限定，例如
            ``"SU='侧流生物除磷' and LY='中国给水排水'"``
            可用字段：SU主题 TKA篇关摘 KY关键词 TI篇名 FT全文 AU作者
            AF作者单位 FU基金 AB摘要 LY文献来源 DOI DOI CF被引频次
        limit: 最多返回条数。

    Returns:
        统一格式的检索结果文本；不可用时返回以"检索失败"开头的说明。
    """
    if not _cnki_mcp_available():
        return (
            "知网检索不可用：未检测到 cnki-mcp。\n"
            "需先安装并初始化（一次性）：\n"
            "  git clone https://github.com/SepineTam/cnki-mcp.git\n"
            "  cd cnki-mcp && uv sync && uv run playwright install chromium\n"
            "  uv run cnki-mcp init   # 需用户本人在浏览器完成知网认证"
        )

    code, out, err = _run_cli(["tool", "search", "--advanced", query, "--limit", str(limit)])

    if code != 0:
        detail = (err or out).strip()[:300]
        # 常见原因：未初始化 / 未登录
        if "init" in detail.lower() or "profile" in detail.lower() or "login" in detail.lower():
            return (
                "知网检索失败：尚未初始化或未登录知网。\n"
                "请在终端执行 `uv run cnki-mcp init`，按提示在浏览器中完成知网账号认证。"
            )
        return f"知网检索失败：{detail}"

    return _parse_cnki_json(out, query)


def _parse_cnki_json(raw: str, query: str) -> str:
    """把 cnki-mcp 的 JSON 输出转成本项目统一格式。

    CLI search 返回精简字段：title / authors / journal / date；
    被引频次、DOI 等需 info 接口补全，这里先用可获得字段，
    缺失的以 N/A 占位（由上层白名单与相关性逻辑继续处理）。
    """
    import json
    import re

    if not raw.strip():
        return "知网未返回结果，请调整检索式。"

    # CLI 可能输出日志前缀，用首个 [ 或 { 起始处解析
    data = None
    for start in ("[", "{"):
        idx = raw.find(start)
        if idx >= 0:
            try:
                data = json.loads(raw[idx:])
                break
            except Exception:  # noqa: BLE001
                continue
    if data is None:
        # 回退：按行解析 "- 标题" 形式
        lines = [l.strip() for l in raw.splitlines() if l.strip().startswith("-")]
        if not lines:
            return f"知网返回格式无法解析：{raw[:200]}"
        data = [{"title": l.lstrip("- ").strip(), "journal": "?", "date": "?", "authors": []}]

    if isinstance(data, dict):
        data = data.get("results") or data.get("data") or [data]

    lines = []
    for it in data:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        authors = it.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        authors = "; ".join(str(a) for a in authors[:3])
        venue = (it.get("journal") or it.get("source") or "?").strip()
        date = str(it.get("date") or it.get("year") or "?").strip()
        year = date[:4] if date[:4].isdigit() else "?"
        doi = (it.get("doi") or "N/A").strip()
        cited = it.get("citationCount") or it.get("cited") or it.get("CF") or "?"
        lines.append(
            f"- {title} ({year}) | {authors} | {venue} | DOI:{doi} | 被引:{cited} | 语言:zh"
        )

    if not lines:
        return "知网未返回符合条件的文献，请调整检索式。"
    header = f"# 知网检索结果（query='{query}', 共 {len(lines)} 篇）\n"
    return header + "\n".join(lines)


def search_cnki_core_journal(query: str, journal: str, limit: int = 10) -> str:
    """限定某本核心期刊内检索（配合北大核心白名单使用）。

    Args:
        query: 主题检索式，如 ``SU='侧流' * '除磷'``
        journal: 期刊名，须在 `tools.core_journals` 白名单内（如 "中国给水排水"）
    """
    combined = f"({query}) and LY='{journal}'"
    return search_cnki(combined, limit=limit)

# ---------- CrewAI 工具包装 ----------
# 延迟导入 crewai，保证在无 crewai 环境下本模块仍可被 main.py 使用
try:
    from crewai.tools import tool as _crew_tool

    cnki_search = _crew_tool("知网中文文献检索")(search_cnki)
except Exception:  # noqa: BLE001
    cnki_search = None
