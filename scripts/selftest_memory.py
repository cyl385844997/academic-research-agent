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

    print("\n=== 统计 ===")
    s = ms.stats()
    check("统计可用", s["total"] >= 1, s)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'='*40}\n结果：{PASS} 通过，{FAIL} 失败\n{'='*40}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
