"""来源分级与产品名抽取的独立自测脚本（不涉及 LLM 与网络）。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.source_credibility import (  # noqa: E402
    classify_source,
    extract_features,
    extract_product_name,
)

print("=== 来源可信度分级 ===")
CASES = [
    ("https://www.mee.gov.cn/xxgk2018/", "A", "生态环境部政策文件"),
    ("https://www.sciencedirect.com/science/article/pii/S0001", "A", "期刊论文"),
    ("https://36kr.com/p/123456", "B", "科技媒体"),
    ("https://www.theverge.com/ai", "B", "海外科技媒体"),
    ("https://www.zhihu.com/question/123", "C", "社区问答"),
    ("https://baijiahao.baidu.com/s?id=123", "D", "内容农场(应丢弃)"),
    ("https://www.epa.gov/water-research", "A", "政府机构"),
    ("https://github.com/some/project", "B", "开源项目"),
    ("https://random-blog.xyz/post/1", "C", "个人博客(未知来源)"),
]
ok = 0
for url, expect, note in CASES:
    got = classify_source(url)
    mark = "OK" if got == expect else "MISMATCH"
    if got == expect:
        ok += 1
    print(f"  [{got}] {note:18} {url[:52]}  ({mark})")
print(f"分级命中 {ok}/{len(CASES)}")

print()
print("=== 产品名抽取 ===")
NAME_CASES = [
    ("海康机器人污水巡检方案发布", "https://www.hikrobotics.com/product/x"),
    ("《智慧水务巡检系统》技术白皮书", ""),
    ("新松污水处理巡检机器人发布", ""),
    ("Sewer Inspection Robot for Municipal Utilities", ""),
    ("某小型化设备", ""),
]
for title, url in NAME_CASES:
    print(f"  {title[:40]:42} -> {extract_product_name(title, url)or '(未识别)'}")

print()
print("=== 功能线索抽取 ===")
FEAT_CASES = [
    "基于机器视觉的管道缺陷检测与诊断系统",
    "城镇污水厂智能巡检与运维调度平台",
    "Real-time sewer monitoring and overflow prediction",
]
for t in FEAT_CASES:
    print(f"  {t[:44]:46} -> {extract_features(t)}")