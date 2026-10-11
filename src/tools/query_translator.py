"""中文主题 → 英文检索式转换（基于 LLM，领域术语化）。

解决什么问题：学术检索的中英文数据库是两套体系，中文主题词直接丢给
Semantic Scholar / OpenAlex / Crossref 会返回完全无关的内容
（实测「侧流生物除磷」→ Crossref 返回「水母幼虫」「飞溅侵蚀」）。

而如果只查知网，就会丢掉英文文献——环境工程领域的核心成果
（Water Research、ES&T 等）几乎全部发表在英文期刊上。

因此中文输入时，用 LLM 把主题转成国际期刊通用术语，再分别检索中英文。

**重要约束**：本模块只负责「生成检索式」，**不参与文献内容的生成**。
文献记录一律由真实学术库返回、代码解析并写入 TSV，LLM 不接触文献表，
以维护「可溯源铁律」（详见 AGENTS.md）。
"""
import os
import re

# 转换模板：强调领域术语而非字面直译
_PROMPT_TEMPLATE = """你是环境工程/污水处理领域的文献检索专家。请把下面的中文主题转换为国际期刊常用的英文检索式。

要求：
1. 输出 2-3 个英文检索式，用分号分隔
2. 必须使用该领域的国际通用术语（专业术语，不是逐字直译）
3. 只使用**该领域论文标题中真实出现过**的词，不要生造复合词
4. 避免使用罕见或只在非学术语境出现的词；宁可用宽泛的常用术语
5. 每个检索式 3-8 个关键词
6. 只输出检索式本身，不要任何解释

中文主题：{topic}
英文检索式："""


def _get_llm():
    """构造用于翻译的 LLM。

    注意：Agnes 等 OpenAI 兼容端点直连时用**原始模型名**（如
    `agnes-2.5-flash`），不带 `openai/` 前缀——该前缀是 litellm/CrewAI
    的约定，langchain_openai 直连时会导致 model_not_found。
    """
    from langchain_openai import ChatOpenAI

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    kwargs = dict(
        model=model,
        api_key=os.getenv("OPENAI_API_KEY", ""),
        temperature=0.2,
    )
    base = os.getenv("OPENAI_BASE_URL")
    if base:
        kwargs["base_url"] = base
    return ChatOpenAI(**kwargs)


# 翻译质量闸门：出现以下情形视为幻觉，整条检索式丢弃
_HALLUCINATION_MARKERS = (
    "leisure",          # 「高水位」误译为 leisure level（休闲水位）
    "sanitarium",
    "fun",              # 「溢流/溢水」误译
    "drainage basin recreational",
)


def _clean_queries(text: str, topic: str) -> list[str]:
    """从 LLM 输出中清洗出干净的检索式列表。

    质量闸门（实测教训）：LLM 偶发产出臆造词，如把「高水位」译成
    `"leisure level"`。这类检索式丢给 Crossref 会召回大量无关文献
    （实测召回洪水/钩端螺旋体病等传染病学文献）。故：
      - 命中臆造词黑名单 → 整条丢弃；
      - 纯中文/含中文 → 丢弃；
      - 检索式过短（<2 个有效词）→ 丢弃。
    """
    out = []
    for seg in re.split(r"[;；\n]", text or ""):
        q = seg.strip().strip("-*").strip()
        if not q or len(q) < 8:
            continue
        low = q.lower()
        # 臆造词闸门
        if any(m in low for m in _HALLUCINATION_MARKERS):
            continue
        # 必须含足量英文词
        words = re.findall(r"[A-Za-z]{3,}", q)
        if len(words) < 2:
            continue
        # 不得含中文
        if re.search(r"[\u4e00-\u9fff]", q):
            continue
        out.append(q)
    return out


def translate_to_english_queries(topic: str, max_queries: int = 3) -> list[str]:
    """把中文主题转换为英文检索式列表；失败时返回空列表。

    Args:
        topic: 中文主题词，如「侧流生物除磷」
        max_queries: 最多返回几条检索式

    Returns:
        英文检索式列表；LLM 不可用或输出无效时返回 []（调用方需能降级）。
    """
    topic = (topic or "").strip()
    if not topic:
        return []
    try:
        llm = _get_llm()
        resp = llm.invoke(_PROMPT_TEMPLATE.format(topic=topic))
        queries = _clean_queries(resp.content or "", topic)
        return queries[:max_queries]
    except Exception:  # noqa: BLE001
        # 翻译失败不能影响主流程——如实返回空，调用方跳过英文检索
        return []


def build_bilingual_query(topic: str, max_queries: int = 3) -> tuple[str, list[str]]:
    """为中文主题生成英文检索式。

    Args:
        topic: 原始检索词（可中可英）
        max_queries: 最多生成几条英文检索式

    Returns:
        (中文部分, 英文检索式列表)。英文部分为空表示无需翻译。
    """
    zh = " ".join(re.findall(r"[\u4e00-\u9fff]+", topic or "")).strip()
    if not zh:
        # 已是英文或中英混写，取其英文部分即可
        en = " ".join(re.findall(r"[A-Za-z][A-Za-z\-]*", topic or "")).strip()
        return "", [en] if en else []
    return zh, translate_to_english_queries(zh, max_queries)