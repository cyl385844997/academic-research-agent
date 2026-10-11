"""关键词理解与生成：从中文主题推出中英文检索式。

设计思路（用户确认的三层架构）
------------------------------
第1 层 **领域词典**（domain_lexicon）：人工核定的中英文等价映射，零幻觉，优先。
第 2 层 **概念解析**（本模块）：词典未覆盖时，用 LLM 理解主题并输出**结构化拆解**：
        对象 / 条件 / 任务  →  分别生成中英文检索词，再按语义角色组装检索式。
第 3 层 **规则回退**（cnki_tool.build_advanced_query）：前两层失效时兜底。

为什么不直接翻译
----------------
中文工程术语与英文文献术语不是一一对应，字面直译会失真：
    高水位    → 字面 high water level，英文标准概念却是 infiltration/inflow (I/I)
    雨污混错接 → 字面 rain-sewage mixing，英文用 cross-connection
    提标改造  → 字面 standard-raising，英文用 upgrading / retrofitting
所以必须"先理解、再按概念找对应表述"，而非逐字翻译。

**可溯源约束**：本模块只生成「检索词」，绝不生成「文献记录」。
文献表一律由代码从真实学术库抓取、解析、写出（见 AGENTS.md 可溯源铁律）。
"""
import json
import os
import re

from src.tools.domain_lexicon import LEXICON, lookup

# ============ 语义角色词表（用于词典命中时判定对象/条件/任务） ============

# 研究对象：检索的主体名词，知网中作为主条件
ROLE_OBJECT = (
    "排水管网", "排水管道", "污水管网", "给水管网", "管网", "管道",
    "污水处理厂", "污水厂", "侧流生物除磷", "生物除磷", "EBPR",
    "活性污泥", "侧流", "再生水", "污泥",
    "总氮", "TN", "氨氮", "总磷", "进水", "出水",
    "风机", "水泵", "泵系统",
)

# 任务：方法或目标，知网/英文中作为动作词
ROLE_TASK = (
    "诊断", "检测", "评估", "监测", "排查", "修复", "鉴定",
    "管网诊断", "缺陷检测", "非开挖检测", "管道检测", "深度处理", "提标改造",
    "脱氮", "除磷", "硝化", "反硝化", "诊断",
)


# ============ 第 1 层：领域词典 ============


def analyze_with_lexicon(topic: str):
    """用词典解析中文主题，返回结构化拆解与检索式；未命中返回 None。

    拆解按语义角色：
        对象（研究主体）→ 知网主条件、英文核心名词
        条件（工况场景）→ 知网修饰词、英文限定
        任务（方法目标）→ 知网修饰词、英文动作词
    """
    hits = lookup(topic)
    if not hits:
        return None

    obj_cn, cond_cn, task_cn = [], [], []
    en_terms = []
    for cn in hits:
        entry = LEXICON.get(cn, {})
        en_terms.extend(entry.get("en", []))
        if cn in ROLE_OBJECT:
            obj_cn.append(cn)
        elif cn in ROLE_TASK:
            task_cn.append(cn)
        else:
            cond_cn.append(cn)

    if not (obj_cn or cond_cn or task_cn):
        return None

    # 知网检索式：SU='对象' * ('条件' + '任务')
    # 无对象时退化为「首选命中词」，保证总能生成可用检索式
    if obj_cn:
        main = obj_cn[0]
        mods = [w for w in (cond_cn + task_cn) if w != main][:3]
        if mods:
            cnki_query = f"SU='{main}' * (" + " + ".join(f"'{m}'" for m in mods) + ")"
        else:
            cnki_query = f"SU='{main}' or TKA='{main}'"
    else:
        cnki_query = f"SU='{hits[0]}' or TKA='{hits[0]}'"

    return {
        "concept": {"对象": obj_cn[:3], "条件": cond_cn[:3], "任务": task_cn[:3]},
        "matched_terms": hits,
        "cnki_query": cnki_query,
        "english_queries": _build_english_by_role(obj_cn, cond_cn, task_cn),
        "source": "领域词典",
        "explanation": f"命中领域词典：{'、'.join(hits)}（中英文按词典等价映射，非字面直译）",
    }


def _build_english_by_role(obj_cn, cond_cn, task_cn, max_queries: int = 2) -> list:
    """按语义角色分配英文检索词，而非单纯按词长。

    关键：中文主题里**条件词的英文等价往往比对象词更关键**——
    「高水位排水管网诊断」的对象是排水管网（英文 sewer network，检索泛），
    但条件"高水位"对应 infiltration/inflow，才是拉开文献差异的关键。
    故：条件词与对象词的英文各取一条，任务词并入。
    """
    def first_en(cn_list):
        for cn in cn_list:
            terms = LEXICON.get(cn, {}).get("en", [])
            if terms:
                return terms[0]
        return None

    queries = []
    # 1) 条件的英文等价（若条件词在词典中有等价概念，优先取）
    for cn in cond_cn[:2]:
        t = first_en([cn])
        if t:
            queries.append(t)
            break
    # 2) 对象的英文等价
    t = first_en(obj_cn[:2])
    if t:
        queries.append(t)
    # 3) 任务的英文等价（补足）
    if len(queries) < max_queries:
        t = first_en(task_cn[:1])
        if t and t not in queries:
            queries.append(t)

    # 去重保序
    seen, out = set(), []
    for q in queries:
        k = q.lower()
        if k not in seen:
            seen.add(k)
            out.append(q)
    return out[:max_queries]


# ============ 第 2 层：LLM 概念解析 ============

_PARSE_PROMPT = """你是环境工程/污水处理领域的文献检索专家。请先**理解**下面这个中文研究主题，再输出结构化拆解。

【领域常识提醒】中文工程术语与英文文献术语往往不对应，必须用英文文献的**标准术语**：
- 高水位（管网）→ infiltration and inflow (I/I)、high groundwater（中文多指地下水/河水入渗）
- 雨污混错接 → cross-connection / illicit connection / misconnection
- 提标改造 → upgrading / retrofitting
- 雨季溢流 → combined sewer overflow (CSO)
- 吨水电耗 → specific energy consumption (SEC)

【要求】
1. 先拆解语义角色：研究对象（对象）、工况场景（条件）、方法目标（任务）
2. 对象通常是最核心的名词（如"排水管网""侧流生物除磷"）
3. 只用国际期刊论文标题里**真实出现过**的词，不要生造复合词与生僻词
4. 知网检索式语法：SU=主题 TKA=篇关摘；`*`=与 `+`=或
   正确范式：`SU='对象' * ('条件' + '任务')`（对象必须出现，条件或任务命中其一即可）
5. 英文检索式给 2 条，覆盖不同表述角度

严格按以下 JSON 输出，不要任何解释文字：
{{"对象": ["..."], "条件": ["..."], "任务": ["..."],
  "概念解释": "一句话说明该主题在研究中实际指什么",
  "知网检索式": "SU='...' * ('...' + '...')",
  "英文检索式": ["...", "..."]}}

中文主题：{topic}"""


def _get_llm():
    """构造 LLM（Agnes 等兼容端点直连用原始模型名，不加 openai/ 前缀）。"""
    from langchain_openai import ChatOpenAI

    kwargs = dict(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        api_key=os.getenv("OPENAI_API_KEY", ""),
        temperature=0.1,
    )
    base = os.getenv("OPENAI_BASE_URL")
    if base:
        kwargs["base_url"] = base
    return ChatOpenAI(**kwargs)


def _extract_json(text: str):
    """从 LLM 输出中提取 JSON（容忍代码块包裹与前后废话）。"""
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


# 语法校验：知网检索式必须形如 SU='x' * ('y' + 'z') / SU='x' or TKA='x'
_CNKI_PATTERN = re.compile(
    r"^\s*(SU|TKA)\s*=\s*'[^']+'\s*"
    r"(?:\*\s*\(\s*'[^']+'(?:\s*[+]\s*'[^']+')*\s*\)"
    r"|or\s+TKA\s*=\s*'[^']+')?\s*$",
    re.IGNORECASE,
)

# 幻觉词闸门（实测"leisure level"把检索带偏到传染病学文献）
_HALLUCINATION_MARKERS = ("leisure", "sanitarium", "recreational", " fun ")


def validate_cnki_query(q: str) -> bool:
    """校验知网检索式语法；不合法返回 False（调用方应回退）。"""
    return bool(q and _CNKI_PATTERN.match(q.strip()))


def validate_english_queries(queries) -> list:
    """校验清洗英文检索式：剔除幻觉词、含中文项、过短项。"""
    out = []
    for q in queries or []:
        s = (q or "").strip()
        if not s or len(s) < 8:
            continue
        if any(m in s.lower() for m in _HALLUCINATION_MARKERS):
            continue
        if re.search(r"[\u4e00-\u9fff]", s):
            continue
        if len(re.findall(r"[A-Za-z]{3,}", s)) < 2:
            continue
        out.append(s)
    return out


def analyze_with_llm(topic: str):
    """用 LLM 理解并拆解中文主题；失败返回 None。"""
    if not (topic or "").strip():
        return None
    try:
        llm = _get_llm()
        resp = llm.invoke(_PARSE_PROMPT.format(topic=topic))
        data = _extract_json(resp.content or "")
    except Exception:  # noqa: BLE001
        return None
    if not data:
        return None

    cnki_query = (data.get("知网检索式") or "").strip()
    if not validate_cnki_query(cnki_query):
        cnki_query = ""
    return {
        "concept": {
            "对象": data.get("对象") or [],
            "条件": data.get("条件") or [],
            "任务": data.get("任务") or [],
        },
        "explanation": (data.get("概念解释") or "").strip(),
        "cnki_query": cnki_query,
        "english_queries": validate_english_queries(data.get("英文检索式")),
        "source": "LLM 概念解析",
    }


# ============ 统一入口 ============


def understand_topic(topic: str):
    """理解检索主题，返回结构化拆解与中英文检索式。

    依次尝试：领域词典 → LLM 概念解析；词典部分命中时即使 LLM 不可用也返回词典结果。

    Returns:
        {
          "concept": {"对象": [...], "条件": [...], "任务": [...]},
          "cnki_query": "SU='...' * ('...' + '...')",
          "english_queries": ["...", "..."],
          "source": "领域词典" | "LLM 概念解析",
          "explanation": "...",
        }；完全失败返回 None（调用方走规则回退）
    """
    if not (topic or "").strip():
        return None

    # 第 1 层：词典
    lex = analyze_with_lexicon(topic)
    if lex and lex["cnki_query"] and lex["english_queries"]:
        return lex

    # 第 2 层：LLM 概念解析（词典未覆盖或信息不全时）
    llm_res = analyze_with_llm(topic)
    if llm_res and llm_res["cnki_query"] and llm_res["english_queries"]:
        return llm_res

    # 降级：至少返回词典的中文部分
    return lex


# 向后兼容旧接口
def translate_to_english_queries(topic: str, max_queries: int = 3) -> list:
    """兼容旧接口：返回英文检索式列表。"""
    res = understand_topic(topic)
    return (res or {}).get("english_queries", [])[:max_queries]