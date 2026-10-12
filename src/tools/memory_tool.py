"""记忆的 CrewAI 工具包装：让 Agent 在运行过程中按需读写记忆。

给 Crew 用的读写与 CLI 不同，两点收紧：
1. **写入只进待审队列，不直接落库**——模型判断的重要��很可能不准，
   自动落库会污染后续所有回答；进 pending.md 等人工确认，与本项目
   「可溯源铁律」同源（不让模型直接产出不可回溯的结果）。
2. **删除需显式 --confirm**——防止模型误删用户手写的记忆。
"""
from __future__ import annotations

try:
    from crewai.tools import tool as _crew_tool
except Exception:  # noqa: BLE001
    _crew_tool = None

from src.tools import memory_store as ms
from src.tools.memory_store import ENTRIES_DIR, MEM_DIR


def memory_recall(topic: str, limit: int = 6) -> str:
    """检索长期记忆：按主题召回相关的操作者偏好、领域约定与在办事项。

    遇到不明确的领域口径（同一术语多种英文说法、中文术语歧义）时先查这里，
    避免用错映射。返回结果为空说明该议题尚无记忆，按通用知识处理并如实标注。
    """
    items = ms.recall(topic, limit=limit)
    if not items:
        return "记忆库中无匹配条目。"
    return "\n".join(f"- {e.one_line()}：{e.body.strip()[:200]}" for e in items)


def memory_note(kind: str, title: str, body: str, tags: str = "",
                topic_key: str = "") -> str:
    """记录一条值得长期记住的信息（偏好 / 领域约定 / 在办事项）。

    写入的是**待审提案**，需操作者确认后才生效（见 memory/pending.md）。
    kind 取值：user=操作者偏好、domain=领域约定、project=在办事项。
    不要把一次性任务请求、模型自己的推断、或任何密钥记进来。
    """
    proposals = [{
        "kind": kind if kind in ms.VALID_KINDS else "domain",
        "title": title,
        "topic_key": topic_key or title,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "body": body,
        "reason": "运行中由 Agent 记录，待人工确认",
        "source": "Agent 运行记录",
    }]
    n = ms.add_pending(proposals, source_desc="Agent 运行中记录")
    return f"已记入待审队列（{n} 条）。需操作者在 {MEM_DIR / 'pending.md'} 确认后才生效。"


def memory_list(kind: str = "") -> str:
    """列出记忆库当前生效的全部条目（便于 Agent 了解用户的长期要求）。"""
    items = ms.list_entries(kind=kind or None)
    if not items:
        return "记忆库为空。"
    lines = []
    for e in items:
        lines.append(f"[{e.id}|{e.kind}] {e.title}\n  {e.body.strip()[:160]}")
    return "\n".join(lines)


if _crew_tool is not None:
    memory_recall_tool = _crew_tool("长期记忆检索")(memory_recall)
    memory_note_tool = _crew_tool("记录长期记忆")(memory_note)
    memory_list_tool = _crew_tool("列出长期记忆")(memory_list)
else:  # pragma: no cover - 无 crewai 环境
    memory_recall_tool = memory_note_tool = memory_list_tool = None


__all__ = [
    "memory_recall", "memory_note", "memory_list",
    "memory_recall_tool", "memory_note_tool", "memory_list_tool",
    "ENTRIES_DIR",
]
