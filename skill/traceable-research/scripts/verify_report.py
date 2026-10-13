"""产物独立核验器：抽检一份 markdown 调研报告里的引用是否可溯源。

定位：项目自带的两道闸口（sanitize_report_urls / sanitize_report_citations）
是**进程内**的——只有跑项目的流水线才生效。本脚本是**带外审计**：对任意
markdown 报告（包括别人写的、LLM 现场生成的、脱离项目跑出来的）做独立抽检，
只用标准库，不import 项目任何模块，因此可在任何环境使用。

用法：
    python verify_report.py REPORT.md [REPORT2.md ...]
    python verify_report.py REPORT.md --refs refs.tsv            # TSV 内含 DOI 或 URL 列
    python verify_report.py REPORT.md --refs academic.json       # papers[].doi / records[].url
    python verify_report.py REPORT.md --refs a.tsv --refs b.json --json

退出码：
    0 = 通过（无越界引用，或无白名单可比对）
    1 = 发现越界引用（白名单外DOI/URL）
    2 = 发现未处理的风险标记（闸口剔除标记、伪造检索措辞等）

为什么必须有：实测（2026-10-12）一份文献综述正文 51 个引用里 50 个是编造的，
而当时只有 URL 侧有闸口、引用侧没有。prompt 里写「逐字照抄」完全无效。
任何声称「引用可溯源」的产物，都应该被本脚本独立抽检一遍，而不是相信它自己。
"""
import argparse
import json
import os
import re
import sys

# ---- DOI / URL 抽取（与项目 main.py 同规整规则，但独立实现以便带外审计）----
_DOI_RE = re.compile(r"10\.\d{4,9}/\S{3,}")
_URL_RE = re.compile(r"https?://[^\s)\]<>\u3000]+")
_DOI_SPLIT = re.compile(r"[\s\uff0c\u3002\uff1b\u3001\uff1a,;)\uff09]")

# 闸口留下的标记：出现了说明项目护栏已经拦过一次，产物不是「干净」的
_GATE_MARKERS = [
    "\u3010DOI \u4e0d\u53ef\u6eaf\u6e90\uff0c\u5df2\u5254\u9664\u3011",   # 〔DOI 不可溯源，已剔除〕
    "\uff08\u6765\u6e90\u5f85\u6838\u5b9e\uff09",                      # （来源待核实）
]

# 伪造检索过程的措辞：tools=[] 的角色扮演式检索会留下这种痕迹
_FAKE_SEARCH_PATTERNS = [
    (r"\u68c0\u7d22[\u2018\u201c\"]?[^\u2019\u201d\"]{0,20}[\u2019\u201d\"]?\s*\u8fd4\u56de\s*0\s*\u6761", "声称某次检索返回 0 条结果"),
    (r"\u641c\u7d22\s*\u7ed3\u679c\s*\u4e3a\s*0\s*\u6761", "声称搜索结果为 0 条"),
    (r"\u7ecf\u7814\u7a76[\uff08(]?[^\uff09)]{0,10}\uff09?\u663e\u793a\u65e0\u76f8\u5173\u7ed3\u679c", "以研究报告口吻断言无结果"),
]


def clean_doi(raw):
    t = _DOI_SPLIT.split(str(raw or "").strip())[0]
    t = t.rstrip(".,;")
    while t.endswith(")") and t.count(")") > t.count("("):
        t = t[:-1]
    return t.lower()


def load_whitelist(paths):
    """从 TSV/JSON 里收集允许的 DOI 与 URL 集合（按列名/字段名自动识别）。"""
    dois, urls = set(), set()
    used = []
    for p in paths or []:
        if not os.path.exists(p):
            print(f"  [WARN] 白名单文件不存在：{p}", file=sys.stderr)
            continue
        used.append(p)
        if p.lower().endswith(".json"):
            try:
                data = json.load(open(p, encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                print(f"  [WARN] JSON 解析失败：{p}（{exc}）", file=sys.stderr)
                continue
            items = []
            if isinstance(data, dict):
                for key in ("papers", "records", "items", "data"):
                    if isinstance(data.get(key), list):
                        items.extend(data[key])
                if not items:
                    items = [v for v in data.values() if isinstance(v, dict)]
            elif isinstance(data, list):
                items = data
            for it in items:
                if not isinstance(it, dict):
                    continue
                if it.get("doi"):
                    dois.add(clean_doi(it["doi"]))
                if it.get("url"):
                    urls.add(it["url"].rstrip("/").lower())
            continue
        # TSV/CSV：按列名找 DOI / URL
        with open(p, encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
        if not lines:
            continue
        header = [h.strip() for h in lines[0].split("\t")]
        sep = "\t" if "\t" in lines[0] else ","
        i_doi = next((i for i, h in enumerate(header)
                      if h.lower() in ("doi", "doi链接", "doi 号")), None)
        i_url = next((i for i, h in enumerate(header)
                      if h.lower() in ("url", "链接", "source url", "来源链接")), None)
        for ln in lines[1:]:
            cells = [c.strip() for c in ln.split(sep)]
            if i_doi is not None and i_doi < len(cells) and cells[i_doi]:
                dois.add(clean_doi(cells[i_doi]))
            if i_url is not None and i_url < len(cells) and cells[i_url]:
                urls.add(cells[i_url].rstrip("/").lower())
    return dois, urls, used


def audit(path, allowed_dois, allowed_urls):
    text = open(path, encoding="utf-8").read()

    dois = {}
    for m in _DOI_RE.finditer(text):
        d = clean_doi(m.group(0))
        if d:
            dois[d] = dois.get(d, 0) + 1
    urls = {}
    for m in _URL_RE.finditer(text):
        u = m.group(0).rstrip("/.,;")
        urls[u] = urls.get(u, 0) + 1

    over_doi = sorted(d for d in dois if allowed_dois and d not in allowed_dois)
    over_url = sorted(u for u in urls if allowed_urls
                      and u.rstrip("/").lower() not in allowed_urls)

    marks = [m for m in _GATE_MARKERS if m in text]
    fakes = []
    for pat, desc in _FAKE_SEARCH_PATTERNS:
        for m in re.finditer(pat, text):
            line_no = text.count("\n", 0, m.start()) + 1
            fakes.append(f"{desc}（第 {line_no} 行：{m.group(0)[:30]}）")

    return {
        "file": path,
        "chars": len(text),
        "doi_total": len(dois),
        "doi_occurrences": sum(dois.values()),
        "url_total": len(urls),
        "over_doi": over_doi,
        "over_url": over_url,
        "gate_marks": marks,
        "fake_search": fakes,
        "whitelist_compared": bool(allowed_dois or allowed_urls),
    }


def main():
    ap = argparse.ArgumentParser(description="调研报告引用可溯源抽检")
    ap.add_argument("reports", nargs="+", help="待核验的 markdown 报告")
    ap.add_argument("--refs", action="append", default=[],
                    help="白名单文件（TSV/JSON），可多次传入")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args()

    allowed_dois, allowed_urls, used = load_whitelist(args.refs)
    if used:
        print(f"白名单：DOI {len(allowed_dois)} 个 / URL {len(allowed_urls)} 个"
              f"（来自 {', '.join(os.path.basename(u) for u in used)}）")
    else:
        print("白名单：未提供——本次只统计引用数量与风险标记，不做越界判定")
    print("-" * 60)

    results = []
    for rp in args.reports:
        if not os.path.exists(rp):
            print(f"[SKIP] 文件不存在：{rp}")
            continue
        results.append(audit(rp, allowed_dois, allowed_urls))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"\n■ {r['file']}（{r['chars']} 字符）")
            print(f"  引用 DOI：{r['doi_total']} 个不同 / 共 {r['doi_occurrences']} 次")
            print(f"  出现 URL：{r['url_total']} 个不同")
            if r["whitelist_compared"]:
                if r["over_doi"]:
                    print(f"  🚨 越界 DOI（白名单外）：{len(r['over_doi'])} 个")
                    for d in r["over_doi"][:10]:
                        print(f"       - {d}")
                    if len(r["over_doi"]) > 10:
                        print(f"       …… 另有 {len(r['over_doi']) - 10} 个")
                else:
                    print("  ✅ 全部 DOI 均在白名单内")
                if r["over_url"]:
                    print(f"  🚨 越界 URL（白名单外）：{len(r['over_url'])} 个")
                    for u in r["over_url"][:10]:
                        print(f"       - {u}")
                else:
                    print("  ✅ 全部 URL 均在白名单内")
            if r["gate_marks"]:
                print(f"  ⚠️ 检出闸口标记 {len(r['gate_marks'])} 种——产物含被剔除项，"
                      f"引用前须逐条确认")
            if r["fake_search"]:
                print("  🚨 检出伪造检索措辞：")
                for f in r["fake_search"]:
                    print(f"       - {f}")

    verdict = 0
    if any(r["over_doi"] or r["over_url"] for r in results):
        verdict = 1
    if any(r["gate_marks"] or r["fake_search"] for r in results):
        verdict = max(verdict, 2) if verdict else 2
    print("\n" + "=" * 60)
    print("结论：" + {0: "通过", 1: "不通过——存在白名单外引用", 2: "需人工复核"}[verdict])
    return verdict


if __name__ == "__main__":
    sys.exit(main())