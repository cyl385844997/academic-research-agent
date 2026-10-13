"""护栏回归自测：sanitize_report_citations / sanitize_report_urls。

为什么必须有这个：2026-10-12 实测发现旧文献综述正文 51 个引用里 50 个是编造的，
而当时两道闸口只做了 URL 侧、引用侧没有。护栏本身一旦被改坏（例如 DOI 正则
收窄、截断逻辑改错），编造就会重新悄悄进来——必须用固定样本锁住行为。

运行：python scripts/selftest_guardrails.py
不联网、不需要 LLM，全部使用离线样本。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.main import (_DOI_RE, _clean_doi, sanitize_report_citations,  # noqa: E402
                      sanitize_report_urls)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {detail}" if detail else ""))


def run_citation_gate(text, allowed):
    """在临时文件上跑 DOI 闸口，返回处理后文本与被剔除清单。"""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as f:
        f.write(text)
        path = f.name
    try:
        dropped = sanitize_report_citations(path, allowed_dois=allowed)
        with open(path, encoding="utf-8") as f:
            return f.read(), dropped
    finally:
        os.unlink(path)


def run_url_gate(text, allowed):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as f:
        f.write(text)
        path = f.name
    try:
        sanitize_report_urls(path, allowed_urls=allowed)
        with open(path, encoding="utf-8") as f:
            return f.read()
    finally:
        os.unlink(path)


def main():
    print("=== DOI 抽取与规整 ===")
    # ASCE 系列真实 DOI 含括号与冒号，不能被截断
    asce = "10.1061/(ASCE)0733-9429(2003)129:7(504)"
    check("ASCE 含括号 DOI 完整保留", _clean_doi(asce) == asce.lower(),
          _clean_doi(asce))
    # 报告里常见的「DOI:xxx，被引121次」形态
    check("中文逗号后缀被正确截断",
          _clean_doi("10.1016/j.autcon.2019.04.013，被引121次")
          == "10.1016/j.autcon.2019.04.013")
    # 文末句号不应留在 DOI 里
    check("尾部句号被剥离",
          _clean_doi("10.1000/xyz123.") == "10.1000/xyz123")
    # 不成对的右括号应剔除（DOI 自身含成对括号时必须保留，见上一条）
    check("不成对右括号被剔除",
          _clean_doi("10.1000/xyz123)") == "10.1000/xyz123")
    check("成对括号不被剔除",
          _clean_doi("10.1061/40937(261)") == "10.1061/40937(261)")

    print("\n=== DOI 闸门：编造引用必须被剔除 ===")
    allowed = [
        "10.3390/w12123412",
        "10.1109/access.2021.3115981",
        asce,
    ]
    sample = (
        "真实引用 A（DOI:10.3390/w12123412）与 B（DOI:10.1109/access.2021.3115981）应保留。\n"
        "编造引用 C（DOI:10.1016/j.envres.2021.111609）应被剔除。\n"
        "编造引用 D（DOI:10.3390/infrastructures4010010，被引86次）应被剔除。\n"
        "含括号真实引用 E（DOI:10.1061/(ASCE)0733-9429(2003)129:7(504)）应保留。\n"
    )
    out, dropped = run_citation_gate(sample, allowed)
    check("白名单内 DOI 全部保留",
          "10.3390/w12123412" in out and "10.1109/access.2021.3115981" in out
          and "10.1061/(asce)0733-9429(2003)129:7(504)" in out.lower())
    check("白名单外 DOI 被剔除", len(dropped) == 2, f"剔除 {dropped}")
    check("剔除处留下标记", out.count("〔DOI 不可溯源，已剔除〕") == 2)
    check("编造 DOI 未残留在正文",
          "10.1016/j.envres.2021.111609" not in out
          and "10.3390/infrastructures4010010" not in out)

    print("\n=== DOI 闸门：空/缺 DOI 的中文文献不应误伤 ===")
    zh_sample = "陈盼（2021，广州大学）学位论文，基于神经网络的城市排水冒溢预测（无 DOI）。\n"
    out_zh, dropped_zh = run_citation_gate(zh_sample, allowed)
    check("无 DOI 记录不受影响", out_zh == zh_sample and dropped_zh == [])

    print("\n=== URL 闸门 ===")
    urls_allowed = ["https://www.ks.gov.cn/a.shtml", "https://example.org/x/"]
    url_sample = (
        "真实来源：[昆山政府](https://www.ks.gov.cn/a.shtml) 应保留。\n"
        "编造来源：https://www.linkedin.com/posts/fake 应标记。\n"
        "裸链 https://example.org/x/ 应保留。\n"
    )
    out_url = run_url_gate(url_sample, urls_allowed)
    check("白名单内 markdown 链接保留", "https://www.ks.gov.cn/a.shtml" in out_url)
    check("白名单外链接被标记", "linkedin" not in out_url and "来源待核实" in out_url)
    check("白名单内裸链保留", "https://example.org/x/" in out_url)

    print("\n=== 闸门空值保护 ===")
    out_none, dropped_none = run_citation_gate("DOI:10.1000/abc", [])
    check("白名单为空时不改动文件（避免误删全部引用）",
          "10.1000/abc" in out_none and dropped_none == [])

    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    failed = len(RESULTS) - passed
    print("\n" + "=" * 40)
    print(f"结果：{passed} 通过，{failed} 失败")
    print("=" * 40)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())