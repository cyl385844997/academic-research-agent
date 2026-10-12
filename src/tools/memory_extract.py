"""记忆自动整理：从会话/运行记录中提炼「值得长期记住」的信息。

为什么要 LLM 参与
----------------
"什么值得记住"是语义判断：用户随口一句"我习惯用 TSV 不要 xlsx"是长期偏好，
而"帮我算个数"是一次性请求，不该进记忆。规则写不出来，交给 LLM 判。

安全边界（重要）
--------------
LLM 在本模块里**只做候选提议，绝不直接写库**。理由与「可溯源铁律」同源：
模型会误判重要��、会编造偏好，一旦自动落库，错误记忆会持续污染后续所有回答，
且用户难以察觉。因此：

    提炼 ──→ 去重/冲突检测 ──→ 无冲突才自动生效
                      └──────→ 有重复/冲突则写入 pending.md 等人工裁决

`promote_safe(proposals)` 只自动采纳「全新且无冲突」的条目，其余一律进待审。
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from src.tools import memory_store as ms

# ============ 提炼提示词 ============

_EXTRACT_PROMPT = """你是科研工作记忆的管理员。请从下面的工作对话/运行记录中，
提炼出**值得长期记住**的信息，用于让后续回答更贴合这位使用者。

【什么该记】
1. 操作者偏好：交付格式偏好、习惯、明确要求（如"给 TSV 不要 xlsx"、"中文回答"）
2. 领域约定：术语口径、判据标准、检索习惯（如"高水位≠入渗，是满管流"）
3. 在办事项与约束：项目、经费、截止时间、必须遵守的红线
4. 被明确纠正过的错误：以及纠正后的正确口径

【什么不该记】
- 一次性的具体任务请求（"帮我算这个数""查一下 X""跑一次 Y"）——那是任务，不是记忆
- **一次性的故障与插曲**（"我没看到结果""预览没渲染""又报错了"）——
  这类属于当次排障，记住会变成无意义的长期约束
- 模型自己推断出的、对话里没人确认过的结论
- 任何密钥、token、密码、身份证号等凭证

【判定门槛：宁缺毋滥】
只有当对话里出现了**明确的、面向将来的约束或偏好**（"以后""都要""必须""不要"
"记住""一律"这类措辞，且指向长期行为）才提炼。
如果这句话只描述当次发生了什么，就不要提炼。
不确定要不要记 → 不记。6 条上限是硬约束，宁可只提炼 1 条确实该记的。

【严格要求】
1. 每条必须是**可执行的口径**，不是话题描述。
   差：「讨论了高水位」；好：「高水位=管网运行水位偏高(满管流/溢流风险)，英文用 full pipe flow，不用 infiltration and inflow」
2. topic_key 填判断该条是否冲突的「议题名」，同一议题的不同口径必须用**相同** topic_key，
   这样程序才能检测出冲突并交人工裁决。
3. `always` 只在「**每次交付都必须遵守**」时才填 true（如交付格式、解释风格、脱敏要求）。
   仅适用于**特定主题**的口径必须填 false（如某术语映射、某个环境的工具链细节）——
   否则会把无关内容硬塞进每次的报告里。**判断标准：这条换个主题还成立吗？**
4. 只输出 JSON，不要解释。
5. 最多 6 条，宁缺毋滥。

输出格式：
{{"memories": [
  {{"kind": "user|domain|project",
    "title": "一句话标题",
    "topic_key": "议题名",
    "tags": ["标签1"],
    "always": false,
    "body": "可执行口径，多行用 \\n",
    "reason": "为什么要记这条（引用对话中的依据）"}}
]}}

kind 的判定标准（不要凭标题里的字面词猜）：
- user：**这位操作者本人的要求或偏好**。判据是「谁提出的」——
  「用户说以后文档要脱敏」「用户要求给 TSV」→ user（哪怕内容像规范）。
- domain：**领域内的客观口径**，任何同类研究者都会这么用，与具体是谁无关。
  判据是「换个操作者也成立吗」——「高水位=满管流，用 full pipe flow」→ domain。
- project：具体在办的事项、进度、约束（本次要交付什么、截止时间）。

待提炼内容：
{content}"""


def _get_llm():
    """构造 LLM（与项目其它模块一致：兼容端点直连，用裸模型名）。"""
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
                    return json.loads(t[start:i + 1])
                except Exception:  # noqa: BLE001
                    return None
    return None


# 凭证类内容一律不落库（纵深防御：即使 prompt 漏了也拦得住）
_LAST_ERR = ""
_SECRET_PATTERNS = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{10,}|sk-[A-Za-z0-9]{10,}|"
    r"AKIA[0-9A-Z]{10,}|BEGIN\s+.*PRIVATE\s+KEY|"
    r"api[_-]?key\s*[:=]\s*\S+|password\s*[:=]\s*\S+|token\s*[:=]\s*\S{8,})",
    re.IGNORECASE,
)


def _has_secret(text: str) -> bool:
    return bool(_SECRET_PATTERNS.search(text or ""))


def _last_error() -> None:
    """把最近一次静默失败的详情贴出来，便于区分「确实没有」与「LLM 挂了」。"""
    if _LAST_ERR:
        print(f"  [记忆提炼] LLM 调用失败：{_LAST_ERR[:160]}")


def extract_candidates(content: str, source_desc: str = "") -> list:
    """用 LLM 提炼候选记忆（含语义裁决标注），失败时如实返回空列表。"""
    global _LAST_ERR
    _LAST_ERR = ""
    content = (content or "").strip()
    if not content:
        return []
    if _has_secret(content):
        # 内容含凭证：拒绝整体提炼，避免密钥被写进记忆库
        _LAST_ERR = "内容含凭证特征，已跳过提炼（安全策略）"
        return []

    try:
        llm = _get_llm()
        resp = llm.invoke(_EXTRACT_PROMPT.format(content=content[:8000]))
        data = _extract_json(resp.content or "")
    except Exception as exc:  # noqa: BLE001
        _LAST_ERR = f"{type(exc).__name__}: {exc}"
        return []
    if not data:
        _LAST_ERR = "LLM 回复无法解析为 JSON"
        return []

    out = []
    for it in (data.get("memories") or [])[:6]:
        if not isinstance(it, dict):
            continue
        body = (it.get("body") or "").strip()
        title = (it.get("title") or "").strip()
        if not body or not title:
            continue
        if _has_secret(body) or _has_secret(title):
            continue  # 命中凭证特征，丢弃该条
        out.append({
            "kind": it.get("kind") if it.get("kind") in ms.VALID_KINDS else "domain",
            "title": title,
            "topic_key": (it.get("topic_key") or title).strip(),
            "tags": [t for t in (it.get("tags") or []) if isinstance(t, str)][:6],
            "body": body,
            "reason": (it.get("reason") or "").strip(),
            "source": source_desc or "自动提炼",
            # always 由模型判断「换个主题是否还成立」，不按 kind 一刀切——
            # 否则「某环境的工具链细节」这类主题性事实会污染每次输出。
            "always": bool(it.get("always", False)),
        })
    if not out:
        _LAST_ERR = "LLM 判定这些内容不值得长期记忆（多为一次性任务或插曲）"
    return out


def annotate(candidates: list) -> list:
    """为每条候选标注与既有记忆的关系（初筛，纯词面）。

    这里只做**高置信度的明显重复**初筛（词面高度相似）。
    注意：词面相似度**无法区分「改述」与「矛盾」**（实测矛盾对得分反而更高），
    因此只把 SIM_DUPLICATE 以上的判为疑似重复，低于此的一律交给 LLM 语义裁决。
    """
    for c in candidates:
        probe = ms.MemoryEntry(
            id="", kind=c["kind"], title=c["title"],
            tags=c["tags"], topic_key=c["topic_key"], body=c["body"],
        )
        similar = ms.find_similar(probe, threshold=ms.SIM_DUPLICATE)
        # 同议题的全部既有条目都要送 LLM 裁决——不能用相似度阈值提前过滤，
        # 否则改述型重复（实测相似度仅 0.39）会被漏判、重复入库。
        same_topic = ms.find_same_topic(probe)
        c["similarity"] = (
            f"{similar[0][1]:.2f} vs {similar[0][0].id}" if similar else "无"
        )
        c["_dup_of"] = similar[0][0].id if similar else None
        c["_same_topic"] = [e.id for e in same_topic]
        c["conflict_with"] = []
    return candidates


# ============ 语义裁决：矛盾 vs 改述 ============

_JUDGE_PROMPT = """你在判断两条「长期记忆」之间的关系。

记忆 A：{a}

记忆 B：{b}

请判断 B 相对 A 属于哪种关系：
- unrelated：A 与 B 讲的根本不是一件事（议题不同），无需合并也不构成冲突
- same：讲的是同一件事，只是换了措辞或更详细 → 应合并，不要新增
- supplement：B 是对 A 的补充（新增了独立信息），两者不矛盾 → 可并存
- conflict：B 与 A 口径相悖（同一议题给出不同结论）→ 必须人工裁决

判断依据：只看两条记忆的内容是否真的矛盾，不要因为措辞不同就判 conflict。
例：「高水位指满管流」与「高水位指地下水入渗」是 conflict；
    「解释概念要配案例」与「讲解时不要照教科书，要举例说明」是 same。

只输出 JSON：{{"relation": "unrelated|same|supplement|conflict", "why": "一句话理由"}}"""


def _judge(a: str, b: str) -> tuple[str, str]:
    """用 LLM 判定两条记忆的关系。失败时返回 ("unknown", "")——由上层转人工。"""
    try:
        llm = _get_llm()
        resp = llm.invoke(_JUDGE_PROMPT.format(a=a[:1500], b=b[:1500]))
        data = _extract_json(resp.content or "")
        if data and data.get("relation") in ("same", "supplement", "conflict"):
            return data["relation"], str(data.get("why", ""))[:200]
    except Exception:  # noqa: BLE001
        pass
    return "unknown", ""


def adjudicate(candidates: list, use_llm: bool = True) -> list:
    """对同议题的候选与既有记忆做语义裁决，标注最终归类。

    裁决结果写入候选的 `_relation` 字段：
      merge     —— 与既有记忆是同一件事，应人工合并（不新增）
      supplement—— 可与既有并存（补充了独立信息）
      conflict  —— 口径相悖，必须人工裁决（冲突熔断）
      new       —— 全新条目，无既有相关项
    """
    annotate(candidates)
    for c in candidates:
        same_topic = c.get("_same_topic") or []
        if not same_topic:
            c["_relation"] = "new" if not c.get("_dup_of") else "merge"
            continue
        target_id = same_topic[0]
        target = ms.get_entry(target_id)
        if not target:
            c["_relation"] = "new"
            continue
        rel, why = _judge(target.searchable_text(), c["title"] + " " + c["body"]) \
            if use_llm else ("unknown", "")
        c["_judge_why"] = why
        if rel == "unrelated":
            # 该议题候选其实不相关 → 当作全新条目，不做合并/裁决
            c["_relation"] = "new"
            c["conflict_with"] = []
            c["_dup_of"] = None
        else:
            c["_relation"] = rel
            c["conflict_with"] = [target_id] if rel == "conflict" else []
            if rel in ("same", "unknown"):
                c["_dup_of"] = target_id
    return candidates


def promote_safe(candidates: list, auto_write: bool = False, use_llm: bool = True) -> dict:
    """把候选记忆分流：安全的入库，其余进待审队列。

    分流规则（保守优先——误自动改记忆的成本高于多看一条待审）：
      - LLM 判为 same / unknown（判不准）→ 不新增，建议合并 → 待审
      - LLM 判为 conflict                → 冲突熔断，交人工裁决 → 待审
      - supplement                       → 补充信息，可与既有并存 → 入库
      - new（无既有相关项）              → 入库

    Args:
        auto_write: True 才真正写库。默认 False = 只演练并返回预览，
                     由上层确认后调用，避免误改记忆。
    """
    candidates = adjudicate(candidates, use_llm=use_llm)
    accepted, pending, rejected = [], [], []

    for c in candidates:
        rel = c.get("_relation", "new")
        if rel == "conflict":
            c["reason"] = (
                c.get("reason", "") +
                f"；与 {','.join(c.get('conflict_with', []))} 口径冲突（{c.get('_judge_why','')}），需人工裁决"
            )[:300]
            pending.append(c)
        elif rel in ("same", "unknown"):
            dup = c.get("_dup_of") or "既有条目"
            c["reason"] = (
                c.get("reason", "") +
                f"；与 {dup} 实为同一件事（{c.get('_judge_why','') or '程序判不准'}），建议合并而非新增"
            )[:300]
            pending.append(c)
        else:  # new / supplement
            accepted.append(c)

    if auto_write:
        for c in accepted:
            e = ms.MemoryEntry(
                kind=c["kind"], title=c["title"], tags=c["tags"],
                topic_key=c["topic_key"], body=c["body"],
                source=c.get("source", "自动提炼"), always=c.get("always", False),
                status="active",
            )
            ms.save_entry(e, archive_reason="auto-extract")
        if pending:
            ms.add_pending(pending, source_desc=candidates[0].get("source", "") if candidates else "")

    return {"accepted": accepted, "pending": pending, "rejected": rejected}


def commit(candidates: list) -> dict:
    """确认后真正落库（promote_safe(auto_write=True) 的显式版本）。"""
    return promote_safe(candidates, auto_write=True)


def refresh_from_daily(days: int = 3) -> list:
    """读取最近若干天的会话日志作为提炼素材。"""
    chunks = []
    for p in ms.list_daily(limit=days):
        try:
            chunks.append(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
    return chunks
