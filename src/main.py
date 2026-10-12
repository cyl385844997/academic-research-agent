"""学术前期研究 Agent - 入口 CLI。

用法：
  python src/main.py --mode literature --topic "side-stream EBPR wet weather overflow"
  python src/main.py --mode market    --topic "AI 基金申请书 产品 2026"
  python src/main.py --mode memory    --topic "高水位"        # 查看与该主题相关的记忆
  python src/main.py --mode memory    --topic "list"         # 列出全部记忆
  python src/main.py --mode memory    --topic "stats"        # 记忆库统计
  python src/main.py --mode memory    --topic "refresh"      # 从最近会话日志自动提炼

记忆库（`memory/`）：长期积累的操作者偏好与领域约定，会注入 Crew 影响输出。
LLM 只提议、不直接落库；`memory/pending.md` 里的提案需人工确认。

依赖（在项目根目录执行）：
  pip install -r requirements.txt
  cp .env.example .env   # 然后填入你的 API key
"""
import os
import re
import time
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
from src.tools.openalex_tool import openalex_search, search_openalex
from src.tools.crossref_tool import crossref_search, search_crossref
from src.tools.cnki_tool import cnki_search, search_cnki, build_advanced_query
from src.tools.query_translator import understand_topic, translate_to_english_queries
from src.tools.core_journals import CORE_JOURNALS, CORE_JOURNAL_GROUPS
from src.tools.market_query import DIMENSIONS, build_market_queries
from src.tools import memory_store as ms
from src.tools.memory_store import build_memory_block
from src.tools import memory_extract as mx
from src.tools.source_credibility import (
    build_market_table,
    classify_source,
    dedupe_records,
)


def _norm_venue(s: str) -> str:
    """归一化期刊名：去除空白与常见副标题分隔符，便于与白名单比对。

    Crossref/OpenAlex 返回的刊名可能带"(中英文)"、空格或全半角差异，
    直接比较会漏判，故先归一化。
    """
    s = (s or "").strip()
    # 去掉中英文标记、空格、点号等噪声
    for ch in (" ", "　", "·", "・", ".", "．", "（", "）", "(", ")"):
        s = s.replace(ch, "")
    return s


_NORM_CORE = {_norm_venue(j) for j in CORE_JOURNALS}

# 学位论文类特征词：知网返回的学位论文没有期刊名，`journal` 字段是
# **学位授予单位**（如「西安理工大学」「哈尔滨工业大学」）。
# 这些不是期刊，不能拿期刊白名单去匹配，但学位论文本身质量可靠
# （尤其硕博论文对环境工程选题价值很高），应当保留并标注类型。
_THESIS_MARKERS = (
    "大学", "学院", "研究院", "研究所", "科学院",
)


def _is_thesis(venue: str) -> bool:
    """判断是否为学位论文记录（venue 实为学位授予单位）。"""
    v = (venue or "").strip()
    return any(m in v for m in _THESIS_MARKERS)


def _is_core_journal(venue: str) -> bool:
    """判断期刊是否在北大核心白名单内（归一化后精确匹配）。"""
    v = _norm_venue(venue)
    if not v or v == "?":
        return False
    if v in _NORM_CORE:
        return True
    # 部分源会追加"（中英文）"等后缀，做前缀匹配兜底
    return any(v.startswith(j) or j.startswith(v) for j in _NORM_CORE if len(j) >= 4)


def assess_quality(papers, topic="", en_topic=""):
    """对检索结果做质量评估，返回 (过滤后列表, 预警信息或None)。

    **中文文献的唯一判据是北大核心期刊白名单**（见 tools/core_journals.py，
    源自用户提供的《北大中文核心期刊要目总览》2023年版第十版）：
    - 中文文献：不在白名单内 → 一律剔除（中文库多为付费灌水刊）；
    - 英文文献：按主题相关性过滤，不做期刊限制（英文库本身质量可靠）。

    结果质量偏低时主动提示换检索词——宁可提示，也不闷头输出低质文献。
    """
    kept, dropped = [], []

    def tokens(s: str):
        """中文取连续汉字串、英文取>=3字母的词，用于相关性比对。"""
        s = (s or "").lower()
        return set(re.findall(r"[\u4e00-\u9fff]{2,}", s)), set(re.findall(r"[a-z]{3,}", s))

    topic_cn, topic_en = tokens(topic)
    # 实际用于英文检索的词（可能是 LLM 翻译所得），用于英文相关性判断
    _, en_topic_words = tokens(en_topic)
    if en_topic:
        en_topic_words = set(re.findall(r"[a-z]{3,}", en_topic.lower()))

    def relevant(title: str, lang: str) -> bool:
        """判断标题是否与检索词相关。

        **按语种分别比对**：中英混写的检索词里，中文文献不可能包含
        "sewer/pipeline" 等英文词，反之亦然；跨语种比对会误杀全部中文文献。
        """
        t_cn, t_en = tokens(title)
        if lang == "zh":
            return (not topic_cn) or bool(topic_cn & t_cn)
        return (not topic_en) or bool(topic_en & t_en)

    for p in papers:
        lang = p.get("lang", "en")
        venue = p.get("venue") or ""

        # 中文文献：以白名单为唯一判据
        if lang == "zh":
            # 学位论文：venue 是学位授予单位，非期刊，不适用期刊白名单。
            # 硕博论文对环境工程选题价值高，保留并在报告中标注类型。
            if _is_thesis(venue):
                kept.append(p)
                continue
            if not _is_core_journal(venue):
                dropped.append((p, f"非北大核心期刊（{venue or '未标注'}）"))
                continue
            # 核心刊也可能跑题，仍做相关性校验
            if topic_cn and not (topic_cn & tokens(p.get("title", ""))[0]):
                dropped.append((p, "主题不相关"))
                continue
            kept.append(p)
            continue

        # 英文文献：按「实际使用的英文检索词」做相关性过滤。
        # 注意不能用 topic 的英文部分——纯中文输入时它为空，
        # 会导致相关性检查被整体跳过，LLM 翻译偏差引入的噪声文献
        # （实测召回洪水/传染病学文献）全部放行。
        if en_topic_words and not (en_topic_words & tokens(p.get("title", ""))[1]):
            dropped.append((p, "主题不相关"))
            continue
        kept.append(p)

    warn = None
    n_zh_kept = sum(1 for p in kept if p["lang"] == "zh")
    if not n_zh_kept and any(p["lang"] == "zh" for p in papers):
        warn = (
            f"⚠️ 中文文献全部被过滤：检索到的中文记录均不在北大核心期刊白名单内"
            f"（共剔除 {sum(1 for p in papers if p['lang'] == 'zh')} 篇）。\n"
            f"原因：中文免费库（尤其 Crossref 中文部分）以付费灌水刊为主。\n"
            f"建议：① 知网/万方需人工补检（本项目不爬取付费库）；"
            f"② 优先用英文检索获取高质量文献；"
            f"③ 或换用核心刊常见的主题词（如「城镇污水处理」「排水管网」）。"
        )
    elif not kept:
        warn = (
            f"⚠️ 检索到的 {len(dropped)} 条记录全部被过滤。建议更换检索关键词。"
        )
    elif len(dropped) / max(len(papers), 1) >= 0.5:
        warn = (
            f"⚠️ 质量过滤：{len(dropped)}/{len(papers)} 条被剔除"
            f"（中文按北大核心白名单，英文按主题相关性）。"
        )
    return kept, warn
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



def _parse_citations(raw: str):
    """从 '被引:N' 片段解析被引数（无法解析返回 None）。"""
    m = re.search(r"被引:\s*(\d+)", raw)
    return int(m.group(1)) if m else None


def parse_ss_papers(raw: str):
    """从检索工具的真实返回中解析出结构化文献列表。

    输出列：标题/年份/作者/DOI/期刊/被引/语种。
    """
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
        lang = "?"
        if len(parts) >= 6:
            lang = parts[5].replace("语言:", "", 1).strip()
        if not title:
            continue
        # 注意：中文期刊论文常无 DOI（知网 CLI 返回即如此），
        # 不能因缺 DOI 而丢弃——标题/期刊/年份齐备即为可溯源记录。
        doi = "" if doi in ("N/A", "?") else doi
        # 语种最终以标题实际字符判定：数据源的 language 字段不可靠
        # （OpenAlex 实测会把中文期刊标成 en），字符判定最稳。
        cjk = sum(1 for ch in title if "\u4e00" <= ch <= "\u9fff")
        lang = "zh" if cjk >= 3 else "en"
        papers.append(
            {
                "title": title,
                "year": year,
                "authors": authors,
                "doi": doi,
                "venue": venue,
                "citations": cit,
                "lang": lang,
            }
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
        # 兼容两种格式：
        #   - 工具显式输出「摘要:...」（旧约定）
        #   - 工具输出普通缩进续行（ddgs / Tavily 实际返回，无「摘要:」前缀）
        # 凡下一条非新条目（不以 "- " 开头）且非空，均视作本条摘要。
        if nxt.startswith("摘要:"):
            snippet = nxt[len("摘要:"):].strip()
        elif nxt and not nxt.startswith("- "):
            snippet = nxt
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


def _norm_url(u: str) -> str:
    """规范化 URL 用于比对（去尾斜杠、小写 scheme+netloc+path）。"""
    u = (u or "").strip().rstrip("/")
    try:
        p = urlparse(u)
        return (p.scheme + "://" + p.netloc + p.path).lower().rstrip("/")
    except Exception:  # noqa: BLE001
        return u.lower().rstrip("/")


def sanitize_report_urls(report_path: str, allowed_urls):
    """可溯源硬性护栏：删除报告中任何不在「真实检索结果」集合内的 URL。

    原因：实测 CrewAI 撰稿员在 tools=[]（无联网）时，会凭自身记忆「补」出
    看似合理但并未检索到的链接（linkedin/researchgate/qq.com 等变体），
    即使 prompt 已要求「逐字照抄」。仅靠 prompt 不可靠，故做代码级兜底：
    凡是报告里出现、但不在 allowed_urls 中的链接，一律剥离（保留文字、标注待核实）。
    允许的 URL 集合来自真实检索记录；本函数运行在 Crew 写稿之后、对比表追加之前，
    而对比表本身含真实 URL，故不会被误伤。

    Args:
        report_path: 报告文件路径
        allowed_urls: 真实检索结果 URL 集合（list/set of str）
    """
    allowed = {_norm_url(u) for u in (allowed_urls or [])}
    if not os.path.exists(report_path) or not allowed:
        return
    with open(report_path, encoding="utf-8") as f:
        text = f.read()

    removed = 0

    # 1) markdown 链接 [文字](url)
    def _md(m):
        nonlocal removed
        label, url = m.group(1), m.group(2).strip()
        if _norm_url(url) in allowed:
            return m.group(0)
        removed += 1
        return f"{label}（来源待核实）"

    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", _md, text)

    # 2) 裸 URL（排除刚处理过的 markdown 链接内 URL；上一轮已替换为文字，故此处基本只剩裸链）
    def _bare(m):
        nonlocal removed
        url = m.group(0).strip()
        if _norm_url(url) in allowed:
            return url
        removed += 1
        return "（来源待核实）"

    text = re.sub(r"(?<!\()(?<!\])(?<!\[)(https?://[^\s)\]<>]+)", _bare, text)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(text)
    if removed:
        print(f"  ⚠️ URL 护栏：已剥离 {removed} 处非真实来源的链接（标记为「来源待核实」）")


# DOI 抽取：先粗取 \S+，再按中文标点/空白截断。注意不能按 ASCII 括号截断——
# ASCE 类真实 DOI 含括号（如 10.1061/(asce)0733-9429(2003)129:7(504)）。
_DOI_RE = re.compile(r"10\.\d{4,9}/\S{3,}")


def _clean_doi(s: str) -> str:
    """规整 DOI 用于比对：小写、去尾部标点、剔除不成对的右括号。"""
    t = re.split(r"[\s，。；、：,;）]", str(s or "").strip())[0]
    t = t.rstrip(".,;")
    while t.endswith(")") and t.count(")") > t.count("("):
        t = t[:-1]
    return t.lower()


def sanitize_report_citations(report_path: str, allowed_dois):
    """可溯源硬性护栏（引用级）：剔除报告中不在真实检索结果内的 DOI。

    背景（实测 2026-10-12）：学术线撰稿员在 tools=[]（无联网）时，不仅会编 URL，
    **更会编 DOI**——旧版 literature_report.md 引用 51 个 DOI，只有 1 个能在
    真实检索清单（literature_references.tsv）里找到，其余 50 个系凭参数记忆生成
    （如 10.1016/j.envres.2021.111609）。Crew 提示词里已写「逐字照抄、严禁编造」，
    但实测无效，故必须像 URL 一样做代码级兜底：凡 DOI 不在 allowed_dois 内，
    一律替换为「〔DOI 不可溯源，已剔除〕」并计数告警。

    Args:
        report_path: 报告文件路径
        allowed_dois: 真实检索结果的 DOI 集合（list/set of str，无 DOI 的记录传空串）
    Returns:
        被剔除的 DOI 清单（去重、保持出现顺序）
    """
    allowed = {_clean_doi(d) for d in (allowed_dois or []) if d}
    if not os.path.exists(report_path) or not allowed:
        return []
    with open(report_path, encoding="utf-8") as f:
        text = f.read()

    dropped = []

    def _sub(m):
        doi = _clean_doi(m.group(0))
        if doi in allowed:
            return m.group(0)
        if doi and doi not in dropped:
            dropped.append(doi)
        return "〔DOI 不可溯源，已剔除〕"

    text = _DOI_RE.sub(_sub, text)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(text)
    if dropped:
        print(f"  🚨 DOI 护栏：已剔除 {len(dropped)} 个不在检索结果中的编造引用")
        print(f"     例：{dropped[0]} / {dropped[1] if len(dropped) > 1 else ''}")
    return dropped


def _chinese_portion(topic: str) -> str:
    """从混合检索词中提取中文部分（知网只对中文查询有意义）。

    「城镇污水处理 side-stream EBPR」→ 「城镇污水处理」
    无中文时返回空字符串，表示不走知网。
    """
    cn = re.findall(r"[\u4e00-\u9fff]+", topic or "")
    return " ".join(cn).strip()


def _resolve_topic(topic: str) -> dict:
    """理解检索主题，产出中英文检索式（含来源与解释）。

    三层：领域词典 → LLM 概念解析 → 规则回退。
    返回结构供fetch_literature_grounded 使用与写入报告，保证可溯源。
    """
    zh = _chinese_portion(topic)
    # 原词已含英文时直接用，不做翻译
    en_in_topic = " ".join(re.findall(r"[A-Za-z][A-Za-z\-]*", topic or "")).strip()

    understanding = None
    if zh:
        understanding = understand_topic(zh)

    cnki_query = ""
    en_queries = []
    source = "未解析"
    explanation = ""
    concept = {}
    if understanding:
        cnki_query = understanding.get("cnki_query") or ""
        en_queries = understanding.get("english_queries") or []
        source = understanding.get("source") or "未解析"
        explanation = understanding.get("explanation") or ""
        concept = understanding.get("concept") or {}

    # 规则回退：词典与 LLM 都未给出可用检索式时，用切词规则兜底
    if zh and not cnki_query:
        from src.tools.cnki_tool import build_advanced_query
        cnki_query = build_advanced_query(zh)
        source = "规则回退（词典/LLM 未产出）"
    if en_in_topic:
        en_queries = [en_in_topic] + [q for q in en_queries if q != en_in_topic]

    return {
        "zh_query": zh,
        "cnki_query": cnki_query,
        "english_queries": en_queries[:4],
        "source": source,
        "explanation": explanation,
        "concept": concept,
    }


def _english_queries(topic: str, max_queries: int = 2) -> list[str]:
    """生成用于英文库检索的检索式列表。

    - 原词含英文 → 直接取英文部分（中英混写场景）；
    - 纯中文 → 交 LLM 转换出国际期刊通用术语（见 query_translator）。

    最多返回 max_queries 条，避免请求过多触发英文库限流。
    """
    en = " ".join(re.findall(r"[A-Za-z][A-Za-z\-]*", topic or "")).strip()
    if en:
        return [en]
    if _chinese_portion(topic):
        return translate_to_english_queries(_chinese_portion(topic), max_queries)
    return []


def _search_cnki_with_fallback(understanding: dict, limit: int):
    """知网检索 + 0 命中自动降级重试。

    降级阶梯（由严到宽）：
        1. 解析出的完整检索式（对象 * (条件 + 任务)）
        2. 去掉全部修饰词（仅对象）
        3. 整词 TKA 兜底
        4. 整词 SU 兜底
    只要任一阶梯召回>0 即停止。返回 (papers, trace)，
    trace 记录每级尝试与结果，写入报告以保证可溯源。
    """
    primary = understanding.get("cnki_query") or ""
    zh = understanding.get("zh_query") or ""
    concept = understanding.get("concept") or {}
    objs = concept.get("对象") or []

    ladder = []
    if primary:
        ladder.append(("完整式", primary))
    # 仅对象词
    obj = objs[0] if objs else (zh.split()[0] if zh else "")
    if obj:
        ladder.append(("仅对象词", f"SU='{obj}' or TKA='{obj}'"))
    if zh:
        ladder.append(("整词篇关摘", f"TKA='{zh}'"))
        ladder.append(("整词主题", f"SU='{zh}'"))

    papers, trace = [], []
    for label, query in ladder:
        raw = search_cnki(query, limit)
        got = [x for x in parse_ss_papers(raw) if x["lang"] == "zh"]
        trace.append(f"{label} `{query}` → {len(got)} 篇")
        if got:
            papers = got
            break
    return papers, trace


_LAST_TRACE = []


def fetch_literature_grounded(topic: str, limit: int = 15):
    """多源容错抓取真实文献：知网（中文）+ Semantic Scholar/OpenAlex/Crossref（英文）。

策略：
1. 检索词含中文 → 走知网（中文核心刊唯一可靠来源）；
2. 英文检索式：若原词已含英文则直接用；**若为纯中文，则用 LLM 转换**
   （中文词直接喂英文库会返回「水母幼虫」这类无关内容）；
3. 各源结果合并去重 → 质量过滤（中文按北大核心白名单）→ 中英文均衡。

全部源失败时如实返回失败原因，绝不编造。

返回 (raw_text, source_name, papers, warn)。
    """
    global _LAST_TRACE
    collected = []
    used_sources = []
    errors = []

    # 【主题理解】三层架构：领域词典 → LLM 概念解析 → 规则回退
    u = _resolve_topic(topic)
    trace_lines = [
        f"- 检索主题理解（来源：{u['source']}）",
    ]
    if u["concept"]:
        c = u["concept"]
        trace_lines.append(
            f"  - 语义拆解：对象={c.get('对象') or '—'}｜条件={c.get('条件') or '—'}｜任务={c.get('任务') or '—'}"
        )
    if u["explanation"]:
        trace_lines.append(f"  - 说明：{u['explanation']}")
    if u["cnki_query"]:
        trace_lines.append(f"  - 知网检索式：`{u['cnki_query']}`")

    # 【中文主源】知网 —— 中文核心刊的唯一可靠来源。
    # 0 命中时按阶梯自动降级重试（去修饰 → 仅对象 → 整词 TKA），
    # 避免因检索式过严而误判"无文献"。
    zh_query = u["zh_query"]
    if zh_query:
        papers_cnki, cnki_trace = _search_cnki_with_fallback(u, limit)
        trace_lines.append(f"  - 知网召回：{len(papers_cnki)} 篇")
        trace_lines.extend(f"    {t}" for t in cnki_trace)
        if papers_cnki:
            collected.extend(papers_cnki)
            used_sources.append("知网")
        else:
            errors.append("- **知网**：各降级阶梯均无结果")

    if u["english_queries"]:
        trace_lines.append("  - 英文检索式：" + "；".join(f"`{q}`" for q in u["english_queries"]))

    # 【英文源】英文检索式来源：
    #   - 原词含英文 → 直接使用；
    #   - 纯中文 → LLM 转成国际期刊通用术语（避免中文词污染英文库）。
    en_queries = u["english_queries"]
    if not en_queries and zh_query:
        errors.append(
            "- **英文检索**：未能从中文主题生成英文检索式（LLM 不可用），"
            "本次仅检索中文文献"
        )
    for en_query in en_queries:
        for name, fn in (
            ("Semantic Scholar", search_literature),
            ("OpenAlex", search_openalex),
            ("Crossref", search_crossref),
        ):
            raw = fn(en_query, limit)
            papers = parse_ss_papers(raw)
            # **Crossref 的中文库基本是灌水刊集散地**，只取其英文记录，
            # 中文文献交由知网负责。
            if name == "Crossref":
                en_only = [p for p in papers if p["lang"] != "zh"]
                zh_dropped = len(papers) - len(en_only)
                papers = en_only
                if zh_dropped:
                    errors.append(
                        f"- **Crossref**：已跳过 {zh_dropped} 条中文记录"
                        f"（该库中文部分以付费灌水刊为主，质量不可信）"
                    )
            if papers:
                collected.extend(papers)
                used_sources.append(name)

    if not collected:
        fail_msg = (
            "经依次尝试，以下检索渠道均未返回可用结果：\n"
            + "\n".join(errors)
            + "\n\n建议：稍后重试；或配置 SEMANTIC_SCHOLAR_API_KEY 提升速率；或缩短检索关键词。"
        )
        _LAST_TRACE = trace_lines
        return fail_msg, "无（三个源均失败）", [], None

    # 去重：有 DOI 用 DOI 作键；中文文献常无 DOI，退化为「标题+年份」去重
    seen = set()
    uniq = []
    for p in collected:
        k = p["doi"].lower() if p.get("doi") else f"{p['title'].strip().lower()}|{p.get('year','')}"
        if k not in seen:
            seen.add(k)
            uniq.append(p)

    # 先做质量过滤，再做中英文均衡——
    # 顺序很重要：若先均衡再过滤，中文配额会被不合格记录占掉，
    # 导致「知网明明拿到核心刊、最终却一篇不剩」。
    kept, warn = assess_quality(uniq, topic, en_topic=" ".join(en_queries))
    _LAST_TRACE = trace_lines  # 保存溯源信息供报告使用

    zh = [p for p in kept if p["lang"] == "zh"]
    en = [p for p in kept if p["lang"] != "zh"]

    # 中文至少保留 1/3（最低 2 篇），其余留给英文
    balanced = []
    if zh and en:
        # 中文核心刊数量本就少（多在 2-5 篇），均衡时**先把中文全部保住**，
        # 再用剩余配额补英文——否则会出现「中 2 / 英 57」这种失衡。
        take_zh = min(len(zh), max(limit // 2, 3))
        take_en = max(limit - take_zh, min(len(en), limit // 2))
        balanced = zh[:take_zh] + en[:take_en]
    elif zh:
        balanced = zh[:limit]
    else:
        balanced = en[:limit]

    # 重建注入给 Crew 的上下文文本
    uniq_sources = list(dict.fromkeys(used_sources))
    lines = [f"# 真实检索结果（来源：{'/'.join(uniq_sources)}，严禁编造、严禁替换）"]
    for p in kept:
        # 知网记录的 venue 字段可能是期刊名，也可能是学位授予单位
        kind = ""
        if p.get("lang") == "zh" and _is_thesis(p.get("venue", "")):
            kind = "（类型：学位论文，授予单位）"
        lines.append(
            f"- {p['title']} ({p['year']}) | {p['authors']} | {p['venue']}{kind} | "
            f"DOI:{p['doi']} | 被引:{p['citations']} | 语言:{p['lang']}"
        )
    raw_ctx = "\n".join(lines)
    return raw_ctx, "+".join(dict.fromkeys(used_sources)), kept, warn


def _cmd_memory(topic: str, confirm: bool = False) -> int:
    """记忆库 CLI：list / stats / recall / refresh / add / pending / stale / confirm / drop。"""
    from src.tools import memory_store as _ms

    op = (topic or "").strip()
    low = op.lower()

    if low in ("list", "ls"):
        items = _ms.list_entries(status=None)
        if not items:
            print("记忆库为空。可用 `--mode memory --topic \"refresh\"` 从会话日志自动提炼。")
            return 0
        for e in items:
            st = _ms.staleness(e)
            flag = {"active": "生效", "superseded": "已取代",
                    "rejected": "已否决", "draft": "草稿"}[e.status]
            mark = ""
            if st["stale"] and st["age"] is not None:
                mark = f"  ⚠️ 久未确认 {st['age']} 天（TTL {st['ttl']} 天）"
            print(f"[{e.id}|{e.kind}|{flag}] {e.title}{mark}")
        print(f"\n共 {len(items)} 条。编辑文件：{_ms.ENTRIES_DIR}")
        return 0

    if low in ("stats", "stat"):
        s = _ms.stats()
        print("记忆库统计：")
        print(f"  总条目 {s['total']}"
              f"（领域 {s['domain']} / 偏好 {s['user']} / 在办 {s['project']}）")
        print(f"  生效 {s['active']}｜已取代 {s['superseded']}"
              f"｜已否决 {s['rejected']}｜草稿 {s['draft']}")
        print(f"  会话日志 {s['daily_files']} 篇｜待审提案：{'有' if s['pending'] else '无'}")
        print(f"  久未确认 {s['stale']} 条"
              f"（已降权但仍生效，复审见 `--mode memory stale`）")
        print(f"  目录：{_ms.MEM_DIR}")
        return 0

    if low in ("stale", "review"):
        items = _ms.build_review_queue()
        if not items:
            print("没有久未确认的记忆。TTL："
                  f"user {_ms.TTL_DAYS['user']} 天 / "
                  f"project {_ms.TTL_DAYS['project']} 天 / "
                  f"domain {_ms.TTL_DAYS['domain']} 天")
            return 0
        print(f"久未确认的记忆（{len(items)} 条）。已降权 "
              f"×{_ms.STALE_FACTOR}，仍生效但可能不适用：\n")
        for st, e in items:
            last = (e.confirmed or e.updated or e.created or "未知")[:10]
            badge = {"user": "偏好", "project": "在办", "domain": "领域"}.get(e.kind, e.kind)
            over = st["age"] / max(1, st["ttl"])
            print(f"[{e.id}|{badge}] {e.title}")
            print(f"    上次确认 {last}｜已有 {st['age']} 天｜TTL {st['ttl']} 天"
                  f"｜超期 {over:.1f}×")
            print(f"    仍然成立 → --mode memory --topic \"confirm {e.id}\"")
            print(f"    已被取代 → --mode memory --topic \"drop {e.id}\"（转归档）")
            print()
        p = _ms.write_review_file()
        if p:
            print(f"复审清单已写入：{p}")
        return 0

    if low.startswith("confirm "):
        eid = op[8:].strip()
        e = _ms.confirm_entry(eid)
        if not e:
            print(f"未找到记忆 {eid}")
            return 1
        print(f"已确认 {e.id}：{e.title}")
        # 注意读 confirmed 而非 updated——touch() 不改 updated（内容没变），
        # 用 updated 会显示旧日期，看起来像确认没生效。
        print(f"下次复审：{(e.confirmed or '')[:10]} 起算 {e.kind} 的 TTL "
              f"（{_ms.ttl_days(e)} 天）")
        return 0

    if low.startswith("drop "):
        eid = op[5:].strip()
        e = _ms.get_entry(eid)
        if not e:
            print(f"未找到记忆 {eid}")
            return 1
        ok = _ms.delete_entry(eid)   # 默认转归档，可回溯
        print(f"{'已转归档' if ok else '处理失败'}：{eid} {e.title}")
        return 0 if ok else 1

    if low == "refresh":
        content = "\n".join(mx.refresh_from_daily(days=3))
        if not content.strip():
            print("最近没有会话日志，无可提炼内容。")
            return 0
        cands = mx.extract_candidates(content, source_desc="最近会话日志自动提炼")
        if not cands:
            mx._last_error()
            print("未提炼出候选记忆（或 LLM 不可用）。")
            return 0
        res = mx.promote_safe(cands, auto_write=confirm)
        verb = "已入库" if confirm else "演练"
        print(f"{verb}：提炼 {len(cands)} 条候选\n")
        for c in res["accepted"]:
            tag = "补充" if c.get("_relation") == "supplement" else "全新"
            print(f"  [{'已入库' if confirm else '可入库'}·{tag}] ({c['kind']}) {c['title']}")
            print(f"           理由：{c.get('reason', '')[:100]}")
        for c in res["pending"]:
            rel = c.get("_relation")
            why = {"conflict": "口径冲突", "same": "与既有重复", "unknown": "程序判不准"}[rel] \
                if rel in ("conflict", "same", "unknown") else "待审"
            print(f"  [待人工裁决·{why}] ({c['kind']}) {c['title']}")
            print(f"           {c.get('reason', '')[:100]}")
        if confirm:
            print(f"\n已写入 {_ms.ENTRIES_DIR}；待裁决 {len(res['pending'])} 条见 {_ms.PENDING_FILE}")
        else:
            print("\n以上仅为演练。确认要采纳请加 --confirm 重新运行，"
                  "或手动编辑 memory/pending.md。")
        n_stale = len(_ms.build_review_queue())
        if n_stale:
            print(f"\n另有 {n_stale} 条已生效的记忆久未确认（已降权但仍生效），"
                  f"见 `--mode memory stale`")
        return 0

    if low.startswith("add "):
        raw = op[4:].strip()
        if not raw:
            print("用法：--topic \"add <正文>\"（默认记为 user 偏好，可用 | 分隔标题）")
            return 1
        title, _, body = raw.partition("|")
        if not body:
            title, body = raw[:30], raw
        e = _ms.MemoryEntry(
            kind="user", title=title.strip(), body=body.strip(),
            source="操作者手动录入", tags=[], status="active",
        )
        e = _ms.save_entry(e, archive_reason="manual-add")
        print(f"已新增记忆 {e.id}：{e.title}")
        print(f"文件：{e.path}")
        return 0

    if low == "pending":
        p = _ms.PENDING_FILE
        if not p.exists():
            print("无待审提案。")
            return 0
        print(f"待审提案：{p}")
        print(p.read_text(encoding="utf-8"))
        return 0

    if low.startswith("log "):
        raw = op[4:].strip()
        if not raw:
            print('用法：--topic "log <本次会话要点>"（换行用 \\n）')
            return 1
        p = _ms.append_daily(["- " + ln for ln in raw.split("\\n") if ln.strip()])
        print(f"已记入会话日志：{p}")
        print("之后运行 `--mode memory --topic refresh` 可自动从中提炼长期记忆。")
        return 0

    if low == "pending-clear":
        ok = _ms.clear_pending()
        print("已清空待审提案。" if ok else "无待审提案。")
        return 0

    # 默认：按主题召回
    items = _ms.recall(op, limit=8)
    if not items:
        print(f"记忆库中无与「{op}」相关的条目。")
        return 0
    print(f"与「{op}」相关的记忆（{len(items)} 条）：\n")
    for e in items:
        badge = {"user": "偏好", "project": "在办", "domain": "领域"}.get(e.kind, e.kind)
        st = _ms.staleness(e)
        mark = ""
        if st["stale"] and st["age"] is not None:
            mark = f"  ⚠️ 久未确认 {st['age']} 天（TTL {st['ttl']} 天）"
        print(f"[{e.id}|{badge}] {e.title}{mark}")
        for ln in e.body.strip().splitlines():
            ln = _ms._strip_marker(ln)
            if ln:
                print(f"    {ln}")
        print()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="学术前期研究 Agent（论文检索 / 市场调研 / 记忆库）")
    parser.add_argument(
        "--mode",
        choices=["literature", "market", "memory"],
        required=True,
        help="literature=论文检索综述；market=市场/竞品调研；memory=记忆库管理",
    )
    parser.add_argument("--topic", required=True,
                        help="研究主题 / 检索词；memory 模式下支持 "
                             "list|stats|stale|recall|refresh|add <内容>|pending|"
                             "confirm <ID>|drop <ID>|pending-clear")
    parser.add_argument("--confirm", action="store_true",
                        help="memory refresh 时真正写入记忆库（默认仅演练预览）")
    args = parser.parse_args()

    os.makedirs("reports", exist_ok=True)

    if args.mode == "memory":
        return _cmd_memory(args.topic, confirm=args.confirm)

    llm = get_llm()
    tools = [literature_search, openalex_search, crossref_search, web_search]
    os.makedirs("reports", exist_ok=True)

    # 记忆召回：与主题相关的长期偏好/约定注入 Crew（无记忆时为空串，不影响主流程）
    mem_block = build_memory_block(args.topic, limit=8)
    if mem_block:
        n = len(ms.recall(args.topic, limit=8))
        print(f"[记忆] 召回 {n} 条相关记忆，已注入分析上下文")
    else:
        print("[记忆] 无相关记忆，按通用方式处理")

    if args.mode == "literature":
        # 1) 真实检索：可溯源铁律的基准数据（由代码持有，LLM 不碰）
        print("[1/3] 正在检索真实学术库（Semantic Scholar → OpenAlex → Crossref）...")
        raw, source, papers, warn = fetch_literature_grounded(args.topic, 15)
        if warn:
            print(warn)

        n_zh = sum(1 for p in papers if p["lang"] == "zh")
        n_en = len(papers) - n_zh
        print(f"      来源={source}｜中文文献 {n_zh} 篇｜英文文献 {n_en} 篇")

        ref_tsv = os.path.join("reports", "literature_references.tsv")
        tsv_lines = ["标题\t年份\t作者\tDOI\t期刊\t被引\t语种"]
        for p in papers:
            tsv_lines.append(
                f"{p['title']}\t{p['year']}\t{p['authors']}\t{p['doi']}\t"
                f"{p['venue']}\t{p['citations']}\t{p['lang']}"
            )
        with open(ref_tsv, "w", encoding="utf-8") as f:
            f.write("\n".join(tsv_lines) + "\n")

        # 2) 注入真实结果运行 Crew（只做分析，不生成文献表）
        print("[2/3] 正在运行 CrewAI 三角色分析（通常 2-5 分钟，请耐心等待）...")
        crew = build_literature_crew(args.topic, llm, tools, search_results=raw,
                                     memory=mem_block)
        crew.kickoff()

        # 3) 后处理：剥离可能伪造的 TSV，追加真实 TSV
        print("[3/3] 正在生成报告...")
        report_path = os.path.join("reports", "literature_report.md")
        # 可溯源护栏（引用级）：剔除撰稿员凭参数记忆编造的 DOI。
        # 实测旧报告 51 个引用里 50 个不在检索结果中，故 prompt 约束不够，必须代码兜底。
        sanitize_report_citations(
            report_path, allowed_dois=[p["doi"] for p in papers if p.get("doi")]
        )
        from src.main import _LAST_TRACE
        trace_md = "\n".join(_LAST_TRACE) if _LAST_TRACE else "（无溯源记录）"
        tsv_block = (
            "## 检索过程溯源\n\n"
            "本节记录程序如何理解你的检索主题、构造了哪些检索式、各级降级结果——"
            "**若理解有误，可据此判断并换词重跑**。\n\n"
            f"{trace_md}\n\n"
            "## 文献表（真实检索结果，系统按代码生成，绝不编造）\n\n"
            f"来源：{source}｜中文 {n_zh} 篇 + 英文 {n_en} 篇\n\n```\n"
            + "\n".join(tsv_lines)
            + "\n```"
        )
        append_grounded_refs(report_path, tsv_block)
        print(
            f"\n===== 完成：报告={report_path}，真实文献 {len(papers)} 篇"
            f"（中 {n_zh} / 英 {n_en}，来源：{source}），TSV={ref_tsv} =====\n"
        )

    else:  # market
        # 【市场调研】与文献检索的差异：
        #   检索词 → 多维拆解（产品/厂商/技术/案例，中英文分列）
        #   质量判据 → 来源可信度分级（A/B/C，D级丢弃），无期刊白名单
        print("[1/3] 正在拆解调研主题为多维检索式...")
        mq = build_market_queries(args.topic, max_queries=5)
        queries = mq["queries"]
        trace = [f"- 题型判定：{mq['题型']}（检索式来源：{mq['source']}）"]
        for q in queries:
            flag = " ⚠需核实产品名" if q.get("需核实") else ""
            trace.append(f"  - [{DIMENSIONS.get(q['维度'], q['维度'])}] `{q['查询']}`{flag}")
        if not queries:
            print("⚠️ 未能生成可用检索式，请调整主题表述")

        print(f"[2/3] 正在执行 {len(queries)} 条检索式并评估来源可信度...")
        records = []
        for q in queries:
            raw_i = search_web(q["查询"], 6)
            for it in parse_web_results(raw_i):
                tier = classify_source(it["url"], it["title"], it["snippet"])
                if tier == "D":
                    continue  # 内容农场直接丢弃
                records.append({
                    "title": it["title"],
                    "url": it["url"],
                    "snippet": it["snippet"],
                    "tier": tier,
                    "query_hit": f"{DIMENSIONS.get(q['维度'], q['维度'])}: {q['查询']}",
                })
            time.sleep(0.5)  # 降低被限流概率
        records = dedupe_records(records)

        ref_tsv = os.path.join("reports", "market_references.tsv")
        table_rows = build_market_table(records)
        tsv_lines = ["\t".join(r) for r in table_rows]
        with open(ref_tsv, "w", encoding="utf-8") as f:
            f.write("\n".join(tsv_lines) + "\n")

        tier_stat = {}
        for r in records:
            tier_stat[r["tier"]] = tier_stat.get(r["tier"], 0) + 1
        trace.append(
            f"  - 来源分级：" + "；".join(f"{t}级 {n} 条" for t, n in sorted(tier_stat.items()))
            + f"（D级内容农场已丢弃）"
        )

        # 注入给 Crew 的上下文：含可信度标记，提示分析员区分对待
        ctx_lines = [
            "# 真实检索结果（来源含可信度分级，严禁编造产品名/链接）",
            "",
            "| 产品/机构候选 | 来源标题 | 可信度 | 功能线索 | 命中检索式 |",
            "|---|---|---|---|---|",
        ]
        for row in table_rows[1:]:
            ctx_lines.append("| " + " | ".join(row[:1] + row[1:2] + row[3:]) + " |")
        ctx_lines.append("")
        ctx_lines.append(
            "【重要】可信度 A=官方/学术，B=主流媒体，C=社区参考。"
            "撰写时须区分：只有 A/B 级可作为结论依据，C 级需注明「社区反馈，待核实」。"
            "产品名均为**从检索结果抽取的候选**，未经核实，不得断言。"
        )
        market_ctx = "\n".join(ctx_lines)

        print("[3/3] 正在运行 CrewAI 三角色分析...")
        crew = build_market_crew(args.topic, llm, tools, search_results=market_ctx,
                                 memory=mem_block)
        crew.kickoff()

        # 可溯源护栏：剥离撰稿员可能凭记忆编造的链接（不在真实检索结果内）
        sanitize_report_urls(
            os.path.join("reports", "market_report.md"),
            allowed_urls=[r["url"] for r in records],
        )

        report_path = os.path.join("reports", "market_report.md")
        trace_md = "\n".join(trace)
        tsv_block = (
            "## 检索过程溯源\n\n"
            "本节记录调研主题如何被拆解为多维检索式、各来源的可信度分布——"
            "**若拆解有误，可据此判断并换词重跑**。\n\n"
            f"{trace_md}\n\n"
            "## 产品/机构对比表（由真实检索结果经代码生成，绝不编造）\n\n"
            "列：产品/机构｜来源标题｜URL｜可信度｜功能线索｜命中检索式\n\n"
            "```\n" + "\n".join(tsv_lines) + "\n```\n\n"
            "> 产品/机构名为**从标题与 URL 抽取的候选**，非经核实；\n"
            "> 可信度 C 的来源属社区反馈，仅供参考。"
        )
        append_grounded_refs(report_path, tsv_block)
        print(
            f"\n===== 完成：报告={report_path}，真实来源 {len(records)} 条"
            f"（A{tier_stat.get('A',0)}/B{tier_stat.get('B',0)}/C{tier_stat.get('C',0)}），"
            f"TSV={ref_tsv} =====\n"
        )


if __name__ == "__main__":
    main()
