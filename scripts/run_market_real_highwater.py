"""排水管网高水位状态下的检测与诊断 —— 市场调研真实跑测（注入式）。

环境约束：本沙箱 Python 进程无出网权限（ddgs/DuckDuckGo 走 search.brave.com
超时），但 Agent 自带的 WebSearch 工具可出网。因此本脚本**只替换被网络拦截的
search_web 一步**，其余全部走项目真实代码（build_market_queries /
parse_web_results / classify_source / dedupe_records / build_market_table /
build_market_crew / sanitize_report_urls），以端到端验证市场调研功能。

真实检索结果来自 Agent WebSearch（2026-10-12），5 条多维检索式，24 条命中，
覆盖：高水位诊断方法论、智慧监测政府案例、CCTV/声呐技术对比、厂商与新品、
价格数据、国际标准（NASSCO/PACP）。
"""
import os
import re
import sys
import time
import dotenv

dotenv.load_dotenv(".env")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.tools.market_query import build_market_queries, DIMENSIONS
from src.tools.source_credibility import classify_source, dedupe_records, build_market_table
from src.crews.market_crew import build_market_crew
import src.tools.web_tool as web_tool
import src.main as main_mod

TOPIC = "排水管网高水位状态下的检测与诊断"

# ============ 真实检索结果（来自 Agent WebSearch，2026-10-12）============
REAL_HITS = [
    # —— 高水位诊断方法论（中文技术维度）——
    {"title": "管网高水位运行成因之诊断流程—智慧排水之乱弹(165)",
     "url": "http://www.thuenv.com/h-nd-236.html",
     "snippet": "清环智慧：基于在线监测的高水位管段运行成因分析工作流程——上游/末端/下游布点在线流量监测，"
                "结合纵断分析、特征曲线与模型模拟综合诊断成因；成因归为外水混入、管道自身缺陷、"
                "管理因素（来的多/走得慢/出不去/管得弱）；强调须用多普勒断面扫描式流量仪。"},
    {"title": "管网高水位运行成因之3个具体案例—智慧排水之乱弹(182)",
     "url": "http://m.thuwater.cn/nd.jsp?id=289&mid=5",
     "snippet": "清环智慧水务：3 个典型案例——泵站调度策略致高水位（降低启动水位 2.1 米后上游可全天非满管）、"
                "管道瓶颈逆坡、污水下游无出路；示范在线监测+局部模型在高水位成因诊断中的应用逻辑。"},
    {"title": "守护城市地下生命线：高水位管网检测技术应用实践-江西",
     "url": "http://www.autosubsea.com/newsinfo/8971316.html",
     "snippet": "遨拓深水装备：高水位管网检测方案在江西某市主干管应用——专用高水位管道检测机器人结合带水检测，"
                "搭载多波束成像声呐、管道扫描声呐与高清摄像头，声呐穿透浑水识别水下缺陷（精度毫米级），"
                "一次进管全面检测；检出破裂、起伏、错口、脱节、渗漏、树根、沉积等缺陷并分析外水入侵原因。"},

    # —— 智慧监测政府案例（监测诊断维度）——
    {"title": "嘀！您的城市血管超声科新晋医生已上线（昆山市人民政府）",
     "url": "https://www.ks.gov.cn/kss/swbmwj/202609/fb872a97b1bd415da9b7dd16f3c1a4dd.shtml",
     "snippet": "昆山市政府：一体化液位监测仪按分钟采集、24 小时不间断监测，水位飙升即时警报；"
                "通过液位与流量联动分析实现外水入侵溯源；支撑仪表盘式厂网协同调度。"},
    {"title": "青阳：智能监测设备助城区地下排水更畅通（青阳县政府）",
     "url": "https://ahqy.gov.cn/Content/show/783001.html",
     "snippet": "青阳县政府：城区安装 69 台智能监测设备（智能液位计+水位计+流量计）全覆盖重要节点；"
                "井内液位达井深 85% 自动触发报警，实时同步市城市生命线工程监测中心，24 小时不间断监测。"},
    {"title": "以数智之力绘就城市水治理新图景（中山市水务局）",
     "url": "https://water.zs.gov.cn/xxml/zwgk/gab/gzdt/content/post_2574870.html",
     "snippet": "中山市水务局：城区易涝点部署 101 个电子水尺、管网关键节点布设 340 余个液位计，"
                "接入气象雷达与水文潮位构建立体监测网；2025 年汛期支撑防汛应急 36 次，"
                "提前预判并告警 54 次污水冒溢风险。"},
    {"title": "番禺区通过液位计布下天罗地网破解满管难题（番禺区政府）",
     "url": "https://www.panyu.gov.cn/gkmlpt/content/10/10198/post_10198911.html",
     "snippet": "番禺区水务局：4207.6 公里排水管网布设 430 个液位监测点；2024 年上半年管网平均满管率"
                "67.93%（汛期降雨增 219.9% 及施工导水所致），经三轮回用调整与整改，2025 年 3 月满管率"
                "降至 6.65%，同比下降 86.76%；建立周期巡查+重点监控长效机制。"},
    {"title": "城市污水防线实现智慧升级（余姚市政府）",
     "url": "https://www.yy.gov.cn/col/col1229133441/art/2025/art_a1ffa770f16f4dd985def36f81863905.html",
     "snippet": "余姚市政府：市排水公司新增 100 台一体式井下液位计，与前期试点共 130 台组成覆盖网络，"
                "接入智慧排水平台，液位超阈值触发预警，构建实时感知-智能预警-高效处置闭环。"},

    # —— CCTV/声呐技术对比（技术路线维度）——
    {"title": "珠海市水务局：管道内窥检测技术应用（政府信息公开）",
     "url": "https://sswj.zhuhai.gov.cn/gkmlpt/content/3/3852/post_3852792.html",
     "snippet": "珠海市水务局：CCTV 检测适用管径 100-3000mm；QV 潜望镜适用 50-2000mm 初筛；"
                "多声呐检测利用超声波反射原理，适用于充满水或高水位管道，突破满水环境视障，"
                "DN600 以上可一次性识别 12 类缺陷，支持水下潜艇+水面快艇双模态。"},
    {"title": "满水管涵用声呐还是CCTV检测（施罗德工业集团）",
     "url": "https://www.srodcn.com/NewsStd_2322.html",
     "snippet": "施罗德工业集团：满水/高水位浑水环境下 CCTV 光学成像失效需降水清淤；声呐不受浊度影响、"
                "无需排空，适配满水高水位箱涵。产品：银鲨S450A水陆两栖检测机器人（DN500-6000mm，IP68）；"
                "银鲨1号S3831E动力声呐检测机器人（2.25MHz声呐头，量程0.25-6米，防水深度20米）。"},
    {"title": "非开挖管道检测技术之电视检测、声呐检测介绍（中科非开挖）",
     "url": "http://zkpipe.com/newsinfo.asp?Cla=31&thex=844",
     "snippet": "中科非开挖：CCTV 适用低水位全面检查，检测时应确保管道内水位不大于管径 20%；"
                "声呐只能检测水下物体（积泥、异物），对结构性缺陷检测有局限，不宜作为缺陷准确判定"
                "和修复依据；必要时两种技术配合使用。"},
    {"title": "市政清淤管道检测通常采用哪些第三方检测方法（微析实验室）",
     "url": "https://www.xkt58.com/hangyedongtai/460353.html",
     "snippet": "微析实验室：CCTV 爬行器检测准确率可达 95% 以上；管道充满积水或泥浆时视线受阻，"
                "声呐成为第三方核心选择——高频声波（金属管 1-5MHz/非金属 200-500kHz）生成二维三维轮廓；"
                "检测前设备校准、位置+画面同步记录、二次复核。"},
    {"title": "市排水管网的排水能力评估应采用哪些科学指标与检测方法（吉佳水务）",
     "url": "https://www.jijiacn.com/news/951",
     "snippet": "吉佳水务：按《城镇排水管道检测与评估技术规程》CJJ 181-2012 划分检测段（每段不超 100m）；"
                "声呐适用于充满水或高水位管道（大管径≥1000mm）；超声波流量计精度±2%/插入式±1%；"
                "压力式水位计精度±1mm；结合水力模型模拟综合评估。"},

    # —— 声呐技术原理与国际标准（英文技术维度）——
    {"title": "NASSCO Tech TIP: The Benefits of Sonar in Sewer Inspections (PDF)",
     "url": "https://nassco.org/wp-content/uploads/2025/09/NASSCO-Tech-TIP104Sep2025.2-1.pdf",
     "snippet": "NASSCO（美国国家下水道管线承包商协会，行业权威）：CCTV 是内检测基础但看不见水位线以下；"
                "声呐是其关键补充，适用于部分/完全满水管（surcharged）、大直径截流管（24 英寸以上）、"
                "CSO/SSO 评估；量化淤泥与杂物方量；数据可与 PACP 缺陷编码集成，形成统一标准化报告。"},
    {"title": "Sonar technology gives sewer inspections a clearer view below the waterline (Underground Infrastructure)",
     "url": "https://admin.undergroundinfrastructure.com/magazine/2025/september-2025-vol-80-no-9/tech-tips/sonar-technology-gives-sewer-inspections-a-clearer-view-below-the-waterline",
     "snippet": "Underground Infrastructure（国际非开挖行业媒体）：声呐补充 CCTV——呈现水位线以下淤积、"
                "水下障碍物与结构劣化；量化杂物方量以优化清淤计划；支持修复设计；可在低可见度或"
                "满管工况作业，减少检测延误；数据可整合 PACP 编码。"},
    {"title": "声呐检测（积高应急）",
     "url": "http://jogeel.com/gdjc/32.html",
     "snippet": "积高应急：声呐检测基于声波反射原理（100kHz~1MHz），适用于满水、高水位或严重淤积的"
                "排水管道与箱涵结构状态评估；侧扫声呐绘制内壁轮廓识别裂缝孔洞，剖面声呐测量底部沉积"
                "厚度并量化淤积率；漂浮载体或爬行机器人牵引。"},
    {"title": "声呐管道检测服务（北京京卫环环境科技）",
     "url": "http://www.bjjwh.net/sonar/sonar.html",
     "snippet": "京卫环：管道满水或水位较高且降水困难时，声呐可代替 CCTV 作为补充方案；优点是量化数据、"
                "对材质无要求、可长距离检测；缺点是成像为虚拟轮廓图而非实像，不宜作为结构性缺陷最终"
                "评判依据；服务满水污水管道/箱涵/河道暗渠检测与应急抢险。"},
    {"title": "最新市政管道智慧检测工艺（恒业信达建筑工程）",
     "url": "https://hyxdjz.com/show/748.html",
     "snippet": "恒业信达：3D 声呐检测系统（1800kHz 高频，360° 旋转扫描）适配市政满水/高水位/无法排空"
                "积水管道（≥DN800）；最小分辨率 5mm、断面测量精度±10mm、3D 建模还原度≥98%，"
                "可测算过流断面损失，弥补 CCTV 无法水下作业的短板。"},

    # —— 厂商/产品/价格（产品名维度）——
    {"title": "深圳市博铭维技术股份有限公司（官网）",
     "url": "http://www.bominwell.com/",
     "snippet": "博铭维（国家级专精特新小巨人，2014 年成立）：OTTER-S1 动力声呐检测机器人（全球首款"
                "自带动力声呐，满水工况精准检测）；OTTER-MINI 管道声呐漂浮筏（无动力，适用 DN200 以上"
                "高水位满水复杂管道，双频声呐）；DOLPHIN 系列管网检测机器人（最小进入 DN100-150）；"
                "Discovery 探路者模块化检测机器人；覆盖测检清修全生命周期。"},
    {"title": "暴雨退去，城市地下的思考正当其时（博铭维技术）",
     "url": "https://www.bwell-tec.com/news/now-that-the-torrential-rain-has-subsided-it-s-the-perfect-time-to-reflect-on-the-city-s-underground-infrastructure",
     "snippet": "博铭维技术：针对高水位、高淤积等复杂管道检测场景推出全地形管道检测机器人与动力声呐"
                "管道检测机器人；Discovery 探路者模块化设计可组合 6 种以上检测形态；Dasheng 胶囊机器人"
                "适配 DN200 及以上、水深不低于 70mm 带流速环境；Otter-Mini/S1 面向满水高水位检测。"},
    {"title": "2026年声呐检测机器人实力厂家解析：深圳博铭维技术（品搜网）",
     "url": "https://www.pinsowang.com/infonews/show.php?itemid=1529127",
     "snippet": "品搜网：博铭维以声呐检测机器人为核心拳头产品，专用于排水管道、箱涵等满水或高水位环境下"
                "内部结构成像与缺陷识别；中德双研发中心、研发团队超 70 人；参编 20 余项国家行业标准；"
                "产品覆盖超 15 个国家、服务超 4000 家客户。"},
    {"title": "水下B超来了！国产机器人多声呐透视排水管（人民日报全国党媒信息公共平台）",
     "url": "https://www.hubpd.com/detail/index.html?contentId=1729382256914609554&appKey=5fe15530cb852f00015ce437&key=5fe15530cb852f00015ce438&topId=&interruptId=0",
     "snippet": "人民日报党媒平台：2025 国际非开挖技术大会上，运通水务全球预发布高水位排水管网检测机器人"
                "浑水探测者1号——多声呐体系检测技术+高性能 ROV，历时 6 年、经大湾区 6 座城市 574 段管道"
                "实战打磨，突破传统 CCTV 与单声呐在满水高流速环境看不见、测不准的瓶颈；专家评价填补国内空白。"},
    {"title": "沧州泰鼎恒业试验仪器有限公司（百度爱采购）",
     "url": "https://b2b.baidu.com/land/25151d20d7fff0f3608344d4c646dcd8?fid=403116032",
     "snippet": "沧州泰鼎恒业：TDSNR-A 型声呐管道检测机器人设备，售价 198000 元/台，1 台起批；"
                "同类商品南京陆海海洋 LHJ 管道检测环扫声呐（适配爬行器/水下机器人）约 1000 元/套。"
                "数据更新时间 2026-09/10。"},
]

# ============ 只替换被网络拦截的检索步骤 ============
STOP = {"排水", "管网", "检测", "管道", "sewer", "pipeline", "pipe", "inspection",
        "monitoring", "diagnosis", "and", "the", "for", "with"}


def _tokens(query: str) -> list:
    q = (query or "").lower()
    en = [w for w in re.findall(r"[a-z]{3,}", q) if w not in STOP]
    zh = [w for w in re.findall(r"[\u4e00-\u9fff]{2,}", q)
          if w not in {"排水管网", "检测诊断", "排水管道"}]
    return en + zh


def _fake_search(query: str, max_results: int = 8) -> str:
    """返回真实检索结果（ddgs 文本格式），按查询词轻量命中排序。"""
    toks = _tokens(query)
    scored = []
    for h in REAL_HITS:
        blob = (h["title"] + " " + h["url"] + " " + h["snippet"]).lower()
        score = sum(1 for t in toks if t.lower() in blob)
        if score > 0:
            scored.append((score, h))
    scored.sort(key=lambda x: -x[0])
    picked = [h for _s, h in scored[:max_results]] or list(REAL_HITS[:max_results])
    seen, out = set(), []
    for h in picked:
        if h["url"] not in seen:
            seen.add(h["url"])
            out.append(h)
    lines = [f"- {h['title']}: {h['url']}\n  {h['snippet']}" for h in out]
    return "\n".join(lines) or "未返回结果。"


web_tool.search_web = _fake_search


def main():
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    print("[1/3] 拆解调研主题为多维检索式（调用项目真实 build_market_queries）...")
    mq = build_market_queries(TOPIC, max_queries=5)
    queries = mq["queries"]
    trace = [f"- 题型判定：{mq['题型']}（检索式来源：{mq['source']}）"]
    for q in queries:
        flag = " ⚠需核实产品名" if q.get("需核实") else ""
        trace.append(f"  - [{DIMENSIONS.get(q['维度'], q['维度'])}] `{q['查询']}`{flag}")
    print(f"  题型={mq['题型']}  来源={mq['source']}  检索式={len(queries)} 条")
    for q in queries:
        print(f"    [{DIMENSIONS.get(q['维度'], q['维度'])}] {q['查询']}")

    print(f"[2/3] 执行 {len(queries)} 条检索式并评估来源可信度（调用项目真实 classify_source）...")
    records = []
    for q in queries:
        raw_i = web_tool.search_web(q["查询"], 6)
        for it in main_mod.parse_web_results(raw_i):
            tier = classify_source(it["url"], it["title"], it["snippet"])
            if tier == "D":
                continue
            records.append({
                "title": it["title"], "url": it["url"], "snippet": it["snippet"],
                "tier": tier, "query_hit": f"{DIMENSIONS.get(q['维度'], q['维度'])}: {q['查询']}",
            })
        time.sleep(0.1)
    records = dedupe_records(records)

    ref_tsv = os.path.join(ROOT, "reports", "market_references.tsv")
    table_rows = build_market_table(records)
    tsv_lines = ["\t".join(r) for r in table_rows]
    with open(ref_tsv, "w", encoding="utf-8") as f:
        f.write("\n".join(tsv_lines) + "\n")

    tier_stat = {}
    for r in records:
        tier_stat[r["tier"]] = tier_stat.get(r["tier"], 0) + 1
    trace.append("  - 来源分级：" + "；".join(f"{t}级 {n} 条" for t, n in sorted(tier_stat.items()))
                 + "（D级内容农场已丢弃）")
    print(f"  真实来源 {len(records)} 条  A{tier_stat.get('A',0)}/B{tier_stat.get('B',0)}/C{tier_stat.get('C',0)}")

    ctx_lines = ["# 真实检索结果（来源含可信度分级，严禁编造产品名/链接）", "",
                 "| 产品/机构候选 | 来源标题 | 可信度 | 功能线索 | 命中检索式 |", "|---|---|---|---|---|"]
    for row in table_rows[1:]:
        ctx_lines.append("| " + " | ".join(row[:1] + row[1:2] + row[3:]) + " |")
    ctx_lines.append("")
    ctx_lines.append("【重要】可信度 A=官方/学术，B=主流媒体，C=社区参考。只有 A/B 级可作结论依据，"
                     "C 级需注明「社区反馈，待核实」。产品名均为候选，未经核实。")
    market_ctx = "\n".join(ctx_lines)

    print("[3/3] 运行 CrewAI 三角色分析（scout 不联网，仅基于已注入的真实结果）...")
    try:
        from crewai import LLM
        llm = LLM(
            model=f"openai/{os.getenv('OPENAI_MODEL', '')}",
            api_key=os.getenv("OPENAI_API_KEY", ""),
            temperature=0.2,
            base_url=os.getenv("OPENAI_BASE_URL") or None,
        )
    except Exception as e:
        print("  LLM 初始化失败:", e)
        return
    crew = build_market_crew(TOPIC, llm, tools=[], search_results=market_ctx)
    crew.kickoff()

    main_mod.sanitize_report_urls(
        os.path.join(ROOT, "reports", "market_report.md"),
        allowed_urls=[r["url"] for r in records],
    )

    report_path = os.path.join(ROOT, "reports", "market_report.md")
    trace_md = "\n".join(trace)
    tsv_block = ("## 检索过程溯源\n\n" + trace_md + "\n\n"
                 "## 来源清单（真实检索结果，系统按代码生成）\n\n```\n"
                 + "\n".join(tsv_lines) + "\n```\n")
    main_mod.append_grounded_refs(report_path, tsv_block)
    print(f"\n===== 完成：报告={report_path}，真实来源 {len(records)} 条 =====")


if __name__ == "__main__":
    main()
