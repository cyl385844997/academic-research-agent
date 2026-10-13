"""市场来源可信度分级与对比表生成。

【归档 2026-10-13】随市场调研线一并归档，暂不维护（A/B/C 分级逻辑仍有复用价值）。
详见 docs/scope-decision-2026-10-13.md。

为什么需要分级
--------------
文献检索有「北大核心白名单」这种硬标准，市场调研没有——
产品页、社区帖、技术博客的可靠程度差异极大，但形式上都是"网页"。
因此用**来源类型分级**替代白名单：

    A 级（可信）  官方站点/政府公告/标准/专利/学术论文
    B 级（较可信）主流科技与商业媒体、行业协会
    C 级（参考）  社区问答、论坛、个人博客
    D 级（存疑）  内容农场、无出处转载 —— **直接丢弃**

**可溯源约束**：本模块只对**真实检索返回的 URL** 做分级与抽取，
不生成任何产品信息。表内容来自 Web 工具的真实返回（见 AGENTS.md 可溯源铁律）。
"""
import re
from urllib.parse import urlparse

# ============ 来源分级规则 ============

# A 级：官方 / 权威
_TIER_A_DOMAIN = (
    ".gov.cn", ".gov", ".org.cn", "gov.cn", "mee.gov.cn", "ndrc.gov.cn",
    "most.gov.cn", "cnipa.gov.cn", "std.gov.cn", "sac.gov.cn",
    "iso.org", "who.int", "unep.org", "epa.gov", ".europa.eu",
    "wikipedia.org", "doi.org", "cnki.net", "wanfangdata.com",
    "springer.com", "sciencedirect.com", "nature.com", "wiley.com",
    "tandfonline.com", "ascelibrary.org", "iwaponline.com",
    "mdpi.com", "acs.org", "ieee.org",
)

# B 级：主流科技 / 商业媒体 / 行业研究 / 财经门户
_TIER_B_DOMAIN = (
    "36kr.com", "kr36.com", "tmtpost.com", "jiemian.com", "yicai.com",
    "thepaper.cn", "huxiu.com", "infoq.cn", "segmentfault.com",
    "techcrunch.com", "theverge.com", "wired.com", "arstechnica.com",
    "engadget.com", "gizmodo.com", "zdnet.com", "cnet.com",
    "forbes.com", "bloomberg.com", "reuters.com", "ft.com",
    "medium.com", "substack.com", "github.com",
    # 中文财经 / 产经门户
    "cet.com.cn", "cs.com.cn", "stcn.com", "cnstock.com", "eastmoney.com",
    # 行业 / 市场研究报告机构（管道检测机器人市场规模、CAGR 等）
    "pmarketresearch.com", "datainsightsmarket.com", "datainsightsreports.com",
    "grandviewresearch.com", "marketsandmarkets.com", "mordorintelligence.com",
    "fortunebusinessinsights.com", "globenewswire.com", "prnewswire.com",
    "businesswire.com",
)

# C 级：社区 / 论坛
_TIER_C_DOMAIN = (
    "zhihu.com", "jianshu.com", "csdn.net", "cnblogs.com",
    "oschina.net", "v2ex.com", "tieba.baidu.com", "douban.com",
    "reddit.com", "quora.com", "stackoverflow.com", "stackexchange.com",
    "x.com", "twitter.com", "linkedin.com", "facebook.com", "youtube.com",
)

# D 级特征：内容农场 / 无出处转载（一律丢弃）
_TIER_D_PATTERN = (
    "content-farm", "article-aggregator", "news-aggregator",
    "sohu.com/a/", "baijiahao.baidu.com", "toutiao.com", "163.com/dy/",
)

# 官方站点特征（URL 路径含官方栏目）
_OFFICIAL_PATH_HINT = (
    "/product", "/products", "/solution", "/solutions", "/about",
    "/company", "/news", "/press", "/blog", "/case", "/cases",
)


def classify_source(url: str, title: str = "", snippet: str = "") -> str:
    """判定来源可信度等级：A / B / C / D。

    Args:
        url: 来源链接
        title: 标题（辅助判断）
        snippet: 摘要（辅助判断）

    Returns:
        'A' | 'B' | 'C' | 'D'
    """
    if not url or not url.strip():
        return "D"
    low = url.lower()

    # D 级优先（内容农场特征）
    if any(p in low for p in _TIER_D_PATTERN):
        return "D"

    try:
        host = (urlparse(low).netloc or "").replace("www.", "")
    except Exception:  # noqa: BLE001
        host = low

    # A 级：政府/国际组织/学术出版商
    if any(d in host for d in _TIER_A_DOMAIN):
        return "A"
    # B 级：主流媒体
    if any(d in host for d in _TIER_B_DOMAIN):
        return "B"
    # C 级：社区
    if any(d in host for d in _TIER_C_DOMAIN):
        return "C"

    # 启发式①：路径含官方栏目且域名较短，可能是企业官网
    path = urlparse(low).path or ""
    if any(h in path for h in _OFFICIAL_PATH_HINT) and "." not in host.split("/")[0]:
        # 无子域的短域名 + 官方栏目 → 可能是官网
        return "B"

    # 启发式②：企业官网首页（根路径 / index）。
    # 不带子域的裸域名（如 bominwell.com、cctv-robot.com）且访问的是首页，
    # 通常是厂商官方站点，按 B 级（较可信）处理。
    # 排除带子域的聚合/社区（b2b.baidu.com、shop.xxx 等）与已知 C 级站点。
    _HOME_PATHS = ("", "/", "/index.html", "/index.htm", "/index.php", "/index.aspx")
    host_naked = host.split("/")[0]
    if path in _HOME_PATHS and host_naked.count(".") <= 1 and host_naked not in _TIER_C_DOMAIN:
        return "B"

    # 未知来源：默认 C（参考级），由报告标注"来源不明"
    return "C"


# ============ 产品/公司名抽取 ============

# 从标题中抽取候选产品名：书名号/引号/括号内内容，或英文首字母大写词组
_PRODUCT_PATTERNS = (
    re.compile(r"[《【\[]([^》】\]]{2,30})[》】\]]"),          # 《产品名》
    re.compile(r"[“\"]([^”\"]{2,30})[”\"]"),# “产品名”
    # 英文：连续的大写开头词组（Sewer Inspection Robot 需整体捕获）
    re.compile(
        r"\b((?:[A-Z][A-Za-z0-9\-]*(?:\s+(?:[A-Z][A-Za-z0-9\-]*|of|and|for|in|the)){0,4}))"
    ),
)

# 中文品牌/厂商名线索：出现在标题开头且后面跟产品描述
_VENDOR_LEAD = re.compile(r"^([一-龥A-Za-z]{2,10}?)(?=[\u4e00-\u9fff]?(?:发布|推出|亮相|亮相|研发|自主|全新|新一代))")

# 已知环境/水务领域厂商（用于精确匹配，避免误抽）
_KNOWN_VENDORS = (
    "海康威视", "海康机器人", "大华股份", "宇树科技", "优必选", "新松",
    "埃斯顿", "普渡科技", "中控技术", "和利时", "汇川技术", "雷赛智能",
    "西门子", "施耐德", "罗克韦尔", "ABB", "艾默生", "横河电机",
    "赛莱默", "哈希", "海德立", "中持股份", "碧水源", "清控环境",
    "北控水务", "首创环保", "重庆水务", "瀚蓝环境",
    # 排水管道检测机器人领域厂商（实测检索中高频出现，加入以提升抽取准确度）
    "博铭维", "中仪物联", "施罗德", "九泰", "快通", "新业环保", "东熙汇通",
    "固德超前", "华璟环保", "哈工智灵", "中岩科技",
)

# 功能关键词（用于抽产品定位）
_FEATURE_HINTS = (
    "巡检", "检测", "监测", "诊断", "运维", "调度", "优化", "控制",
    "仿真", "预测", "预警", "平台", "系统", "设备", "机器人",
    "inspection", "detection", "monitoring", "diagnosis", "control",
    "optimization", "simulation", "prediction", "platform", "system",
)


def extract_product_name(title: str, url: str = "") -> str:
    """从标题/URL 中抽取候选产品或公司名。

    优先级：
      1. 已知厂商名单精确匹配（最可靠）
      2. 《》/引号内内容
      3. 标题开头的厂商名（后接"发布/推出/亮相"等动词）
      4. 英文首字母大写词组
      5. URL 域名主干（兜底）

    抽取结果仅为**候选**，报告中需标注为"检索到的名称"，非经核实的产品名。
    """
    t = (title or "").strip()

    # 1) 已知厂商名单（取最长匹配，避免"海康"抢在"海康机器人"前面）
    best = ""
    for v in _KNOWN_VENDORS:
        if v in t and len(v) > len(best):
            best = v
    if best:
        return best

    # 2) 书名号 / 引号
    for pat in _PRODUCT_PATTERNS[:2]:
        m = pat.search(t)
        if m:
            cand = m.group(1).strip()
            if not re.search(r"(研究|分析|综述|进展|现状|探讨)$", cand):
                return cand

    # 3) 标题开头的厂商名 + 动词线索
    m = _VENDOR_LEAD.match(t)
    if m:
        cand = m.group(1).strip()
        if len(cand) >= 2:
            return cand

    # 4) 英文大写词组（过滤掉纯功能词的误匹配）
    m = _PRODUCT_PATTERNS[2].search(t)
    if m:
        cand = re.sub(r"\s+(of|and|for|in|the)$", "", m.group(1).strip())
        # 英文词组至少要有 2 个词，或长度足够，才像产品名
        if len(cand.split()) >= 2 or len(cand) >= 8:
            return cand

    # 5) 域名主干兜底
    try:
        host = (urlparse(url or "").netloc or "").replace("www.", "")
        stem = host.split(".")[0]
        if stem and len(stem) >= 3 and stem not in ("app", "docs", "blog", "m", "ai"):
            return stem
    except Exception:  # noqa: BLE001
        pass
    return ""


def extract_features(text: str, limit: int = 3) -> str:
    """从标题+摘要中抽取功能关键词，作为产品定位线索。"""
    low = (text or "").lower()
    hits = [h for h in _FEATURE_HINTS if h.lower() in low]
    return "、".join(hits[:limit])


# ============ 对比表生成 ============

# 来源表列名（保持与文献表一致的 TSV 风格，可直接粘 Excel）
MARKET_COLUMNS = ["产品/机构", "来源标题", "URL", "可信度", "功能线索", "命中检索式"]


def build_market_table(records: list) -> list:
    """由真实检索记录生成竞品对比表。

    Args:
        records: [{title, url, snippet, tier, query_hit}, ...]

    Returns:
        [list_of_lists] 首行为表头
    """
    rows = [MARKET_COLUMNS]
    for r in records:
        name = extract_product_name(r.get("title", ""), r.get("url", "")) or "（未识别）"
        feat = extract_features(f"{r.get('title','')} {r.get('snippet','')}")
        rows.append([
            name,
            (r.get("title") or "").strip(),
            (r.get("url") or "").strip(),
            r.get("tier", "?"),
            feat or "—",
            r.get("query_hit") or "—",
        ])
    return rows


def dedupe_records(records: list) -> list:
    """按 URL 去重（同一页面被多条检索式命中时保留可信度更高的）。"""
    best = {}
    order = []
    tier_rank = {"A": 0, "B": 1, "C": 2, "D": 3}
    for r in records:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        if url not in best:
            best[url] = r
            order.append(url)
        else:
            old = best[url]
            # 可信度更高者胜出；同级则保留更长的标题（信息更完整）
            if tier_rank.get(r.get("tier", "C"), 2) < tier_rank.get(old.get("tier", "C"), 2):
                best[url] = r
            elif (len(r.get("title", "")) > len(old.get("title", ""))) and \
                    r.get("tier") == old.get("tier"):
                best[url] = r
    return [best[u] for u in order]