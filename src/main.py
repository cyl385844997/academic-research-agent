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
from src.tools.openalex_tool import openalex_search, search_openalex
from src.tools.crossref_tool import crossref_search, search_crossref
from src.tools.cnki_tool import cnki_search, search_cnki, build_advanced_query
from src.tools.query_translator import translate_to_english_queries
from src.tools.core_journals import CORE_JOURNALS, CORE_JOURNAL_GROUPS


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


def assess_quality(papers, topic=""):
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

        # 英文文献：只做主题相关性过滤
        if topic_en and not (topic_en & tokens(p.get("title", ""))[1]):
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


def _chinese_portion(topic: str) -> str:
    """从混合检索词中提取中文部分（知网只对中文查询有意义）。

    「城镇污水处理 side-stream EBPR」→ 「城镇污水处理」
    无中文时返回空字符串，表示不走知网。
    """
    cn = re.findall(r"[\u4e00-\u9fff]+", topic or "")
    return " ".join(cn).strip()


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
    collected = []
    used_sources = []
    errors = []

    # 【中文主源】知网 —— 中文核心刊的唯一可靠来源。
    # 用专业检索式广召回，再由 assess_quality 按北大核心白名单过滤；
    # 不做 LY 期刊限定——单期刊召回过少，反而漏掉其它核心刊成果。
    zh_query = _chinese_portion(topic)
    if zh_query:
        raw_cnki = search_cnki(build_advanced_query(zh_query), limit)
        papers_cnki = [p for p in parse_ss_papers(raw_cnki) if p["lang"] == "zh"]
        if papers_cnki:
            collected.extend(papers_cnki)
            used_sources.append("知网")
        else:
            errors.append(f"- **知网**：{(raw_cnki or '').strip()[:160]}")

    # 【英文源】英文检索式来源：
    #   - 原词含英文 → 直接使用；
    #   - 纯中文 → LLM 转成国际期刊通用术语（避免中文词污染英文库）。
    en_queries = _english_queries(topic)
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
    kept, warn = assess_quality(uniq, topic)

    zh = [p for p in kept if p["lang"] == "zh"]
    en = [p for p in kept if p["lang"] != "zh"]

    # 中文至少保留 1/3（最低 2 篇），其余留给英文
    balanced = []
    if zh and en:
        take_zh = min(len(zh), max(limit // 3, 2))  # 中文至少 1/3，下限 2 篇
        take_en = min(len(en), limit - take_zh)
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
    tools = [literature_search, openalex_search, crossref_search, web_search]
    os.makedirs("reports", exist_ok=True)

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
        crew = build_literature_crew(args.topic, llm, tools, search_results=raw)
        crew.kickoff()

        # 3) 后处理：剥离可能伪造的 TSV，追加真实 TSV
        print("[3/3] 正在生成报告...")
        report_path = os.path.join("reports", "literature_report.md")
        tsv_block = (
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
