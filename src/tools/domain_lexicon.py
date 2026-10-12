"""领域术语词典：中文概念 → 知网检索词 + 英文等价术语。

为什么需要它
------------
中文工程术语与英文文献术语**不是一一对应**，字面直译会失真：

    高水位   → 字面 high water level，但英文文献的标准概念是
               infiltration/inflow (I/I) / high groundwater
    雨污混错接 → 字面 rain-sewage mixing，但英文用
               cross-connection / illicit connection / misconnection
    提标改造 → 字面 standard-raising，但英文用
               WWTP upgrading / retrofit

本词典为**人工核定的确定性映射**，零幻觉，优先于 LLM 解析使用。

数据组织
--------
每个条目：
    {
        "cnki": ["知网检索词", ...],      # 可用于拼装 SU= 检索式
        "en":   ["英文等价术语", ...],    # 国际期刊通用表述
        "note": "说明（可选）",
    }

维护约定
--------
1. 新增条目必须确认英文术语是该领域国际期刊**真实用过**的词；
2. LLM 解析成功且实测召回良好的组合，可提示用户收录，但**不自动收录**，
   避免错误被固化；
3. 英文词一律小写（检索时统一处理大小写）。
"""

# ============ 侧流耦合 / 生物除磷 / 溢流 ============
SIDE_STREAM = {
    "侧流生物除磷": {
        "cnki": ["侧流", "生物除磷", "侧流生物除磷", "强化生物除磷"],
        "en": [
            "side-stream enhanced biological phosphorus removal",
            "sidestream EBPR",
            "S2EBPR",
            "side-stream reactor phosphorus removal",
        ],
        "note": "你课题2.2的核心工艺；英文侧常用 S2EBPR 缩写",
    },
    "侧流": {
        "cnki": ["侧流", "侧流反应器", "侧流发酵"],
        "en": ["side-stream reactor", "side stream", "sidestream fermentation"],
    },
    "生物除磷": {
        "cnki": ["生物除磷", "除磷", "强化生物除磷"],
        "en": ["biological phosphorus removal", "EBPR", "enhanced biological phosphorus removal"],
    },
    "EBPR": {
        "cnki": ["EBPR", "强化生物除磷"],
        "en": ["EBPR", "enhanced biological phosphorus removal"],
    },
    "发酵": {
        "cnki": ["厌氧发酵", "发酵", "污泥发酵"],
        "en": ["anaerobic fermentation", "sludge fermentation", "VFA production"],
    },
    "挥发性脂肪酸": {
        "cnki": ["挥发性脂肪酸", "VFA", "易降解有机物"],
        "en": ["volatile fatty acids", "VFA", "readily biodegradable COD"],
    },
}

# ============ 雨季溢流 / 冲击负荷 ============
WET_WEATHER = {
    "雨季溢流": {
        "cnki": ["雨季溢流", "合流制溢流", "溢流"],
        "en": [
            "combined sewer overflow",
            "CSO",
            "wet weather overflow",
            "stormwater overflow",
        ],
        "note": "英文标准说法是 CSO，直译 rainy season overflow 命中率低",
    },
    "合流制": {
        "cnki": ["合流制", "合流制排水系统"],
        "en": ["combined sewer system", "combined sewer"],
    },
    "分流制": {
        "cnki": ["分流制", "分流制排水系统"],
        "en": ["separated sewer system", "dual drainage system", "storm sewer"],
    },
    "溢流": {
        "cnki": ["溢流", "溢流污染", "合流制溢流"],
        "en": ["overflow", "combined sewer overflow", "CSO"],
    },
    "雨污混错接": {
        "cnki": ["雨污混错接", "错接", "混接"],
        "en": [
            "cross-connection",
            "illicit connection",
            "misconnection",
            "sewer lateral misconnection",
        ],
        "note": "字面 rain-sewage mixing 在英文库几乎搜不到",
    },
    "入流入渗": {
        "cnki": ["入流入渗", "地下水入渗", "外水入渗", "入渗评估"],
        "en": [
            "infiltration and inflow",
            "I/I",
            "infiltration and inflow assessment",
            "I/I assessment",
            "inflow",
            "groundwater infiltration",
        ],
        "note": "外水问题需配套流量监测/地下水水位监测/降雨监测；独立于常规管道状况评估",
    },
    # 【用户纠正】"高水位"有两种语义，原先混在一条里是错的：
    #   (a) 管网运行水位偏高（满管流/溢流风险）—— 水力运行状态问题
    #   (b) 地下水/河水入渗导致的水位升高 —— 外水问题（见「入流入渗」/「外水」）
    # 二者技术路线完全不同，故拆为独立概念。
    "高水位": {
        "cnki": ["高水位", "水位升高", "满管", "满管流"],
        "en": [
            "high water level",
            "full pipe flow",
            "surcharge",
        ],
        "note": "指管网运行水位偏高（满管流/溢流风险）；若指地下水入渗请用「入流入渗」或「外水」",
    },
    "满管度": {
        "cnki": ["满管度", "满管流", "充满度"],
        "en": [
            "pipe fullness",
            "h/D ratio",
            "relative depth",
            "filling ratio",
        ],
        "note": "英文文献描述管网运行状态的标准指标，常与高水位/溢流风险同时出现",
    },
    "冲击负荷": {
        "cnki": ["冲击负荷", "负荷冲击", "瞬时负荷"],
        "en": ["hydraulic shock", "load fluctuation", "transient loading"],
    },
    "短程脱氮": {
        "cnki": ["短程脱氮", "短程硝化反硝化", "部分硝化"],
        "en": ["shortcut nitrogen removal", "partial nitritation", "A-B stage"],
    },
    "同步硝化反硝化": {
        "cnki": ["同步硝化反硝化", "SND", "同步反硝化"],
        "en": [
            "simultaneous nitrification and denitrification",
            "SND",
            "simultaneous nitrification denitrification",
        ],
        "note": "节能降碳背景下的高频概念，与短程脱氮(SBR/PN)是不同技术路线",
    },
    "厌氧氨氧化": {
        "cnki": ["厌氧氨氧化", "Anammox", "厌氧氨氧化工艺"],
        "en": [
            "anammox",
            "anaerobic ammonium oxidation",
            "partial nitritation anammox",
            "PN/A",
        ],
        "note": "低碳氮比/能源自给方向的必备术语，常与部分硝化组成 PN/A",
    },
    "部分硝化": {
        "cnki": ["部分硝化", "PN", "亚硝化"],
        "en": ["partial nitritation", "partial nitrification", "PN"],
    },
}

# ============ TN / 脱氮 ============
NITROGEN = {
    "总氮": {
        "cnki": ["总氮", "TN", "出水总氮"],
        "en": ["total nitrogen", "TN", "effluent TN"],
    },
    "TN": {
        "cnki": ["总氮", "TN"],
        "en": ["total nitrogen", "TN"],
    },
    "脱氮": {
        "cnki": ["脱氮", "生物脱氮", "硝化反硝化"],
        "en": ["nitrogen removal", "nitrification denitrification", "biological nitrogen removal"],
    },
    "氨氮": {
        "cnki": ["氨氮", "NH3-N", "出水氨氮"],
        "en": ["ammonia", "ammonia nitrogen", "NH4-N", "effluent ammonia"],
    },
    "总磷": {
        "cnki": ["总磷", "TP", "出水总磷"],
        "en": ["total phosphorus", "TP", "effluent TP"],
    },
    "硝化": {
        "cnki": ["硝化", "硝化菌", "氨氧化"],
        "en": ["nitrification", "ammonia oxidation", "nitrifier"],
    },
    "反硝化": {
        "cnki": ["反硝化", "反硝化菌"],
        "en": ["denitrification", "denitrifier"],
    },
    "内回流": {
        "cnki": ["内回流", "硝化液回流"],
        "en": ["internal recycle", "internal recirculation", "nitrate recycle"],
    },
    "外回流": {
        "cnki": ["外回流", "污泥回流", "回流比"],
        "en": ["external recycle", "sludge recycle", "recycle ratio"],
    },
    "回流比": {
        "cnki": ["回流比", "污泥回流比", "内回流比"],
        "en": ["recycle ratio", "internal recycle ratio", "R ratio"],
    },
    "安全裕度": {
        "cnki": ["安全裕度", "裕度", "出水达标裕度"],
        "en": ["safety margin", "compliance margin", "robustness margin"],
    },
    "进水负荷波动": {
        "cnki": ["进水波动", "负荷波动", "水质波动"],
        "en": ["influent fluctuation", "loading variation", "influent variability"],
    },
}

# ============ 能效 / 风机水泵 ============
ENERGY = {
    "能效": {
        "cnki": ["能效", "能源效率", "节能"],
        "en": ["energy efficiency", "energy consumption", "specific energy consumption"],
    },
    "吨水电耗": {
        "cnki": ["吨水电耗", "单位电耗", "用电量", "kWh/m3"],
        "en": ["specific energy consumption", "power consumption per unit volume", "kWh/m3"],
    },
    "风机": {
        "cnki": ["风机", "鼓风机", "曝气风机"],
        "en": ["blower", "air blower", "aeration blower"],
    },
    "水泵": {
        "cnki": ["水泵", "提升泵", "污水泵"],
        "en": ["pump", "wastewater pump", "lift pump"],
    },
    "曝气": {
        "cnki": ["曝气", "曝气量", "鼓风曝气"],
        "en": ["aeration", "aeration rate", "air supply"],
    },
    "变频": {
        "cnki": ["变频", "变频器", "调速"],
        "en": ["variable frequency drive", "VFD", "speed control"],
    },
    "泵系统": {
        "cnki": ["泵系统", "水泵系统", "提升系统"],
        "en": ["pumping system", "pump system"],
    },
    "管网水力": {
        "cnki": ["管网水力", "水力特性", "水头损失", "SWMM", "水力模型"],
        "en": [
            "pipe hydraulics",
            "SWMM",
            "hydraulic modeling",
            "sewer hydraulic model",
        ],
        "note": "英文溢流分析/管网诊断文献实际检索词常用 SWMM 或 hydraulic modeling，"
        "而非仅 pipe hydraulics",
    },
}

# ============ 排水管网诊断 ============
SEWER = {
    "排水管网": {
        "cnki": ["排水管网", "污水管网", "市政管网"],
        "en": ["sewer network", "drainage network", "sewerage network", "wastewater network"],
    },
    "排水管道": {
        "cnki": ["排水管道", "管道", "管线"],
        "en": ["sewer pipe", "pipeline", "conduit"],
    },
    "管网诊断": {
        "cnki": ["管网诊断", "诊断", "状况评估", "入渗评估"],
        "en": [
            "sewer condition assessment",
            "sewer diagnosis",
            "pipeline condition assessment",
            "sewer inspection",
            # I/I 评估是独立技术方向（流量/地下水水位/降雨监测系统方法），
            # 用户建议补入，与常规管道状况评估并列
            "infiltration and inflow assessment",
            "I/I assessment",
        ],
        "note": "常规状况评估（CCTV/缺陷检测）与 I/I 评估是两条独立技术路线，可并列检索",
    },
    "非开挖检测": {
        "cnki": ["非开挖检测", " CCTV检测", "管道检测"],
        "en": [
            "trenchless inspection",
            "CCTV inspection",
            "pipeline inspection",
            "closed-circuit television inspection",
        ],
    },
    "缺陷检测": {
        "cnki": ["缺陷检测", "缺陷识别", "病害检测"],
        "en": ["defect detection", "defect classification", "pipeline defect"],
    },
    "管道检测": {
        "cnki": ["管道检测", "管道评估", "状况检测"],
        "en": ["pipeline inspection", "pipe condition assessment"],
    },
    "CCTV": {
        "cnki": ["CCTV检测", "闭路电视检测", "管道CCTV"],
        "en": ["CCTV inspection", "closed circuit television", "TFTIS"],
    },
    "机器人检测": {
        "cnki": ["机器人检测", "爬管机器人", "管道机器人"],
        "en": ["pipe robot", "inspection robot", "crawler robot", "in-pipe robot"],
    },
    "DMA": {
        "cnki": ["DMA", "分区排水", "DMA分区"],
        "en": ["district metered area", "DMA", "district metering"],
    },
    "外水": {
        "cnki": ["外水", "地下水入渗", "外水入渗", "入渗评估"],
        "en": [
            "infiltration and inflow",
            "I/I",
            "infiltration and inflow assessment",
            "I/I assessment",
            "inflow",
            "groundwater infiltration",
            "extraneous water",
        ],
        "note": "「高水位」若指地下水入渗导致，应使用本条目而非「高水位」条目",
    },
    "同位素": {
        "cnki": ["同位素", "氢氧稳定同位素", "稳定同位素"],
        "en": ["stable isotope", "hydrogen oxygen isotope", "isotope tracing"],
    },
    "积水": {
        "cnki": ["积水", "内涝", "城市内涝"],
        "en": ["waterlogging", "urban flooding", "flooding event"],
    },
    "内涝": {
        "cnki": ["内涝", "城市内涝", "积水内涝"],
        "en": ["waterlogging", "urban flooding", "pluvial flooding"],
    },
}

# ============ 污水厂主体工艺 ============
WWTP = {
    "污水处理厂": {
        "cnki": ["污水处理厂", "污水厂", "污水处理"],
        "en": ["wastewater treatment plant", "WWTP", "sewage treatment plant"],
    },
    "污水厂": {
        "cnki": ["污水处理厂", "污水厂"],
        "en": ["wastewater treatment plant", "WWTP"],
    },
    "活性污泥": {
        "cnki": ["活性污泥", "活性污泥法", "污泥龄"],
        "en": ["activated sludge", "activated sludge process", "SRT"],
    },
    "污泥龄": {
        "cnki": ["污泥龄", "SRT", "停留时间"],
        "en": ["sludge retention time", "SRT", "solids retention time"],
    },
    "A2O": {
        "cnki": ["A2O", "AAO", "厌氧好氧氧化沟"],
        "en": ["A2O process", "A^2/O", "anaerobic anoxic oxic process"],
    },
    "A/O": {
        "cnki": ["A/O", "厌氧好氧工艺"],
        "en": ["A/O process", "anaerobic oxic process"],
    },
    "MBR": {
        "cnki": ["MBR", "膜生物反应器"],
        "en": ["membrane bioreactor", "MBR"],
    },
    "提标改造": {
        "cnki": ["提标改造", "提标", "改造工程"],
        "en": ["upgrading", "retrofitting", "WWTP upgrade"],
        "note": "字面 standard-raising 在英文库无结果",
    },
    "深度处理": {
        "cnki": ["深度处理", "深度净化", "三级处理"],
        "en": ["advanced treatment", "tertiary treatment", "polishing"],
    },
    "再生水": {
        "cnki": ["再生水", "回用水", "再生水处理"],
        "en": ["water reuse", "reclaimed water", "regenerated water", "water reclamation"],
    },
    "初沉池": {
        "cnki": ["初沉池", "初次沉淀池"],
        "en": ["primary sedimentation tank", "primary clarifier"],
    },
    "二沉池": {
        "cnki": ["二沉池", "二次沉淀池", "沉淀池"],
        "en": ["secondary sedimentation tank", "secondary clarifier"],
    },
}


# ============ 合并导出 ============
def _merge(*groups):
    out = {}
    for g in groups:
        for k, v in g.items():
            out[k] = v
    return out


LEXICON = _merge(
    SIDE_STREAM,
    WET_WEATHER,
    NITROGEN,
    ENERGY,
    SEWER,
    WWTP,
)

# 分组导出，便于展示与维护
LEXICON_GROUPS = {
    "侧流耦合·生物除磷": SIDE_STREAM,
    "雨季溢流·合流制": WET_WEATHER,
    "TN·脱氮": NITROGEN,
    "能效·风机水泵": ENERGY,
    "排水管网诊断": SEWER,
    "污水厂工艺": WWTP,
}

# 反向索引：英文术语 → 中文概念（用于校验检索词是否跑偏）
EN_TO_CN = {}
for cn, entry in LEXICON.items():
    for en in entry.get("en", []):
        EN_TO_CN.setdefault(en.lower(), cn)


def lookup(text: str):
    """在词典中查找与给定文本匹配的概念。

    采用**最长优先**匹配，避免「侧流」先于「侧流生物除磷」命中而丢掉更具体的概念。

    支持两类输入：
      - 中文概念名（如「高水位」「同步硝化反硝化」）
      - 英文术语（如「SWMM」「anammox」「EBPR」）——按词典的 en 字段反查

    Args:
        text: 待匹配文本，如「高水位排水管网诊断」或「SWMM 溢流分析」

    Returns:
        命中的概念列表（长概念在前），未命中返回 []
    """
    hits = []
    raw = text or ""
    low = raw.lower()

    for cn in LEXICON:
        if cn in raw:
            hits.append(cn)
            continue
        # 英文反查：概念名本身是英文缩写，或其 en 术语出现在文本中
        entry = LEXICON.get(cn, {})
        if cn.isascii() and len(cn) >= 2 and cn.lower() in low:
            hits.append(cn)
            continue
        for en in entry.get("en", []):
            # 只用较长的英文术语反查，避免 short词误命中（如 "I/I"、"CN"）
            if len(en) >= 4 and en.lower() in low:
                hits.append(cn)
                break

    # 去重并按长度降序（更具体的概念优先）
    seen, ordered = set(), []
    for c in sorted(hits, key=len, reverse=True):
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def covered_ratio(text: str, english_words) -> float:
    """计算英文检索词被词典覆盖的比例。

    用于校验 LLM 生成的英文检索式是否离谱——覆盖度过低说明可能生造了术语。

    Args:
        text: 原始中文主题
        english_words: 英文检索词列表

    Returns:
        0.0 ~ 1.0 的覆盖率
    """
    import re

    words = set()
    for q in english_words:
        words |= set(w.lower() for w in re.findall(r"[a-z]{4,}", (q or "").lower()))
    if not words:
        return 0.0
    # 词典英文术语里出现过的词（含短语内的词）
    dict_words = set()
    for entry in LEXICON.values():
        for en in entry.get("en", []):
            dict_words |= set(w.lower() for w in en.split())
    hit = sum(1 for w in words if w in dict_words)
    return hit / len(words)