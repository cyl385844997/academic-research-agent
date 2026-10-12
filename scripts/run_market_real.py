"""排水管道检测机器人 —— 市场调研真实跑测。

环境约束：本沙箱 Python 进程无出网权限（ddgs / DuckDuckGo 超时），
但项目的 LLM 端点可达，且 Agent 自带的 WebSearch 工具可出网并已取到
真实 2026 检索结果。因此本脚本**只替换被网络拦截的 search_web 一步**，
其余全部走项目真实代码（build_market_queries / classify_source /
dedupe_records / build_market_table / build_market_crew / append_grounded_refs），
以端到端验证市场调研功能。

真实检索结果来自 Agent WebSearch（2026-10-12），已去重、分维度整理。
"""
import os
import sys
import json
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

TOPIC = "排水管道检测机器人"

# ============ 真实检索结果（来自 Agent WebSearch，2026-10-12）============
# 每条：title / url / snippet。覆盖厂商、国际竞品、市场报告、技术路线、政策价格。
REAL_HITS = [
    # —— 厂商/公司（中文产品名维度）——
    {"title": "深圳市博铭维技术股份有限公司 | 管道检测修复机器人专家",
     "url": "http://www.bominwell.com/",
     "snippet": "国家级专精特新小巨人企业，DOLPHIN系列管网检测机器人、OTTER动力声呐检测机器人、"
                "DASHENG胶囊机器人、穿山甲管道切割机器人，覆盖测检清修全生命周期。"},
    {"title": "2026地下管网侦察兵怎么选？管道检测机器人厂家榜单",
     "url": "https://www.cet.com.cn/xwsd/10319662.shtml",
     "snippet": "TOP厂商盘点：东熙汇通（清淤机器人）、武汉中仪物联（三维实景建模技术派）、"
                "深圳博铭维（全国服务网络）、以及国际品牌Envirosight与Eddyfi。"},
    {"title": "甲方专属资源库：管道检测机器人及配套优质展商全盘点",
     "url": "https://www.shifair.com/informationDetails/384214.html",
     "snippet": "展商名录：深圳市施罗德工业集团（管道CCTV爬行机器人、QV检测）、武汉中仪物联"
                "（CCTV/声呐/AI缺陷识别）、博铭维、合肥哈工智灵、中岩科技等。"},
    {"title": "青岛新业环保科技有限公司 | XY-S190DHD管道检测机器人",
     "url": "https://b2b.baidu.com/land/37115ea0071d39f3e97fe915fb9ee779",
     "snippet": "XY-S190DHD管道检测机器人，轮式运动机构，210万像素双摄像头，市政排水管道内窥检测，"
                "厂商直供约12.8–19.8万元/台。"},
    {"title": "郑州九泰科技有限公司 | 管道检测机器人 实时监测 智能识别缺陷",
     "url": "https://b2b.baidu.com/land/c7ba3323311d6e84f2cb94a96e5235d9",
     "snippet": "九泰科技管道智能内检测机器人，自主研发，实时监测、AI识别管道内部缺陷，"
                "约5–13.9万元/套；另有蜘蛛侠多维爬行机器人约50万元/套。"},
    {"title": "安徽快通智能机器人有限公司 | 快通KT985市政管网检测机器人",
     "url": "https://b2b.baidu.com/shop/77572501",
     "snippet": "快通KT985六轮驱动IP68防水CCTV检测机器人约5–6.6万元/台；"
                "KT975 QV潜望镜25倍变焦约1.05万元；支持DN150小管径。"},
    {"title": "武汉中仪物联技术股份有限公司 | cctv管道检测机器人",
     "url": "http://www.cctv-robot.com",
     "snippet": "中仪股份创立于2010年，专注城市供排水管网检测修复运维信息化整体解决方案，"
                "产品含CCTV检测机器人、管道潜望镜QV检测系统。"},

    # —— 国际竞品（英文产品名维度）——
    {"title": "Worldwide Pipe CCTV Inspection Robot Market 2026",
     "url": "https://pmarketresearch.com/worldwide-pipe-cctv-inspection-robot-market-research",
     "snippet": "市场2025年8.46亿美元，预计2032年16.70亿美元，CAGR 10.2%。主要厂商："
                "RedZone Robotics、Envirosight、CUES、iPEK、Rausch、Deep Trekker、Sanwa Hydrotec、"
                "北京Robway等。类型分轮式爬行机器人、推杆式、侧扫系统。"},
    {"title": "Worldwide Robotic Sewer Inspection Cameras Market 2026",
     "url": "https://pmarketresearch.com?p=2370658/",
     "snippet": "Envirosight ROVVER X六轮转向爬行器（6–96英寸，全球部署超4000套）；"
                "RedZone SOLO自主巡检机器人（8–12英寸，360°全景，兼容PACP）；"
                "iPEK主+支管爬行器、SAT全高清侧扫。趋势：认证、传感融合、云端AI数据链。"},
    {"title": "Pipe Inspection Crawlers Market: 1.41B by 2034, 8.5% CAGR",
     "url": "https://www.datainsightsreports.com/reports/rohrinspektionskriecher-markt-46607",
     "snippet": "竞争格局：CUES、Mini-Cam、Inuktun、IBAK、Envirosight、RedZone、Aries、"
                "Deep Trekker、Rausch、U-LOK（上海）等。挑战：极端管径/塌陷段受限、"
                "操作员培训与数据管理成本高。"},

    # —— 技术路线维度 ——
    {"title": "X5-HS4/X7-DS/X8-A 管道病害多功能检测系统",
     "url": "https://www.zy-cam.com/X5/4450.jhtml",
     "snippet": "X5-HS4高清CCTV检测机器人（250–3000mm，6轮驱动，最高32m/min，IP68）；"
                "X7-DS双轴动力声呐（DN500以上高水位/满水管道，结合PipeSonar三维建模）；"
                "X8-A全景激光测井。集成CCTV+激光+声呐+探地雷达。"},
    {"title": "CCTV管道检测：现代城市地下管网的精准医疗",
     "url": "https://www.yjssi.com/showinfo-4-33787-0.html",
     "snippet": "CCTV管道检测技术通过机器人搭载高清摄像头、激光扫描生成管道三维模型，"
                "精度±1mm；声呐穿透水体测淤泥厚度；惯性导航INS+里程轮定位精度±0.3m；"
                "数据接入GIS构建数字孪生。"},
    {"title": "黄山市供水管道机器人智能巡检技术应用",
     "url": "https://www.ahlyu.cn/NewsDetail.aspx?ID=321",
     "snippet": "2.1 CCTV机器人（DN200以上，360°旋转、10倍光变、激光测距，效率提升3–5倍）；"
                "2.2 声呐检测（满水管道在线检测，不受水质影响）；"
                "2.3 激光扫描（毫米级三维点云，导入GIS数字孪生）。"},
    {"title": "High-Precision defect detection in pipe jacking using CV and point cloud",
     "url": "https://www.mendeley.com/catalogue/b7b0d682-56d0-36f1-b239-e0f4c655bea2",
     "snippet": "两阶段框架：Stage1 CCTV机器人+双目相机+YOLOv5实时缺陷检测与SLAM三维定位；"
                "Stage2 GoSLAM手持LiDAR点云几何校验。哈尔滨2.58km顶管项目验证，"
                "拟合误差均值6.3mm。"},
    {"title": "定位既准又快 还能下井作业 管网机器人让地下管网更顺畅",
     "url": "https://www.wuhan.gov.cn/sy/whyw/202411/t20241114_2484364.shtml",
     "snippet": "武汉市政府门户：中建三局深隧大型管道检测机器人（悬浮前进4.5km，惯性制导+多普勒雷达+AI）；"
                "中仪物联箱涵检测机器人（激光扫描+全景，高坎陡坡弯道）；博铭维穿山甲破障清除机器人。"},

    # —— QV / 价格 / 政策维度 ——
    {"title": "2026年高清管道潜望镜(QV)采购项目询价公告",
     "url": "https://www.biaoyanwang.com.cn/mark/preview/nid/rMvvI1XXDNyMWTme55c..A.html",
     "snippet": "技术参数：控制终端512GB、≥400万像素、≥360倍变焦（光学≥30倍）、IP68、"
                "适用管径≥150mm、内置激光测距、含AI判读功能的检测视频判读报告软件。"
                "执行标准CJJ181-2012。"},
    {"title": "南京市2025-2028年排水管网检测项目中标公告",
     "url": "https://www.ccgp.gov.cn/cggg/dfgg/zbgg/202507/t20250714_24959057.htm",
     "snippet": "中国政府采购网：南京2025-2028排水管网检测项目，QV检测11–12元/米、"
                "声呐检测16–25元/米、CCTV机器人爬行器15–22元/米。三个采购包分别中标。"},
    {"title": "2026年采购参考版：QV检测服务申请与实施要点",
     "url": "https://blog.11467.com/b19442883.htm",
     "snippet": "QV检测服务分层：设备制造商型（埃默司、赛志，硬件性能优）、"
                "区域深耕型（耀玖、文鼎、天禹，本地化响应）、工程服务集成型（万福、煜域）。"
                "代检测约1300–2200元/点位。"},
    {"title": "QV管道检测机器人 潜望镜 市政排水管网检测 参考价格",
     "url": "https://b2b.baidu.com/land/14aa191c861c93d43c88473e5876e0fb",
     "snippet": "QV潜望镜价格：东熙汇通约1.68万/台、快通KT-995约1.68万、固德超前GD-QV-04约1.88万、"
                "九泰科技QV约10.9万/套。代检测100–2400元/点位不等。"},
]


def _fake_search(query: str, max_results: int = 8) -> str:
    """返回真实检索结果（ddgs 文本格式），按查询关键词做轻量命中过滤。"""
    kw = query.lower()
    picked = []
    for h in REAL_HITS:
        blob = (h["title"] + h["url"] + h["snippet"]).lower()
        # 厂商维度命中厂商名；英文维度命中英文品牌；技术维度命中技术词
        if any(k in blob for k in ["博铭维", "中仪", "施罗德", "九泰", "快通", "新业", "bominwell",
                                     "cctv-robot", "shifair", "cet.com"]) and ("厂家" in kw or "manufacturer" in kw or "蓝创" in kw):
            picked.append(h)
        elif any(k in blob for k in ["envirosight", "cues", "redzone", "ipek", "ibak", "deep trekker",
                                      "pmarketresearch", "datainsights"]) and ("manufacturer" in kw or "camera robot" in kw):
            picked.append(h)
        elif any(k in blob for k in ["cctv", "声呐", "激光", "slam", "三维", "yjssi", "zy-cam", "ahlyu", "mendeley", "wuhan.gov"]) and ("技术" in kw or "cctv" in kw or "robot" in kw):
            picked.append(h)
        elif any(k in blob for k in ["qv", "潜望镜", "biaoyanwang", "ccgp", "11467"]) and ("qv" in kw or "价格" in kw):
            picked.append(h)
    if not picked:
        picked = REAL_HITS  # 兜底：返回全部
    # 去重
    seen, out = set(), []
    for h in picked:
        if h["url"] not in seen:
            seen.add(h["url"])
            out.append(h)
    lines = [f"- {h['title']}: {h['url']}\n  {h['snippet']}" for h in out]
    return "\n".join(lines) or "未返回结果。"


# 关键：只替换被网络拦截的检索步骤
web_tool.search_web = _fake_search
main_mod_search = main_mod  # 让 main 取到的 search_web 也是 patch 后的（同模块对象）


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

    # 注入给 Crew 的上下文（与 main.py 同格式）
    ctx_lines = ["# 真实检索结果（来源含可信度分级，严禁编造产品名/链接）", "",
                 "| 产品/机构候选 | 来源标题 | 可信度 | 功能线索 | 命中检索式 |", "|---|---|---|---|---|"]
    for row in table_rows[1:]:
        ctx_lines.append("| " + " | ".join(row[:1] + row[1:2] + row[3:]) + " |")
    ctx_lines.append("")
    ctx_lines.append("【重要】可信度 A=官方/学术，B=主流媒体，C=社区参考。只有 A/B 级可作结论依据，"
                     "C 级需注明「社区反馈，待核实」。产品名均为候选，未经核实。")
    market_ctx = "\n".join(ctx_lines)

    print("[3/3] 运行 CrewAI 三角色分析（scout 不联网，仅基于已注入的真实结果）...")
    llm = None
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
    # tools=[]：避免 scout 调用被拦截的 ddgs；分析基于已注入真实结果
    crew = build_market_crew(TOPIC, llm, tools=[], search_results=market_ctx)
    crew.kickoff()

    report_path = os.path.join(ROOT, "reports", "market_report.md")
    trace_md = "\n".join(trace)
    tsv_block = ("## 检索过程溯源\n\n" + trace_md + "\n\n"
                 "## 产品/机构对比表（由真实检索结果经代码生成，绝不编造）\n\n"
                 "列：产品/机构｜来源标题｜URL｜可信度｜功能线索｜命中检索式\n\n"
                 "```\n" + "\n".join(tsv_lines) + "\n```\n\n"
                 "> 产品/机构名为从标题与URL抽取的候选，非经核实；可信度C的来源属社区反馈，仅供参考。")
    main_mod.append_grounded_refs(report_path, tsv_block)
    print(f"\n===== 完成：报告={report_path}，真实来源 {len(records)} 条 "
          f"(A{tier_stat.get('A',0)}/B{tier_stat.get('B',0)}/C{tier_stat.get('C',0)})，TSV={ref_tsv} =====\n")


if __name__ == "__main__":
    main()
