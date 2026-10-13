"""质量过滤回归自测：assess_quality()。

为什么必须有：2026-10-13 实测发现中文相关性判断用了「整段连续汉字」的 token
交集，导致**发表在北大核心期刊上的中文论文几乎必被误杀**——主题
「排水管网高水位状态下的检测与诊断」与标题「城镇排水管道高水位运行诊断方法」
的 token 交集恒为空。实测后果：知网召回 12 篇中文，���终只剩 1 篇（且那篇是
学位论文，走豁免分支）。核心刊白名单是主闸门，相关性只是辅助过滤，
一旦辅助过滤恒为 false，主闸门就等于形同虚设。

同时锁定可观测性：剔除原因必须出现在 warn 里（否则中文召回塌方看不见）。

运行：python scripts/selftest_quality_filter.py
不联网、不需要 LLM，全部使用离线样本。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.main import assess_quality  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {detail}" if detail else ""))


def rec(title, lang, venue, year=2023, doi="", citations=0, authors="甲"):
    return {"title": title, "lang": lang, "venue": venue, "year": year,
            "doi": doi, "citations": citations, "authors": authors}


def main():
    topic = "排水管网高水位状态下的检测与诊断"
    en_topic = "sewer network high water level"

    print("=== 中文核心刊论文不得被相关性误杀（本次修复的回归锁定）===")
    core_zh = [
        rec("城镇排水管道高水位运行诊断方法", "zh", "中国给水排水"),
        rec("高水位状态下排水管网溢流预测方法", "zh", "环境工程学报"),
        rec("基于多源数据的排水管网诊断模型研究", "zh", "中国给水排水"),
    ]
    kept, warn = assess_quality(core_zh, topic, en_topic)
    check("3 篇北大核心中文论文全部保留", len(kept) == 3, f"保留 {len(kept)}/3")
    check("无「主题不相关」剔除",
          "主题不相关" not in (warn or "") or "剔除 0" in warn,
          (warn or "").splitlines()[0] if warn else "无 warn")

    print("\n=== 中文质量闸门仍然有效 ===")
    mixed = [
        rec("高水位管网溢流预测研究", "zh", "工程管理与技术探讨"),      # 灌水刊
        rec("污水处理厂进水水质预测模型", "zh", "环境科学学报"),         # 核心刊但跑题
        rec("基于神经网络的城市排水冒溢预测及预防研究", "zh", "广州大学"),  # 学位论文
    ]
    kept, warn = assess_quality(mixed, topic, en_topic)
    titles = [p["title"][:12] for p in kept]
    check("灌水刊被剔除", "高水位管网溢流预" not in "".join(titles), f"保留 {titles}")
    check("跑题的核心刊被剔除", "污水处理厂进水" not in "".join(titles))
    check("学位论文被保留（豁免白名单）",
          any("神经网络" in t for t in titles), f"保留 {titles}")

    print("\n=== 英文按英文检索词判相关性 ===")
    en = [
        rec("Water level estimation in sewer pipes using DCNN", "en", "Water",
            doi="10.3390/w12123412", citations=21),
        rec("Coral reef bleaching patterns in the Pacific", "en", "Marine Ecology",
            doi="10.1/other", citations=40),
    ]
    kept, _ = assess_quality(en, topic, en_topic)
    check("英文相关文献保留", len(kept) == 1 and "Water level" in kept[0]["title"])
    check("英文跑题文献剔除", len(kept) == 1, f"保留 {len(kept)}/2")

    print("\n=== 可观测性：剔除原因必须可见 ===")
    kept, warn = assess_quality(mixed, topic, en_topic)
    check("warn 给出剔除条数", "剔除 2/3" in (warn or ""), (warn or "").splitlines()[0])
    check("warn 给出中文剔除原因分类", "中文文献剔除 2 篇" in (warn or ""))
    check("warn 给出样例", "样例：" in (warn or ""))

    print("\n=== 边界：主题无中文词时不得误杀中文 ===")
    en_only_topic = "side-stream EBPR wet weather overflow"
    zh_only = [rec("侧流生物除磷工艺研究", "zh", "中国给水排水")]
    kept, _ = assess_quality(zh_only, en_only_topic, en_only_topic)
    check("英文主题下的中文核心刊不被相关性剔除", len(kept) == 1)

    passed = sum(1 for _n, ok in RESULTS if ok)
    failed = len(RESULTS) - passed
    print("\n" + "=" * 40)
    print(f"结果：{passed} 通过，{failed} 失败")
    print("=" * 40)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())