"""双线合流（v0.2 输出层原型）：学术线 + 市场线检索结果并入同一个文本。

终态效果（用户需求）：「两个检索在同一个文本里」——学术线答「能不能做」，
市场线答「值不值得做」，统一证据 schema 并置；交叉带由代码按主题词并置
（非结论）；「该不该我们做」留白交人工对照清单，Agent 不裁决。

数据流（全部真实代码路径，本脚本无 LLM 调用）：
  学术线：src.main.fetch_literature_grounded() 实时抓取
          （知网 + Semantic Scholar/OpenAlex/Crossref），
          首次结果缓存 reports/academic_results.json（含溯源 trace）
  市场线：reports/market_references.tsv（上一次市场线真实运行的产出，
          含分级与命中检索式）；snippet 按 URL 从
          scripts/run_market_real_highwater.py 的 REAL_HITS
          （Agent WebSearch 真实结果）补全，合并缓存
          reports/market_records.json
  合流：  统一 schema → 两线证据表 → 交叉带 → 盲区对比 → 人工对照清单

双溯源标准：学术线 DOI 级；市场线 URL + 抓取日期 + A/B/C 可信度分级。

用法（仓库根目录）：python -u scripts/build_dual_line_evidence.py [--refresh]
  --refresh  忽略缓存重新实时抓取学术线
"""
import datetime
import json
import os
import sys

import dotenv

dotenv.load_dotenv(".env")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from src.tools.source_credibility import classify_source, dedupe_records  # noqa: E402

TOPIC = "排水管网高水位状态下的检测与诊断"
MARKET_FETCH_DATE = "2026-10-12"  # 市场线 URL 抓取日期（注入式 WebSearch 采集日）
ACADEMIC_CACHE = os.path.join(ROOT, "reports", "academic_results.json")
MARKET_CACHE = os.path.join(ROOT, "reports", "market_records.json")
OUT_PATH = os.path.join(ROOT, "reports", "dual_line_evidence.md")

# 交叉带主题词：英文按小写子串匹配，中文按子串匹配（标题+摘要+线索）
CROSS_KEYS = [
    ("声呐检测", ["sonar", "声呐"]),
    ("水位/液位监测", ["water level", "水位", "液位"]),
    ("检测机器人/SLAM", ["robot", "slam", "机器人"]),
    ("CCTV/内窥", ["cctv", "内窥", "电视检测"]),
    ("满管/压力流", ["surcharge", "full pipe", "full-pipe", "满管", "压力流", "pressurized"]),
    ("外水入侵 I/I", ["infiltration", "inflow", "外水", "入侵", "渗漏"]),
    ("诊断/预测/评估", ["predict", "forecast", "diagnos", "estim", "预测", "诊断", "评估"]),
    ("溢流 CSO/SSO", ["overflow", "冒溢", "溢流"]),
    ("淤积/沉积", ["sediment", "deposit", "淤积", "沉积", "积泥"]),
    ("标准/规程", ["standard", "pacs", "nassco", "cjj", "标准", "规程"]),
]


def _cell(text, limit=60):
    """表格单元格净化：去换行、截断、转义竖线。"""
    t = " ".join(str(text or "").split())
    t = t.replace("|", "/")
    return t if len(t) <= limit else t[: limit - 1] + "…"


def fetch_academic(refresh=False):
    """学术线：缓存优先，否则实时抓取（真实代码路径）并落盘缓存。"""
    if os.path.exists(ACADEMIC_CACHE) and not refresh:
        with open(ACADEMIC_CACHE, encoding="utf-8") as f:
            return json.load(f)
    import src.main as main_mod
    _raw, source, papers, warn = main_mod.fetch_literature_grounded(TOPIC, limit=15)
    data = {
        "topic": TOPIC,
        "source": source,
        "warn": warn,
        "trace": list(getattr(main_mod, "_LAST_TRACE", [])),
        "papers": papers,
        "fetched_at": datetime.date.today().isoformat(),
    }
    os.makedirs(os.path.dirname(ACADEMIC_CACHE), exist_ok=True)
    with open(ACADEMIC_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data


def load_market():
    """市场线：TSV（真实运行产出）为主，snippet 按 URL 从 REAL_HITS 补全。"""
    tsv_path = os.path.join(ROOT, "reports", "market_references.tsv")
    if not os.path.exists(tsv_path):
        raise FileNotFoundError(f"缺少市场线产出：{tsv_path}（先跑市场线）")

    import run_market_real_highwater as rmh
    hits_by_url = {h["url"]: h for h in rmh.REAL_HITS}

    records = []
    with open(tsv_path, encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        for line in f:
            if not line.strip():
                continue
            row = dict(zip(header, line.rstrip("\n").split("\t")))
            url = row.get("URL", "")
            hit = hits_by_url.get(url, {})
            records.append({
                "org": row.get("产品/机构", ""),
                "title": row.get("来源标题", ""),
                "url": url,
                "tier": row.get("可信度", ""),
                "clue": row.get("功能线索", ""),
                "query_hit": row.get("命中检索式", ""),
                "snippet": hit.get("snippet", ""),
            })
    # 过一遍真实去重代码（TSV 已去过重，双保险）
    slim = [{"title": r["title"], "url": r["url"], "snippet": r["snippet"],
             "tier": r["tier"], "query_hit": r["query_hit"]} for r in records]
    slim = dedupe_records(slim)
    by_url = {r["url"]: r for r in records}
    records = [{**by_url.get(r["url"], {}), **{k: r[k] for k in ("title", "url", "snippet", "tier", "query_hit")}}
               for r in slim]

    queries = sorted({r["query_hit"] for r in records if r.get("query_hit")})
    tier_stat = {}
    for r in records:
        tier_stat[r["tier"]] = tier_stat.get(r["tier"], 0) + 1
    data = {"topic": TOPIC, "fetch_date": MARKET_FETCH_DATE,
            "queries": queries, "tier_stat": tier_stat, "records": records}
    os.makedirs(os.path.dirname(MARKET_CACHE), exist_ok=True)
    with open(MARKET_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data


def _match(text, keys):
    t = str(text or "").lower()
    return any(k in t for k in keys)


def build_cross_band(academic, market):
    """交叉带：代码按主题词在两条线各自匹配，并置不结论。"""
    band = []
    for label, keys in CROSS_KEYS:
        a_hits, m_hits = [], []
        for i, p in enumerate(academic, 1):
            if _match(p.get("title", ""), keys):
                a_hits.append((f"A-{i:02d}", p.get("title", "")))
        for i, r in enumerate(market, 1):
            blob = " ".join([r.get("title", ""), r.get("snippet", ""),
                             r.get("org", ""), r.get("clue", "")])
            if _match(blob, keys):
                m_hits.append((f"M-{i:02d}", r.get("title", ""), r.get("tier", "")))
        band.append((label, a_hits, m_hits))
    return band


def render(academic_data, market_data):
    papers = academic_data["papers"]
    records = market_data["records"]
    band = build_cross_band(papers, records)
    today = datetime.date.today().isoformat()

    L = []
    L.append(f"# 双线交叉证据底稿：{TOPIC}")
    L.append("")
    L.append(f"> 生成：{today}（scripts/build_dual_line_evidence.py，无 LLM 调用）")
    L.append(f"> 学术线 {len(papers)} 条（DOI 级溯源，来源：{academic_data['source']}）")
    L.append(f"> 市场线 {len(records)} 条（URL+抓取日期+分级，抓取于 {market_data['fetch_date']}）")
    L.append("> 铁律：全部条目为代码抓取的真实结果；交叉带为关键词并置，非结论；裁决留白。")
    L.append("")

    L.append("## 〇、怎么读这份稿子")
    L.append("")
    L.append("| 字段 | 学术线（能不能做） | 市场线（值不值得做） |")
    L.append("|---|---|---|")
    L.append("| 证据编号 | A-01 起 | M-01 起 |")
    L.append("| 溯源标准 | DOI（无则期刊+年份+作者） | URL + 抓取日期 + A/B/C 分级 |")
    L.append("| 时间含义 | 论文发表年份 | 网页抓取日期 |")
    L.append("| 可信度标度 | 期刊/会议 + 被引次数 | A 官方/学术，B 主流媒体，C 社区参考 |")
    L.append("")

    L.append(f"## 一、学术线证据（共 {len(papers)} 条）")
    L.append("")
    L.append("| ID | 标题 | 年份 | 期刊/来源 | 被引 | DOI | 语 |")
    L.append("|---|---|---|---|---|---|---|")
    for i, p in enumerate(papers, 1):
        L.append("| " + " | ".join([
            f"A-{i:02d}",
            _cell(p.get("title"), 70),
            _cell(p.get("year"), 8) or "?",
            _cell(p.get("venue"), 40) or "?",
            _cell(p.get("citations"), 6) or "?",
            _cell(p.get("doi"), 34) or "（无）",
            _cell(p.get("lang"), 4) or "?",
        ]) + " |")
    L.append("")

    L.append(f"## 二、市场线证据（共 {len(records)} 条，URL 均抓取于 {market_data['fetch_date']}）")
    L.append("")
    L.append("| ID | 标题 | 分级 | URL | 功能线索 | 命中检索式 |")
    L.append("|---|---|---|---|---|---|")
    for i, r in enumerate(records, 1):
        L.append("| " + " | ".join([
            f"M-{i:02d}",
            _cell(r.get("title"), 40),
            _cell(r.get("tier"), 3),
            _cell(r.get("url"), 52),
            _cell(r.get("clue"), 18),
            _cell(r.get("query_hit"), 34),
        ]) + " |")
    L.append("")

    L.append("## 三、双线交叉带（代码按主题词并置，非结论）")
    L.append("")
    L.append("| 交叉主题词 | 学术线证据（ID+标题） | 市场线证据（ID+标题+分级） |")
    L.append("|---|---|---|")
    for label, a_hits, m_hits in band:
        a_cell = "<br>".join(f"{i} {_cell(t, 42)}" for i, t in a_hits) or "—"
        m_cell = "<br>".join(f"{i} {_cell(t, 30)}（{g}）" for i, t, g in m_hits) or "—"
        L.append(f"| {label} | {a_cell} | {m_cell} |")
    L.append("")

    only_a = [lb for lb, a, m in band if a and not m]
    only_m = [lb for lb, a, m in band if m and not a]
    both = [lb for lb, a, m in band if a and m]
    L.append("## 四、两线盲区对比（代码统计，解读留白）")
    L.append("")
    L.append(f"- 仅学术线命中（本次市场线 {len(records)} 条中未见对应词）：{'、'.join(only_a) or '无'}")
    L.append(f"- 仅市场线命中（本次学术线 {len(papers)} 条标题中未见对应词）：{'、'.join(only_m) or '无'}")
    L.append(f"- 双线均命中：{'、'.join(both) or '无'}")
    L.append("")
    L.append("> 注：两条线各自只有十余条级样本，「仅某一线命中」很可能只是该线本次检索覆盖不足")
    L.append("> （如市场线缺厂商/价格/国际标准类命中、学术线按标题匹配漏摘要层信息），")
    L.append("> 不构成「一边热一边冷」的结论——是否补强检索，见人工对照清单。")
    L.append("")

    L.append("## 五、人工对照清单（留白——「该不该我们做」由人判断）")
    L.append("")
    L.append("Agent 只呈现两线证据，不裁决。以下问题依赖内部信息与人的判断：")
    L.append("")
    L.append("- [ ] 在手数据与工况：现有监测数据能否复现「高水位诊断」场景？")
    L.append("- [ ] 预算与成本：声呐/机器人检测能力自建 vs 外采的边界在哪？")
    L.append("- [ ] 合规红线：数据安全/采购流程是否触碰红线？")
    L.append("- [ ] 战略聚焦：交叉带指向的空白点，是否与本单位研究方向重合？")
    L.append("- [ ] 证据补强：C 级线索（厂商软文/社区博客）是否需要一手核实？")
    L.append("- [ ] 检索补强：市场线是否需扩容（当前仅 13 条，缺厂商/价格/国际标准）？")
    L.append("")

    L.append("## 附录：检索过程溯源")
    L.append("")
    L.append("**学术线**（主题理解与检索式，来自代码 trace）：")
    L.append("")
    L.extend(academic_data.get("trace") or ["（无 trace）"])
    if academic_data.get("warn"):
        L.append(f"- 警告：{academic_data['warn']}")
    L.append("")
    L.append("**市场线**（多维检索式与分级，来自真实运行产出）：")
    L.append("")
    for q in market_data.get("queries", []):
        L.append(f"- `{q}`")
    ts = market_data.get("tier_stat", {})
    L.append("- 分级统计：" + "；".join(f"{t} 级 {n} 条" for t, n in sorted(ts.items())))
    L.append(f"- URL 抓取日期：{market_data['fetch_date']}（注入式 WebSearch 采集）")
    L.append("")
    return "\n".join(L)


def main():
    refresh = "--refresh" in sys.argv
    print("[1/3] 学术线：加载缓存或实时抓取（知网+OpenAlex+Crossref）...")
    academic = fetch_academic(refresh=refresh)
    print(f"  学术线 {len(academic['papers'])} 条（来源：{academic['source']}）")

    print("[2/3] 市场线：读取 TSV 产出并补全 snippet...")
    market = load_market()
    print(f"  市场线 {len(market['records'])} 条"
          f"（{'/'.join(f'{t}{n}' for t, n in sorted(market['tier_stat'].items()))}）")

    print("[3/3] 合流渲染（统一 schema + 交叉带 + 盲区 + 人工对照清单）...")
    doc = render(academic, market)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"\n===== 完成：{OUT_PATH}（{len(doc.splitlines())} 行）======")


if __name__ == "__main__":
    main()
