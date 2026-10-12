"""双线合流（v0.2 输出层原型）：学术线 + 市场线检索结果并入同一个文本。

终态效果（用户需求）：「两个检索在同一个文本里」——学术线答「能不能做」，
市场线答「值不值得做」，统一证据 schema 并置；「该不该我们做」留白交人工
对照清单，Agent 不裁决。

本版落实的四项硬要求（对照上一版 3 处不达标）：
  ① 清晰区分且结构连贯：双区块详表（学术/市场各一张原生字段表），
     字段差异在〇节明示，两套溯源标度不互相填空；
  ② 排序逻辑显式：学术线按「相关度 → 年份降序 → 被引降序」，
     市场线按「分级 A→B→C → 命中维度」，排序键写进表头下方；
  ③ 不重复：交叉带只引证据 ID，不重复标题；每条证据按关键词优先级
     **唯一归入一个主桶**，避免同一篇在多个桶里重复计入；
  ④ 来源标识不截断：URL / DOI / 标题一律给全（截断的溯源标识等于失效）。

数据流（全部真实代码路径，本脚本无 LLM 调用）：
  学术线：src.main.fetch_literature_grounded() 实时抓取
          （知网 + Semantic Scholar/OpenAlex/Crossref），
          首次结果缓存 reports/academic_results.json（含溯源 trace）
  市场线：reports/market_references.tsv（上一次市场线真实运行的产出，
          含分级与命中检索式）；snippet 按 URL 从
          scripts/run_market_real_highwater.py 的 REAL_HITS
          （Agent WebSearch 真实结果）补全，合并缓存
          reports/market_records.json
  合流：  主桶互斥归类 → 排序 → 统一 schema 双表 → 交叉带（纯 ID）
          → 盲区对比 → 人工对照清单 → 检索过程溯源

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
MARKET_FETCH_DATE = "2026-10-12"  # 市场线 URL 抓取日期（注入式 WebSearch 采集）
ACADEMIC_CACHE = os.path.join(ROOT, "reports", "academic_results.json")
MARKET_CACHE = os.path.join(ROOT, "reports", "market_records.json")
OUT_PATH = os.path.join(ROOT, "reports", "dual_line_evidence.md")
TIER_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}

# 交叉带主题词（顺序即主桶优先级）：英文按小写子串匹配，中文按子串匹配。
# 学术线只匹配标题（源结构无摘要）；市场线匹配 标题+摘要+机构+功能线索。
CROSS_KEYS = [
    ("声呐检测", ["sonar", "声呐"]),
    ("水位/液位监测", ["water level", "水位", "液位"]),
    ("检测机器人/SLAM", ["robot", "slam", "机器人"]),
    ("CCTV/内窥", ["cctv", "内窥", "电视检测"]),
    ("满管/压力流", ["surcharge", "full pipe", "full-pipe", "满管", "压力流", "pressurized"]),
    ("外水入侵 I/I", ["infiltration", "inflow", "外水", "入侵", "渗漏"]),
    ("溢流 CSO/SSO", ["overflow", "冒溢", "溢流"]),
    ("淤积/沉积", ["sediment", "deposit", "淤积", "沉积", "积泥"]),
    ("诊断/预测/评估", ["predict", "forecast", "diagnos", "estim", "预测", "诊断", "评估"]),
    ("标准/规程", ["standard", "pacs", "nassco", "cjj", "标准", "规程"]),
]
UNBUCKETED = "未归类"


# ---------- 工具 ----------

def _num(value, default=0):
    """年份/被引转整数，'?'/None/'' 一律降为 default（排序时沉底）。"""
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


def _cell(text, limit=0):
    """表格单元格净化：压换行、转义竖线；limit=0 表示不截断（溯源标识必须给全）。"""
    t = " ".join(str(text or "").split()).replace("|", "/")
    if limit and len(t) > limit:
        return t[: limit - 1] + "…"
    return t


def _match(text, keys):
    t = str(text or "").lower()
    return any(k in t for k in keys)


def assign_bucket(text):
    """唯一主桶：按 CROSS_KEYS 顺序首个命中即归入（互斥，防重复计入）。"""
    for label, keys in CROSS_KEYS:
        if _match(text, keys):
            return label
    return UNBUCKETED


def relevance(text):
    """相关度 = 标题命中主题词的总次数（越多越贴近主题）。"""
    t = str(text or "").lower()
    return sum(1 for _label, keys in CROSS_KEYS for k in keys if k in t)


# ---------- 取数 ----------

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
    slim = [{"title": r["title"], "url": r["url"], "snippet": r["snippet"],
             "tier": r["tier"], "query_hit": r["query_hit"]} for r in records]
    slim = dedupe_records(slim)
    by_url = {r["url"]: r for r in records}
    records = [{**by_url.get(r["url"], {}),
                **{k: r[k] for k in ("title", "url", "snippet", "tier", "query_hit")}}
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


# ---------- 归类 + 排序 ----------

def prepare_academic(papers):
    """学术线：算主桶与相关度，按「相关度降序→年份降序→被引降序」排序。"""
    rows = []
    for p in papers:
        title = p.get("title", "")
        rows.append({
            "title": title,
            "year": _num(p.get("year")),
            "year_raw": p.get("year") or "?",
            "venue": p.get("venue") or "?",
            "citations": _num(p.get("citations")),
            "citations_raw": p.get("citations") or "?",
            "doi": p.get("doi") or "",
            "lang": p.get("lang") or "?",
            "bucket": assign_bucket(title),
            "rel": relevance(title),
        })
    rows.sort(key=lambda r: (-r["rel"], -r["year"], -r["citations"]))
    for i, r in enumerate(rows, 1):
        r["id"] = f"A-{i:02d}"
    return rows


def prepare_market(records, query_order):
    """市场线：算主桶，按「分级 A→B→C → 命中维度 → 标题」排序。"""
    dim_rank = {q.split(":")[0].strip(): i for i, q in enumerate(query_order)}
    rows = []
    for r in records:
        blob = " ".join([r.get("title", ""), r.get("snippet", ""),
                         r.get("org", ""), r.get("clue", "")])
        dim = r.get("query_hit", "").split(":")[0].strip()
        rows.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "tier": r.get("tier", ""),
            "org": r.get("org", ""),
            "clue": r.get("clue", ""),
            "query_hit": r.get("query_hit", ""),
            "dim": dim,
            "bucket": assign_bucket(blob),
        })
    rows.sort(key=lambda r: (TIER_ORDER.get(r["tier"], 9),
                             dim_rank.get(r["dim"], 99),
                             r["title"]))
    for i, r in enumerate(rows, 1):
        r["id"] = f"M-{i:02d}"
    return rows


def build_cross_band(academic, market):
    """交叉带：按主桶聚合，每条证据只出现一次（主桶互斥的保证）。

    「未归类」是残差桶（不匹配任何主题词），不是主题词，故不进交叉带，
    只在第四节报计数——避免一个几十个 ID 的单元格把主题带淹没。
    """
    a_by, m_by = {}, {}
    for r in academic:
        a_by.setdefault(r["bucket"], []).append(r["id"])
    for r in market:
        m_by.setdefault(r["bucket"], []).append(r["id"])
    band = [(label, a_by.get(label, []), m_by.get(label, []))
            for label, _keys in CROSS_KEYS]
    residual = (len(a_by.get(UNBUCKETED, [])), len(m_by.get(UNBUCKETED, [])))
    return band, residual


# ---------- 渲染 ----------

def render(academic_data, market_data):
    query_order = market_data.get("queries", [])
    academic = prepare_academic(academic_data["papers"])
    market = prepare_market(market_data["records"], query_order)
    band, residual = build_cross_band(academic, market)
    today = datetime.date.today().isoformat()

    L = []
    L.append(f"# 双线交叉证据底稿：{TOPIC}")
    L.append("")
    L.append(f"> 生成：{today}（scripts/build_dual_line_evidence.py，无 LLM 调用）")
    L.append(f"> 学术线 {len(academic)} 条（DOI 级溯源，来源：{academic_data['source']}）｜"
             f"市场线 {len(market)} 条（URL+抓取日期+分级，抓取于 {market_data['fetch_date']}）")
    L.append("> 铁律：全部条目为代码抓取的真实结果；交叉带只并置 ID、不下结论；裁决留白。")
    L.append("")

    L.append("## 〇、怎么读这份稿子")
    L.append("")
    L.append("| 字段 | 学术线（能不能做） | 市场线（值不值得做） |")
    L.append("|---|---|---|")
    L.append("| 证据编号 | A-01 起（按排序后顺序编号） | M-01 起（按排序后顺序编号） |")
    L.append("| 溯源标准 | DOI，无 DOI 则留空并保留期刊+年份 | 完整 URL + 抓取日期 + A/B/C 分级 |")
    L.append("| 时间含义 | 论文发表年份 | 网页抓取日期 |")
    L.append("| 可信度标度 | 期刊/会议 + 被引次数（不套用 A/B/C） | A 官方/学术，B 主流媒体，C 社区参考 |")
    L.append("| 主桶 | 按关键词优先级唯一归类，每条只进一个桶 | 同左 |")
    L.append("")
    L.append("**排序键**（表内顺序即此顺序，可复现）：")
    L.append("")
    L.append("- 学术线：相关度（标题命中主题词次数）降序 → 发表年份降序 → 被引次数降序")
    L.append("- 市场线：来源分级 A→B→C → 命中维度（通用中文→通用英文→技术路线→产品名→应用案例）")
    L.append("")
    L.append("**主桶优先级**（首个命中即归入，互斥）："
             + " → ".join(label for label, _ in CROSS_KEYS) + f" → {UNBUCKETED}")
    L.append("")
    L.append("> 说明：相关度低的真实结果**不删除**（如 surcharge 一词多义命中的心理学/经济学论文），"
             "只按排序压到表尾；交叉带按主桶归集，故每条证据只出现一次。")
    L.append("")

    L.append(f"## 一、学术线证据（共 {len(academic)} 条）")
    L.append("")
    L.append("> 排序：相关度降序 → 年份降序 → 被引降序。"
             "学术线按 source 顺序合并去重，源结构未逐条记录命中检索式，检索式清单见附录。")
    L.append("")
    L.append("| ID | 标题 | 年份 | 期刊/来源 | 被引 | DOI | 语 | 主桶 | 相关度 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in academic:
        L.append("| " + " | ".join([
            r["id"],
            _cell(r["title"]),
            str(r["year_raw"]),
            _cell(r["venue"]),
            str(r["citations_raw"]),
            _cell(r["doi"]) or "（无）",
            _cell(r["lang"]),
            r["bucket"],
            str(r["rel"]),
        ]) + " |")
    L.append("")

    L.append(f"## 二、市场线证据（共 {len(market)} 条，URL 均抓取于 {market_data['fetch_date']}）")
    L.append("")
    L.append("> 排序：来源分级 A→B→C → 命中维度。"
             "C 级为社区/商业平台线索，仅可作旁证，引用时须标注「待核实」。")
    L.append("")
    L.append("| ID | 标题 | 分级 | URL | 机构/平台 | 功能线索 | 命中检索式 | 主桶 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in market:
        L.append("| " + " | ".join([
            r["id"],
            _cell(r["title"]),
            _cell(r["tier"]),
            _cell(r["url"]),
            _cell(r["org"]),
            _cell(r["clue"]),
            _cell(r["query_hit"]),
            r["bucket"],
        ]) + " |")
    L.append("")

    L.append("## 三、双线交叉带（只并置证据 ID，标题见前两节，不重复）")
    L.append("")
    L.append("| 主题词（主桶） | 学术线 ID（数量） | 市场线 ID（数量） |")
    L.append("|---|---|---|")
    for label, a_ids, m_ids in band:
        a_cell = "、".join(a_ids) if a_ids else "—"
        m_cell = "、".join(m_ids) if m_ids else "—"
        L.append(f"| {label} | {a_cell}（{len(a_ids)}） | {m_cell}（{len(m_ids)}） |")
    L.append("")

    only_a = [(lb, a) for lb, a, m in band if a and not m]
    only_m = [(lb, m) for lb, a, m in band if m and not a]
    both = [lb for lb, a, m in band if a and m]
    neither = [lb for lb, a, m in band if not a and not m]
    L.append("## 四、两线盲区对比（代码统计，解读留白）")
    L.append("")
    if only_a:
        L.append("- 仅学术线命中："
                 + "；".join(f"{lb}（学术 {len(a)} 条）" for lb, a in only_a))
    else:
        L.append("- 仅学术线命中：无")
    if only_m:
        L.append("- 仅市场线命中："
                 + "；".join(f"{lb}（市场 {len(m)} 条）" for lb, m in only_m))
    else:
        L.append("- 仅市场线命中：无")
    L.append(f"- 双线均命中：{'、'.join(both) or '无'}")
    if neither:
        L.append(f"- 双线均未命中：{'、'.join(neither) or '无'}")
    L.append(f"- 未归类（不匹配任何主题词，故不进交叉带，主桶列已标注）："
             f"学术 {residual[0]} 条 / 市场 {residual[1]} 条")
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
    L.append("- [ ] 检索补强：市场线是否需扩容（当前仅 "
             f"{len(market)} 条，缺厂商/价格/国际标准）？")
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

    print("[3/3] 主桶互斥归类 → 排序 → 双表 + 交叉带 + 盲区 + 人工清单...")
    doc = render(academic, market)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"\n===== 完成：{OUT_PATH}（{len(doc.splitlines())} 行）======")


if __name__ == "__main__":
    main()