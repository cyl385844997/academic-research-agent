"""记忆库自测（不涉及 LLM 与网络，纯本地逻辑）。

覆盖：存储 / 召回打分 / 去重 / 冲突熔断 / 归档 / 凭证拦截 / 原子写。
运行：python scripts/selftest_memory.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def main():
    # 隔离：把记忆目录指向临时目录，避免污染真实记忆库
    import src.tools.memory_store as ms
    tmp = tempfile.mkdtemp(prefix="memtest_")
    ms.MEM_DIR = ms.ENTRIES_DIR.parent / "memory"
    ms.MEM_DIR = __import__("pathlib").Path(tmp)
    ms.ENTRIES_DIR = ms.MEM_DIR / "entries"
    ms.DAILY_DIR = ms.MEM_DIR / "daily"
    ms.ARCHIVE_DIR = ms.MEM_DIR / "archive"
    ms.PENDING_FILE = ms.MEM_DIR / "pending.md"
    ms._ensure_dirs()

    print("=== 存储与读取 ===")
    e1 = ms.MemoryEntry(
        kind="domain", title="高水位=满管流", topic_key="高水位",
        tags=["排水管网"], body="指管网运行水位偏高，英文用 full pipe flow。",
        source="测试", always=False,
    )
    e1 = ms.save_entry(e1)
    check("保存后分配 ID", e1.id.startswith("M-"), e1.id)
    check("可回读", ms.get_entry(e1.id) is not None)
    back = ms.get_entry(e1.id)
    check("标题往返一致", back.title == e1.title, back.title)
    check("正文往返一致", "full pipe flow" in back.body, back.body[:50])
    check("列表可列出", any(x.id == e1.id for x in ms.list_entries()))

    print("\n=== 召回打分 ===")
    hits = ms.recall("高水位排水管网诊断", limit=5)
    check("按主题召回命中", any(h.id == e1.id for h in hits), [h.id for h in hits])
    miss = ms.recall("完全无关的量子色动力学", limit=5)
    check("无关主题不误召回", all(h.id != e1.id for h in miss),
          [h.id for h in miss])

    e_always = ms.save_entry(ms.MemoryEntry(
        kind="user", title="中文回答", body="始终用简体中文输出。",
        source="测试", always=True, topic_key="语言偏好"))
    check("always 条目恒召回", any(h.id == e_always.id for h in ms.recall("任意无关主题xyz")))
    block = ms.build_memory_block("高水位排水管网")
    check("记忆块可生成", "## 长期记忆" in block and e1.id in block, block[:80])
    check("记忆块不重复标题", block.count("## 长期记忆") == 1,
          f"出现 {block.count('## 长期记忆')} 次")

    print("\n=== 去重 ===")
    dup = ms.MemoryEntry(
        kind="domain", title="高水位=满管流", topic_key="高水位",
        tags=["排水管网"], body="指管网运行水位偏高，英文用 full pipe flow。",
        source="测试2")
    sims = ms.find_similar(dup)
    check("识别为重复", sims and sims[0][1] >= ms.SIM_DUPLICATE,
          f"sim={sims[0][1]:.2f}" if sims else "none")

    print("\n=== 冲突熔断（同议题不同口径）===")
    conflict = ms.MemoryEntry(
        kind="domain", title="高水位=地下水入渗", topic_key="高水位",
        body="高水位指地下水入渗导致的水位升高，应用 infiltration and inflow。",
        source="测试")
    confs = ms.find_conflicts(conflict)
    check("检出同议题冲突", any(c[0].id == e1.id for c in confs),
          [c[0].id for c in confs])

    print("\n=== 更新留痕（归档不抹除）===")
    e1.body = "改：高水位=运行水位偏高或溢流风险。"
    ms.save_entry(e1, archive_reason="test-update")
    arch = list(ms.ARCHIVE_DIR.glob(f"{e1.id}-*/{e1.id}.md"))
    check("旧版已归档", len(arch) >= 1, f"{len(arch)} 个归档")
    check("新版生效", "溢流风险" in ms.get_entry(e1.id).body)

    print("\n=== 凭证拦截 ===")
    from src.tools.memory_extract import _has_secret, extract_candidates
    check("识别 ghp_ token", _has_secret("token=ghp_ABCDEFGHIJKLMNOP"))
    check("识别 sk- key", _has_secret("OPENAI_API_KEY=sk-abcdefghijklmn"))
    check("识别明文 password", _has_secret("password: hunter2024"))
    check("含凭证内容拒绝提炼", extract_candidates("我的 token 是 ghp_ABCDEFGHIJKLMNOP") == [])
    check("正常内容不被误拦", not _has_secret("排水管网高水位诊断"))

    print("\n=== 删除转归档 ===")
    ok = ms.delete_entry(e_always.id)
    check("删除后不在生效列表", ok and all(x.id != e_always.id for x in ms.list_entries()))
    check("删除后归档可回溯", len(list(ms.ARCHIVE_DIR.glob(f"{e_always.id}-*/*.md"))) >= 1)

    print("\n=== 文本清洗（_strip_marker） ===")
    cases = [
        ("1.5 吨水电耗降低", "1.5 吨水电耗降低"),
        ("- 交付 TSV", "交付 TSV"),
        ("* 要点一", "要点一"),
        ("2026.9 月提交", "2026.9 月提交"),
        ("1) 第一项", "第一项"),
        ("普通正文行", "普通正文行"),
    ]
    for src, exp in cases:
        check(f"_strip_marker({src!r})", ms._strip_marker(src) == exp,
              f"got {ms._strip_marker(src)!r}")

    print("\n=== TTL 与复审 ===")
    from datetime import datetime, timedelta
    now = datetime.now()

    def aged(kind, days, **kw):
        """造一条「N 天前确认过」的记忆。"""
        e = ms.MemoryEntry(kind=kind, title=kw.pop("title", "测试"),
                           body=kw.pop("body", "正文"), tags=[], status="active", **kw)
        ts = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        e.created = e.updated = e.confirmed = ts
        return e

    fresh_u = aged("user", 10, title="偏好新鲜")
    old_u = aged("user", 200, title="偏好过期")
    old_d = aged("domain", 200, title="领域过期")
    no_ts = ms.MemoryEntry(kind="user", title="无时间戳", body="正文")
    no_ts.created = no_ts.updated = no_ts.confirmed = ""

    check("user TTL = 90 天", ms.ttl_days(fresh_u) == 90, ms.ttl_days(fresh_u))
    check("domain TTL = 365 天", ms.ttl_days(old_d) == 365, ms.ttl_days(old_d))
    check("10 天未超期", ms.staleness(fresh_u)["stale"] is False)
    check("200 天超期", ms.staleness(old_u)["stale"] is True)
    check("超期降权系数生效", abs(ms.staleness(old_u)["factor"] - 0.45) < 1e-6,
          ms.staleness(old_u)["factor"])
    check("未超期不降权", ms.staleness(fresh_u)["factor"] == 1.0)
    check("无时间戳不降权", ms.staleness(no_ts)["factor"] == 1.0)
    check("无时间戳不判过期", ms.staleness(no_ts)["stale"] is False)
    check("200 天超 2×TTL 视为深度过期", ms.staleness(old_u)["deep"] is True)

    # always=true 也必须降权，否则久远的 always 会永久压制新记忆
    always_old = aged("user", 300, title="always 过期")
    always_old.always = True
    s_old = ms._score(always_old, "偏好过期", ms._tokens("偏好过期"))
    check("always 条目同样受降权", s_old < 100.0, s_old)

    check("ttl_days 可被条目覆盖",
          ms.ttl_days(ms.MemoryEntry(kind="user", ttl_days=7)) == 7)
    check("_parse_dt 容忍空值", ms._parse_dt("") is None)
    check("_parse_dt 解析日期", ms._parse_dt("2026-10-12") is not None)

    # 复审清单：只收超期项，且 review.md 与 pending.md 分开
    from pathlib import Path as _P
    _ttl_tmp = _P(tmp)
    saved_dir, ms.ENTRIES_DIR = ms.ENTRIES_DIR, _ttl_tmp / "ttl_entries"
    _ttl_tmp.mkdir(parents=True, exist_ok=True)
    ms.save_entry(old_u, "ttl-test")
    ms.save_entry(fresh_u, "ttl-test")
    q = ms.build_review_queue()
    check("复审清单只含超期项", len(q) == 1 and q[0][1].id == old_u.id,
          [e.id for _st, e in q])
    rp = ms.write_review_file()
    check("review.md 已生成", rp is not None and rp.exists())
    check("review.md 提及超期条目", old_u.id in rp.read_text(encoding="utf-8"))
    check("review.md 不含未超期条目", fresh_u.id not in rp.read_text(encoding="utf-8"))
    check("review.md 与 pending.md 是两个文件", rp != ms.PENDING_FILE)

    # confirm 重置 TTL 计时
    before = ms.age_days(ms.get_entry(old_u.id))
    ms.confirm_entry(old_u.id)
    after = ms.age_days(ms.get_entry(old_u.id))
    check("confirm 后龄期归零", after is not None and after <= 1, f"{before} -> {after}")
    check("confirm 后不再超期",
          ms.staleness(ms.get_entry(old_u.id))["stale"] is False)
    check("confirm 写入确认方式",
          "人工复审" in (ms.get_entry(old_u.id).confirm_reason or ""))

    # 召回自动续期：未超期条目 touch，超期条目不 touch
    fresh_before = ms.age_days(ms.get_entry(fresh_u.id))
    old_aged = aged("user", 200, title="超期不续期")
    ms.save_entry(old_aged, "ttl-test")
    ms.recall("测试 偏好", auto_confirm=True)
    # 注意：续期后龄期为 0，不能写 `age or 默认值`——0 是假值会被误判成"失败"
    _age_after = ms.age_days(ms.get_entry(fresh_u.id))
    check("召回时未超期条目被续期",
          _age_after is not None and _age_after <= 1, f"{fresh_before} -> {_age_after}")
    check("召回时超期条目不自动续期",
          (ms.age_days(ms.get_entry(old_aged.id)) or 0) > 100)

    ms.ENTRIES_DIR = saved_dir
    ms.REVIEW_FILE = _ttl_tmp / "review.md"

    print("\n=== 统计 ===")
    s = ms.stats()
    check("统计可用", s["total"] >= 1, s)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'='*40}\n结果：{PASS} 通过，{FAIL} 失败\n{'='*40}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
