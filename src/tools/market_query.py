"""市场情报检索词拆解：把调研题目拆成可检索的多维查询。

【归档 2026-10-13】随市场调研线一并归档，暂不维护。
详见 docs/scope-decision-2026-10-13.md。

与文献检索的本质区别
--------------------
文献检索：一个主题 → 中英文各一条检索式（对象×条件×任务）。
市场检索：**产品名、技术词、公司名互不通用**——
    技术词搜不到具体产品（「AI 写作」搜不到 Elicit 的产品页）
    产品名搜不到同类竞品（搜「Elicit」只会得到 Elicit 本身）
    中文词搜不到国外竞品（搜「智能写作助手」搜不到 Elicit/Consensus）
因此必须**多维拆解 + 多角度检索**，最后合并去重。

**可溯源约束**：本模块只生成「检索式」，不生成任何产品信息或来源记录。
来源表由main.py 依据 Web 工具的真实返回解析生成（见 AGENTS.md 可溯源铁律）。
"""
import json
import os
import re

# ============ 检索维度定义 ============

# 维度键 → 中文名（写入报告的溯源章节）
DIMENSIONS = {
    "generic_cn": "通用中文",
    "generic_en": "通用英文",
    "product": "产品名",
    "vendor": "厂商/公司",
    "tech": "技术路线",
    "case": "应用案例/用户评价",
}

# 识别题目类型的关键词（用于决定各维度的侧重）
_MARKET_TYPE_HINTS = {
    "产品": ("产品", "工具", "软件", "平台", "系统", "方案", "product", "tool", "software", "platform"),
    "技术": ("技术", "工艺", "方法", "算法", "工艺路线", "technology", "method", "technique"),
    "案例": ("案例", "应用", "实践", "经验", "落地", "case", "application", "practice"),
    "竞品": ("竞品", "竞争", "对标", "替代", "competitor", "alternative"),
}

# 识别地区/时间限定词
_SCOPE_HINTS = (
    "中国", "国内", "国外", "全球", "国际", "2024", "2025", "2026",
    "政策", "标准", "国标", "行标", "规范",
)

_PARSE_PROMPT = """你是市场情报分析专家。请把下面的调研题目拆解成**可实际检索**的多维查询式。

【关键认知】不同维度必须分开检索，因为：
- 只搜技术词找不到具体产品（搜"AI写作"找不到某个具体产品页）
- 只搜产品名找不到同类竞品（搜某个产品名只有该产品本身）
- 中文词搜不到国外竞品，英文词搜不到国内产品

【严格要求】
1. 给出 4-6 条检索式，覆盖不同维度，**不要重复同一句话的翻译**
2. 每条标注维度（generic_cn / generic_en / product / vendor / tech / case）
3. **product/vendor 维度必须写你确定真实存在的公司或产品名**；
   拿不准的一律不要写，宁可只写generic_cn/tech 维度——虚构的产品名会污染调研
4. 中英文各覆盖一半
5. **JSON 键名必须严格统一为「维度」和「查询」**（不要写成 dimension/query）
6. 只输出 JSON，不要解释

输出格式：
{{"题型": "产品|技术|案例|竞品",
  "检索式": [
    {{"维度": "generic_cn", "查询": "..."}},
    {{"维度": "generic_en", "查询": "..."}},
    {{"维度": "tech", "查询": "..."}},
    {{"维度": "case", "查询": "..."}}
  ]}}

调研题目：{topic}"""


def _get_llm():
    """构造 LLM（兼容端点直连用原始模型名，不加 openai/ 前缀）。"""
    from langchain_openai import ChatOpenAI

    kwargs = dict(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        api_key=os.getenv("OPENAI_API_KEY", ""),
        temperature=0.15,
    )
    base = os.getenv("OPENAI_BASE_URL")
    if base:
        kwargs["base_url"] = base
    return ChatOpenAI(**kwargs)


def _extract_json(text: str):
    """从 LLM 输出提取 JSON（容忍代码块包裹）。"""
    if not text:
        return None
    t = re.sub(r"^```(?:json)?\s*", "", text.strip())
    t = re.sub(r"\s*```$", "", t)
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(t)):
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start : i + 1])
                except Exception:  # noqa: BLE001
                    return None
    return None


# ============ 校验与清洗 ============

# 幻觉词闸门（沿用文献检索的教训）
_HALLUCINATION_MARKERS = ("leisure", "sanitarium", "recreational")

# 明显的低质/无效查询
_BAD_PATTERNS = (
    "最好的", "推荐哪个", "十大", "排行榜", "哪个好", "怎么样",
    "如何选择", "教程", "入门", "小白",
)


def _clean_queries(items) -> list:
    """校验清洗检索式列表。

    要点（实测踩坑）：
    1. **键名兼容**：LLM 可能混用「查询」/「query」，只认前者会丢条目；
    2. **产品名核实成本高**：LLM 容易虚构产品（实测把「Elicit」文献工具
       列为污水巡检机器人竞品）。故 product/vendor 维度的查询若含
       明显跨领域词，程序无法核实——采取「保留但标注待核实」，
       由分析员在报告中判断，不在检索阶段硬删（否则会误删真竞品）。

    Returns:
        [{'维度': str, '查询': str, '需核实': bool}, ...]
    """
    out = []
    seen = set()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        dim = str(it.get("维度") or it.get("dimension") or "generic_cn").strip()
        # 键名兼容：查询 / query / q
        q = str(it.get("查询") or it.get("query") or it.get("q") or "").strip()
        if not q or len(q) < 3:
            continue
        low = q.lower()
        if any(m in low for m in _HALLUCINATION_MARKERS):
            continue
        # 排除「哪个好/推荐」这类非检索意图
        if any(b in q for b in _BAD_PATTERNS):
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        # 产品/厂商维度需人工核实（LLM 可能虚构），报告中标出即可
        need_verify = dim in ("product", "vendor")
        out.append({
            "维度": dim if dim in DIMENSIONS else "generic_cn",
            "查询": q,
            "需核实": need_verify,
        })
    return out


# ============ 规则回退（LLM 不可用时） ============


def _fallback_queries(topic: str) -> list:
    """规则回退：基于中英文原词 + 常见维度组合生成基础检索式。

    不做翻译（无 LLM 情况下无法保证术语正确），只做安全的形态扩展。
    """
    out = []
    topic = (topic or "").strip()
    if not topic:
        return out

    zh = " ".join(re.findall(r"[\u4e00-\u9fff]+", topic)).strip()
    en = " ".join(re.findall(r"[A-Za-z][A-Za-z\-]*", topic)).strip()

    if zh:
        out.append({"维度": "generic_cn", "查询": zh})
        out.append({"维度": "product", "查询": f"{zh} 产品"})
        out.append({"维度": "tech", "查询": f"{zh} 技术"})
    if en:
        out.append({"维度": "generic_en", "查询": en})
        out.append({"维度": "product", "查询": f"{en} product"})
    return out


# ============ 统一入口 ============


def build_market_queries(topic: str, max_queries: int = 6) -> dict:
    """拆解市场调研题目，生成多维检索式。

    Returns:
        {
          "题型": "产品",
          "queries": [{"维度": "generic_cn", "查询": "..."}, ...],
          "source": "LLM 拆解" | "规则回退",
        }
    """
    topic = (topic or "").strip()
    if not topic:
        return {"题型": "未知", "queries": [], "source": "无输入"}

    # 题型判断（规则，便宜可靠）
    qtype = "综合"
    for t, hints in _MARKET_TYPE_HINTS.items():
        if any(h.lower() in topic.lower() for h in hints):
            qtype = t
            break

    # LLM 拆解
    queries, source = [], "规则回退"
    try:
        llm = _get_llm()
        resp = llm.invoke(_PARSE_PROMPT.format(topic=topic))
        data = _extract_json(resp.content or "")
        if data:
            queries = _clean_queries(data.get("检索式"))
            if queries:
                source = "LLM 拆解"
                qtype = data.get("题型") or qtype
    except Exception:  # noqa: BLE001
        queries = []

    # LLM 失败或产出过少时，用规则补齐
    if len(queries) < 3:
        fb = _fallback_queries(topic)
        have = {q["查询"].lower() for q in queries}
        for q in fb:
            if q["查询"].lower() not in have:
                queries.append(q)
        if queries and source != "LLM 拆解":
            source = "规则回退"

    return {"题型": qtype, "queries": queries[:max_queries], "source": source}