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
6. **时效与复审**：记忆带 TTL（按 kind 分级：user 90 天 / project 30 天 / domain 365 天）。
   过期**不等于淘汰**，只降权（×0.45）并在注入时标注「久未确认 N 天」，
   由 `memory/review.md` 清单人工复审。召回时自动给未过期条目续期，
   使「用得越多的记忆越不容易过期」。详见 `_age` 一节与 `staleness()`。

文件格式（可直接手改）::

    ---
    id: M-0001
    kind: domain            # domain=领域知识 / user=操作者偏好 / project=在办事项
    title: 高水位的英文语义需拆成两类
    tags: [排水管网, 高水位]
    topic_key: 高水位        # 同一 topic_key 的两条记忆若结论相悖 → 冲突
    status: active          # active / superseded / rejected / draft
    always: false           # true = 每次都注入，不做相关性筛选（但仍受 TTL 降权）
    source: 2026-10-12 对话（用户纠正）
    created: 2026-10-12T09:00:00
    updated: 2026-10-12T09:00:00
    confirmed: 2026-10-12T09:00:00   # 上次确认「仍然成立」，TTL 计时基准
    confirm_reason: 人工复审          # 人工复审 / 召回时确认
    ttl_days: 0                       # 0 = 用该 kind 的默认 TTL
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
REVIEW_FILE = MEM_DIR / "review.md"

VALID_KINDS = ("domain", "user", "project")
VALID_STATUS = ("active", "superseded", "rejected", "draft")

# 相似度阈值（difflib ratio）
SIM_DUPLICATE = 0.85   # ≥ 此值视为重复，自动合并
SIM_RELATED = 0.55      # ≥ 此值视为相关，列入待审并建议合并

_KIND_PREFIX = {"domain": "M", "user": "U", "project": "P"}

# ============ TTL 与复审 ============
#
# 为什么需要：偏好会变（「以后给我 TSV」半年后可能改成 xlsx）。
# 原实现里 _score() 只看词面重合度、**完全没有时间项**，
# 于是「6 个月前写的旧偏好」与「昨天确认的新偏好」在召回时完全等价，
# 甚至旧条目会因 `always=true` 或 `kind=user` 的加权压过新条目。
#
# 设计原则（重要）：**过期 = 降权 + 提示复审，而不是淘汰**。
# 半年后改成 xlsx 很可能只是那一个项目的要求，不是永久偏好；
# 自动删除会误伤。所有超期项一律进「复审」流程，仍可用但不主导打分。
#
# TTL 按 kind 分级：
#   user    操作者偏好 —— 最容易变（口味、交付格式），TTL 最短
#   project 在办事项   —— 天然会过期，但**不自动降权**，改由人工归档
#   domain  领域知识   —— 术语口径、技术路线这类事实最稳定，TTL 最长

TTL_DAYS = {"user": 90, "domain": 365, "project": 30}

# 超期后的降权系数（乘在打分上）。刻意保留 0.45 这个下限：
# 过期记忆仍应能被召回，但不会盖过新鲜且高度相关的内容。
STALE_FACTOR = 0.45

# 超过 TTL 多少倍后视为「深度过期」，在注入时显式标注天数。
STALE_DEEP_MULTIPLIER = 2.0


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


# ============ 文本清洗 ============

_LIST_MARK = re.compile(r"^\s*(?:[-*+>\u2022]|\d+[.)\u3001])\s+")


def _strip_marker(line: str) -> str:
    """剥掉 Markdown 列表标记 / 编号前缀，**保留正文原样**。

    不用 `lstrip(chars)`——它按字符集剥离，会把 "1.5 吨" 的 "1." 一并吃掉，
    把数字开头的正常句子毁成 "5 吨"。这里改用正则只匹配列表标记本身。
    """
    out = _LIST_MARK.sub("", (line or "").strip())
    return out.strip()


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
    # ---- 时效字段（2026-10-12 新增）----
    confirmed: str = ""          # 上次确认「仍然成立」的时间，TTL 计时基准
    confirm_reason: str = ""     # 确认方式：人工复审 / 召回时确认
    ttl_days: int = 0            # 覆盖该 kind 的默认 TTL；0 = 用默认值
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
            "confirmed": self.confirmed,
            "confirm_reason": self.confirm_reason,
            "ttl_days": self.ttl_days,
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
            line = _strip_marker(line)
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
        confirmed=str(meta.get("confirmed", "") or ""),
        confirm_reason=str(meta.get("confirm_reason", "") or ""),
        ttl_days=int(meta.get("ttl_days", 0) or 0),
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
    # 首次入库即视为「已确认」：TTL 从入库那一刻起算，而不是从零。
    # 后续 update 若未显式给出 confirmed，保留旧值（内容没变，确认时间也不该变）。
    if not entry.confirmed:
        entry.confirmed = entry.created
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


# ============ 时效（TTL / 过期） ============

def _parse_dt(s: str) -> Optional[datetime]:
    """解析 frontmatter 里的时间戳；解析不了返回 None（不报错）。"""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19] if fmt != "%Y-%m-%d" else s[:10], fmt)
        except ValueError:
            continue
    return None


def ttl_days(entry: MemoryEntry) -> int:
    """该条目的 TTL（天）。可用条目自带 ttl_days 覆盖默认值。"""
    return entry.ttl_days if entry.ttl_days else TTL_DAYS.get(entry.kind, 365)


def age_days(entry: MemoryEntry, now: Optional[datetime] = None) -> Optional[int]:
    """距上次确认过去了多少天。优先用 `confirmed`，退回 `updated`，再退回 `created`。

    返回 None 表示三个时间戳都缺失——此时**不施加任何降权**，
    因为无法判定新旧时，宁可保持原状也不要凭空压低一条记忆的权重。
    """
    now = now or datetime.now()
    for ts in (entry.confirmed, entry.updated, entry.created):
        dt = _parse_dt(ts)
        if dt:
            return max(0, (now - dt).days)
    return None


def staleness(entry: MemoryEntry, now: Optional[datetime] = None) -> dict:
    """判断一条记忆的时效状态，供打分降权、注入标注、复审扫描共用。"""
    age = age_days(entry, now)
    ttl = ttl_days(entry)
    if age is None:
        return {"age": None, "ttl": ttl, "stale": False, "deep": False, "factor": 1.0}
    stale = age > ttl
    deep = stale and age > ttl * STALE_DEEP_MULTIPLIER
    return {
        "age": age,
        "ttl": ttl,
        "stale": stale,
        "deep": deep,
        "factor": STALE_FACTOR if stale else 1.0,
    }


def touch(entry_id: str, reason: str = "召回时确认") -> Optional[MemoryEntry]:
    """续期：把某条记忆标记为「本次任务中仍然成立」，重置 TTL 计时。

    这是复审的**自动**一半：被召回且本次仍然适用的记忆会自动续期，
    于是「用得越多越不容易过期」，复审成本由实际使用频率承担。
    人工复审走 `confirm_entry()`。
    """
    e = get_entry(entry_id)
    if not e:
        return None
    ts = _now()
    e.confirmed = ts
    e.confirm_reason = reason
    # 直接写文件而不走 save_entry()：续期不是内容变更，
    # 不该在 archive/ 里堆出一份内容完全相同的副本。
    _ensure_dirs()
    _atomic_write(e.path, e.to_markdown())
    return e


def confirm_entry(entry_id: str, reason: str = "人工复审") -> Optional[MemoryEntry]:
    """人工确认：同 touch，但语义上区分「人确认过」与「召回时自动续期」。"""
    return touch(entry_id, reason=reason)


def list_stale(kind: Optional[str] = None) -> list:
    """列出所有超期记忆（含未超期但深度超期的），按超期程度降序。

    供 `--mode memory stale` 展示与 `--mode memory review` 批量复审使用。
    """
    now = datetime.now()
    out = []
    for e in list_entries(status="active"):
        if kind and e.kind != kind:
            continue
        st = staleness(e, now)
        if st["stale"]:
            out.append((st["age"] / max(1, st["ttl"]), st, e))
    out.sort(key=lambda x: (-x[0], x[2].id))
    return [(st, e) for _r, st, e in out]


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
        # always=true 也必须过一遍降权：否则一条 N 个月前设的 always
        # 会永久压制同主题的新记忆，「always」就变成了「永不过期」。
        return 100.0 * staleness(entry)["factor"]
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
    return s * staleness(entry)["factor"]


def recall(topic: str, limit: int = 8, kinds: Optional[list] = None,
           auto_confirm: bool = False) -> list:
    """按与 topic 的相关性召回记忆，返回 MemoryEntry 列表（已排序、已去重）。

    `auto_confirm=True` 时，被召回且未超期的条目会自动续期（`confirmed` 重置为
    现在）——即「本次任务里这条偏好仍然适用」。这让**用得越多的记忆越不容易
    过期**，复审成本由实际使用频率承担，而不是靠定时器全表扫描。
    超期条目不自动续期：它们必须先经过人工或 LLM 复审。
    """
    entries = list_entries(status="active")
    if kinds:
        entries = [e for e in entries if e.kind in kinds]
    tt = _tokens(topic)
    scored = [(_score(e, topic or "", tt), e) for e in entries]
    scored = [(s, e) for s, e in scored if s > 0]
    scored.sort(key=lambda x: (-x[0], x[1].id))
    picked = [e for _s, e in scored[:limit]]
    if auto_confirm:
        for e in picked:
            if not staleness(e)["stale"]:
                touch(e.id, reason="召回时确认")
    return picked


def build_memory_block(topic: str, limit: int = 8, kinds: Optional[list] = None) -> str:
    """生成注入 Crew 的记忆上下文块。无可用记忆时返回空串。

    本函数自带标题（`## 长期记忆`），调用方只需把返回值拼进提示词，
    不要重复再加标题——否则同一块内容会出现两个层级标题。
    """
    items = recall(topic, limit=limit, kinds=kinds, auto_confirm=True)
    if not items:
        return ""
    stale = [e for e in items if staleness(e)["stale"]]
    lines = [
        "## 长期记忆（必须遵守，优先于你的通用写作习惯）",
        "",
        "（以下为长期积累的操作者偏好与领域约定，来自操作者本人确认；"
        "与你的默认习惯冲突时以此为准。）",
        "",
    ]
    if stale:
        lines += [
            f"⚠️ 下列 {len(stale)} 条记忆标注「久未确认」，可能已不适用于当前偏好，"
            "以本次明确指令为准；若与指令冲突，按指令执行。",
            "",
        ]
    for e in items:
        badge = {"user": "偏好", "project": "在办", "domain": "领域"}.get(e.kind, e.kind)
        st = staleness(e)
        mark = ""
        if st["stale"] and st["age"] is not None:
            mark = f"　[久未确认：{st['age']} 天前]"
        lines.append(f"- **{badge}｜{e.title or e.one_line()}**（{e.id}）{mark}")
        for ln in e.body.strip().splitlines():
            ln = _strip_marker(ln)
            if ln:
                lines.append(f"  - {ln}")
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


def build_review_queue() -> list:
    """生成复审清单：所有超期记忆 + 各自的确认时间与超期倍数。

    供 `--mode memory stale` 展示，也供 `write_review_file()` 落盘。
    """
    return [(st, e) for st, e in list_stale()]


def write_review_file() -> Optional[Path]:
    """把复审清单写到 `memory/review.md`，供人工逐条处置。

    与 `pending.md`（入库前的新提案）**刻意分成两个文件**：
      - pending.md = 还没进库，等你决定要不要收
      - review.md  = 已经生效过、但久未确认，等你决定还留不留
    混在一个文件里，操作者分不清「这条到底生效了没」。
    """
    items = build_review_queue()
    if not items:
        return None
    _ensure_dirs()
    lines = [
        "# 记忆复审清单",
        "",
        "> 这些记忆**当前仍在生效**，但已超过各自的 TTL，久未确认。",
        "> 处置方式：",
        ">   1. 仍然成立 → 在条目文件里把 `confirmed` 改成当前时间（或跑 "
        "`--mode memory confirm <ID>`）",
        ">   2. 已被新偏好取代 → `--mode memory drop <ID>`（转归档，不删）",
        ">   3. 只是想改内容 → 直接编辑该条目文件",
        "",
        f"生成时间：{_now()}",
        "",
        "| ID | 类型 | 标题 | 上次确认 | 已有 | TTL | 超期 |",
        "|---|---|---|---|---|---|---|",
    ]
    for st, e in items:
        last = (e.confirmed or e.updated or e.created or "未知")
        last_s = last[:10]
        over = f"{st['age'] / max(1, st['ttl']):.1f}×"
        lines.append(
            f"| {e.id} | {e.kind} | {e.title or e.one_line()} | {last_s} | "
            f"{st['age']} 天 | {st['ttl']} 天 | {over} |"
        )
    lines.append("")
    _atomic_write(REVIEW_FILE, "\n".join(lines) + "\n")
    return REVIEW_FILE


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
    stale = list_stale()
    out["stale"] = len(stale)
    out["review_file"] = REVIEW_FILE.exists()
    return out
