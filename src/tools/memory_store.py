"""记忆存储层：人类可编辑的分文件记忆库 + 原子写入 + 去重/冲突检测。

设计取舍（对齐 AGENTS.md 的 local-first 与「可溯源铁律」）
--------------------------------------------------------
1. **一条记忆 = 一个 Markdown 文件**（YAML frontmatter + 正文），放在 `memory/entries/`。
   不用数据库、不用二进制：用户可以用任何编辑器直接打开改，也可以删文件。
   「操作者可以随时编辑记忆」是硬需求，可见性优先于紧凑性。
2. **可溯源**：每条记忆必带 `source`（来自哪次对话 / 哪次运行）与 `created`，
   与本项目对文献「必须能回溯原始来源」的要求一致。
3. **不静默覆盖**：更新已有记忆时旧版转入 `memory/archive/`，不原地抹除。
4. **冲突熔断**：新记忆与既有记忆 `topic_key` 相同但结论相悖 → 标记 conflict 交人工裁决，
   程序不自动择一（对齐「同一事实多处置入不一致时立即停止修改」纪律）。
5. **local-first**：全部落本地磁盘，`.gitignore` 排除，不上传任何服务。

文件格式（可直接手改）::

    ---
    id: M-0001
    kind: domain            # domain=领域知识 / user=操作者偏好 / project=在办事项
    title: 高水位的英文语义需拆成两类
    tags: [排水管网, 高水位]
    topic_key: 高水位        # 同一 topic_key 的两条记忆若结论相悖 → 冲突
    status: active          # active / superseded / rejected / draft
    always: false           # true = 每次都注入，不做相关性筛选
    source: 2026-10-12 对话（用户纠正）
    created: 2026-10-12T09:00:00
    updated: 2026-10-12T09:00:00
    ---

    正文（Markdown）。第一句通常是可执行的结论，便于召回时一眼判断相关性。
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import yaml

# 项目根目录：src/tools/memory_store.py -> 上溯三级
ROOT = Path(__file__).resolve().parents[2]

MEM_DIR = ROOT / "memory"
ENTRIES_DIR = MEM_DIR / "entries"
DAILY_DIR = MEM_DIR / "daily"
ARCHIVE_DIR = MEM_DIR / "archive"
PENDING_FILE = MEM_DIR / "pending.md"

VALID_KINDS = ("domain", "user", "project")
VALID_STATUS = ("active", "superseded", "rejected", "draft")

# 相似度阈值（difflib ratio）
SIM_DUPLICATE = 0.85   # ≥ 此值视为重复，自动合并
SIM_RELATED = 0.55      # ≥ 此值视为相关，列入待审并建议合并

_KIND_PREFIX = {"domain": "M", "user": "U", "project": "P"}


# ============ 基础设施 ============

def _ensure_dirs() -> None:
    for d in (MEM_DIR, ENTRIES_DIR, DAILY_DIR, ARCHIVE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _atomic_write(path: Path, text: str) -> None:
    """原子写：先写同目录临时文件再 os.replace，避免中途崩溃留下半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _split_frontmatter(raw: str) -> tuple[dict, str]:
    """拆分 YAML frontmatter 与正文。缺 frontmatter 时返回 ({}, 全文)。"""
    text = raw.lstrip("\ufeff")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        return {}, text.strip()
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, m.group(2).strip()


# ============ 数据模型 ============

@dataclass
class MemoryEntry:
    id: str = ""
    kind: str = "domain"
    title: str = ""
    tags: list = field(default_factory=list)
    topic_key: str = ""
    status: str = "active"
    always: bool = False
    source: str = ""
    created: str = ""
    updated: str = ""
    body: str = ""

    @property
    def file_name(self) -> str:
        return f"{self.id}.md"

    @property
    def path(self) -> Path:
        return ENTRIES_DIR / self.file_name

    def to_markdown(self) -> str:
        meta = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "tags": list(self.tags or []),
            "topic_key": self.topic_key,
            "status": self.status,
            "always": bool(self.always),
            "source": self.source,
            "created": self.created,
            "updated": self.updated,
        }
        fm = yaml.safe_dump(
            meta, allow_unicode=True, sort_keys=False, default_flow_style=False
        ).rstrip()
        return f"---\n{fm}\n---\n\n{self.body.strip()}\n"

    def searchable_text(self) -> str:
        return f"{self.title} {self.topic_key} {' '.join(self.tags)} {self.body}"

    def one_line(self) -> str:
        """召回注入时用的紧凑摘要：标题 + 正文首句。"""
        first = ""
        for line in self.body.strip().splitlines():
            line = line.strip().lstrip("-*0123456789. ").strip()
            if line and not line.startswith("#"):
                first = line
                break
        head = self.title or first[:30]
        return f"[{self.id}] {head}"


def _entry_from_file(path: Path) -> Optional[MemoryEntry]:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None
    meta, body = _split_frontmatter(raw)
    if not meta.get("id"):
        return None
    return MemoryEntry(
        id=str(meta.get("id", "")),
        kind=str(meta.get("kind", "domain")),
        title=str(meta.get("title", "")),
        tags=list(meta.get("tags") or []),
        topic_key=str(meta.get("topic_key", "") or ""),
        status=str(meta.get("status", "active")),
        always=bool(meta.get("always", False)),
        source=str(meta.get("source", "") or ""),
        created=str(meta.get("created", "") or ""),
        updated=str(meta.get("updated", "") or ""),
        body=body,
    )


def _next_id(kind: str) -> str:
    prefix = _KIND_PREFIX.get(kind, "M")
    n = 0
    for f in ENTRIES_DIR.glob(f"{prefix}-*.md"):
        m = re.match(rf"{prefix}-(\d+)", f.stem)
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}-{n + 1:04d}"


# ============ 读写 ============

def list_entries(kind: Optional[str] = None, status: Optional[str] = "active") -> list:
    """列出记忆条目。status=None 表示不过滤状态。"""
    _ensure_dirs()
    out = []
    for f in sorted(ENTRIES_DIR.glob("*.md")):
        e = _entry_from_file(f)
        if not e:
            continue
        if kind and e.kind != kind:
            continue
        if status and e.status != status:
            continue
        out.append(e)
    return out


def get_entry(entry_id: str) -> Optional[MemoryEntry]:
    return _entry_from_file(ENTRIES_DIR / f"{entry_id}.md")


def save_entry(entry: MemoryEntry, archive_reason: str = "update") -> MemoryEntry:
    """写入（或覆盖）一条记忆。覆盖时旧版转入 archive，不静默抹除。"""
    _ensure_dirs()
    if not entry.id:
        entry.id = _next_id(entry.kind)
    entry.updated = _now()
    if not entry.created:
        entry.created = entry.updated
    if entry.kind not in VALID_KINDS:
        entry.kind = "domain"
    if entry.status not in VALID_STATUS:
        entry.status = "active"

    # 覆盖前先归档旧版
    if entry.path.exists():
        old = _entry_from_file(entry.path)
        if old:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            adir = ARCHIVE_DIR / f"{entry.id}-{ts}"
            adir.mkdir(parents=True, exist_ok=True)
            _atomic_write(
                adir / f"{entry.id}.md",
                f"<!-- 归档原因：{archive_reason}；归档时间：{_now()} -->\n\n{old.to_markdown()}",
            )
            if old.created and not entry.created:
                entry.created = old.created
    _atomic_write(entry.path, entry.to_markdown())
    return entry


def delete_entry(entry_id: str, hard: bool = False) -> bool:
    """删除记忆。默认转归档（可回溯），hard=True 才真正删文件。"""
    _ensure_dirs()
    p = ENTRIES_DIR / f"{entry_id}.md"
    if not p.exists():
        return False
    if hard:
        p.unlink()
        return True
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    adir = ARCHIVE_DIR / f"{entry_id}-{ts}"
    adir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(adir / f"{entry_id}.md"))
    return True


def set_status(entry_id: str, status: str) -> Optional[MemoryEntry]:
    if status not in VALID_STATUS:
        return None
    e = get_entry(entry_id)
    if not e:
        return None
    e.status = status
    return save_entry(e, archive_reason=f"status->{status}")


# ============ 去重与冲突检测 ============

def _norm(text: str) -> str:
    """归一化用于相似度比较：去标点空白、转小写。"""
    return re.sub(r"[\s\W_]+", "", (text or "").lower())


def similarity(a: str, b: str) -> float:
    """字符级相似度（difflib）。

    ⚠️ **只能识别改写，不能识别语义**。实测局限（勿据此判断"矛盾"）：
        - 「预算表交付格式偏好」vs「交付偏好：给可粘贴表格」→ 0.41（同一件事，改述）
        - 「高水位=满管流」vs「高水位=地下水入渗」           → 0.48（真正矛盾）
      即「矛盾」得分反而高于「重复」，**词面相似度无法区分二者**。
      因此本函数只用于「是否明显重复」的初筛；
      真正的矛盾判定交 `memory_extract` 用 LLM 做语义裁决，
      两者都拿不准时一律进 `memory/pending.md` 等人工裁决。
    """
    ca, cb = _norm(a), _norm(b)
    if not ca or not cb:
        return 0.0
    return difflib.SequenceMatcher(None, ca, cb).ratio()


def find_similar(entry: MemoryEntry, threshold: float = SIM_RELATED) -> list:
    """找出与给定记忆相似的既有记忆，按相似度降序。"""
    target = entry.searchable_text()
    hits = []
    for e in list_entries(status=None):
        if e.id == entry.id:
            continue
        r = similarity(target, e.searchable_text())
        if r >= threshold:
            hits.append((r, e))
    hits.sort(key=lambda x: x[0], reverse=True)
    return [(e, r) for r, e in hits]


def _topic_matches(a: str, b: str) -> bool:
    """判断两个 topic_key 是否指同一议题。

    LLM 每次运行都会自造 topic_key 措辞，实测同一议题会出现：
        存储 `概念解释风格` vs 新提 `讲解风格`
        存储 `数据脱敏`     vs 新提 `数据安全`
        存储 `高水位`       vs 新提 `术语口径`
    精确匹配会全部漏判、导致重复入库。故取「相等 / 互相包含 / 共享字符」三档：
        - 共享 ≥2 个字符即视为同议题候选（阈值 2 可排除「数据」vs「安全」这类偶然共字）；
        - 即便匹配上也不直接入库，仍要送 LLM 做语义裁决。
    """
    x, y = (a or "").strip(), (b or "").strip()
    if not x or not y:
        return False
    if x == y:
        return True
    if x in y or y in x:
        return True
    return len(set(x) & set(y)) >= 2


def find_same_topic(entry: MemoryEntry) -> list:
    """找出**同议题**（topic_key 相同）的既有记忆，不看相似度。

    用于把「同议题」的所有条目交给 LLM 做语义裁决：
    既然是同一议题，无论措辞差异大小都必须问一句「这是补充还是矛盾」——
    不能靠相似度阈值提前过滤掉（实测「概念讲解风格偏好」与
    「概念解释要深入浅出配案例」相似度仅 0.39，若按阈值过滤就会漏判、重复入库）。
    """
    if not entry.topic_key:
        return []
    return [e for e in list_entries(status=None)
            if e.id != entry.id and _topic_matches(e.topic_key, entry.topic_key)]


def find_conflicts(entry: MemoryEntry) -> list:
    """找出同议题但词面差异较大的既有记忆（**仅词面初筛，不作最终判定**）。

    ⚠️ 词面相似度无法区分「改述」与「矛盾」（实测矛盾对得分反而更高），
    故本函数只用于**缩小待裁决范围**，真正的矛盾判定必须在
    `memory_extract.adjudicate()` 里由 LLM 完成。
    """
    if not entry.topic_key:
        return []
    out = []
    for e in list_entries(status=None):
        if e.id == entry.id or e.topic_key != entry.topic_key:
            continue
        r = similarity(entry.searchable_text(), e.searchable_text())
        if r < SIM_RELATED:
            out.append((e, r))
    return out


# ============ 每日会话日志 ============

def append_daily(lines: Iterable[str], date_str: Optional[str] = None) -> Path:
    """追加一条会话记录到 memory/daily/YYYY-MM-DD.md（append-only）。"""
    _ensure_dirs()
    d = date_str or datetime.now().strftime("%Y-%m-%d")
    p = DAILY_DIR / f"{d}.md"
    prev = p.read_text(encoding="utf-8") if p.exists() else f"# {d} 会话日志\n"
    body = "\n".join(lines).rstrip()
    if prev and not prev.endswith("\n"):
        prev += "\n"
    _atomic_write(p, f"{prev}\n{body}\n")
    return p


def list_daily(limit: int = 10) -> list:
    _ensure_dirs()
    return sorted(DAILY_DIR.glob("*.md"), reverse=True)[:limit]


# ============ 召回 ============

def _tokens(text: str) -> set:
    """中文取 2-gram + 英文数字整词，用于相关性打分。"""
    t = (text or "").lower()
    toks = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", t):
        if len(run) == 1:
            toks.add(run)
        for i in range(len(run) - 1):
            toks.add(run[i:i + 2])
    toks.update(re.findall(r"[a-z0-9]{2,}", t))
    return toks


def _score(entry: MemoryEntry, topic: str, topic_tokens: set) -> float:
    if entry.always:
        return 100.0
    s = 0.0
    et = _tokens(entry.searchable_text())
    if topic_tokens and et:
        s += 6.0 * len(topic_tokens & et) / len(topic_tokens)
    if entry.topic_key and (entry.topic_key in topic or entry.topic_key in topic_tokens):
        s += 3.0
    for tag in entry.tags or []:
        if tag and (tag in topic or tag in topic_tokens):
            s += 1.5
    if entry.kind == "user":
        s += 0.8   # 操作者偏好略微加权：影响每一次交付
    return s


def recall(topic: str, limit: int = 8, kinds: Optional[list] = None) -> list:
    """按与 topic 的相关性召回记忆，返回 MemoryEntry 列表（已排序、已去重）。"""
    entries = list_entries(status="active")
    if kinds:
        entries = [e for e in entries if e.kind in kinds]
    tt = _tokens(topic)
    scored = [(_score(e, topic or "", tt), e) for e in entries]
    scored = [(s, e) for s, e in scored if s > 0]
    scored.sort(key=lambda x: (-x[0], x[1].id))
    return [e for _s, e in scored[:limit]]


def build_memory_block(topic: str, limit: int = 8, kinds: Optional[list] = None) -> str:
    """生成注入 Crew 的记忆上下文块。无可用记忆时返回空串。

    本函数自带标题（`## 长期记忆`），调用方只需把返回值拼进提示词，
    不要重复再加标题——否则同一块内容会出现两个层级标题。
    """
    items = recall(topic, limit=limit, kinds=kinds)
    if not items:
        return ""
    lines = [
        "## 长期记忆（必须遵守，优先于你的通用写作习惯）",
        "",
        "（以下为长期积累的操作者偏好与领域约定，来自操作者本人确认；"
        "与你的默认习惯冲突时以此为准。）",
        "",
    ]
    for e in items:
        badge = {"user": "偏好", "project": "在办", "domain": "领域"}.get(e.kind, e.kind)
        lines.append(f"- **{badge}｜{e.title or e.one_line()}**（{e.id}）")
        for ln in e.body.strip().splitlines():
            ln = ln.strip()
            if ln:
                lines.append(f"  - {ln.lstrip('-*0123456789. ')}")
    return "\n".join(lines) + "\n"


# ============ 待审队列（自动整理的产物） ============

def add_pending(proposals: list, source_desc: str = "") -> int:
    """把 LLM 提议的候选记忆写入待审文件，返回条目数。

    「自动整理」不等于「自动落库」：只有无冲突、无重复的条目才允许自动生效，
    涉及合并/改写/冲突的一律进这里等人工裁决。
    """
    _ensure_dirs()
    if not proposals:
        return 0
    head = (
        f"# 待审记忆提案\n\n> 由自动整理生成，**尚未生效**。\n"
        f"> 操作者可直接编辑本文件，或用 `--mode memory review` 交互处理。\n"
        f"> 处理方式：把每条的状态行改为 `采纳` / `忽略`，或直接删除整节。\n\n"
    )
    if source_desc:
        head += f"来源：{source_desc}\n\n"
    secs = []
    for i, p in enumerate(proposals, 1):
        secs.append(
            f"## 提案 {i}\n\n"
            f"- 状态：待裁决\n"
            f"- 类型：{p.get('kind', 'domain')}\n"
            f"- 标题：{p.get('title', '')}\n"
            f"- 标签：{', '.join(p.get('tags') or []) or '—'}\n"
            f"- 议题：{p.get('topic_key', '') or '—'}\n"
            f"- 理由：{p.get('reason', '') or '—'}\n"
            f"- 与既有的相似度：{p.get('similarity', '—')}\n\n"
            f"**拟写入正文**：\n\n{p.get('body', '').strip()}\n"
        )
    prev = PENDING_FILE.read_text(encoding="utf-8") if PENDING_FILE.exists() else head
    _atomic_write(PENDING_FILE, prev.rstrip() + "\n\n" + ("\n---\n\n".join(secs)) + "\n")
    return len(secs)


def clear_pending() -> bool:
    if PENDING_FILE.exists():
        PENDING_FILE.unlink()
        return True
    return False


def stats() -> dict:
    """记忆库统计，供 `--mode memory stats` 展示。"""
    all_e = list_entries(status=None)
    out = {"total": len(all_e)}
    for k in VALID_KINDS:
        out[k] = sum(1 for e in all_e if e.kind == k)
    for s in VALID_STATUS:
        out[s] = sum(1 for e in all_e if e.status == s)
    out["daily_files"] = len(list(DAILY_DIR.glob("*.md"))) if DAILY_DIR.exists() else 0
    out["pending"] = PENDING_FILE.exists()
    return out
