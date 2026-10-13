---
name: traceable-research
description: |
  可溯源调研交付专用 Skill：跑文献检索（学术）与市场/竞品调研两条线，产出「每条引用都点得开」的报告，并在交付前用代码闸门抽检引用真伪。适用于：检索某主题的中英文文献、写文献综述、判断一份调研报告里的 DOI/链接是真是假、按北大核心期刊标准筛选中文文献、把调研结果写进立项材料或项目申报。
  与 academic-search 的分工：academic-search 负责「尽可能多地找到文献」，本 skill 负责「交付物的每条引用可溯源 + 中文质量判据 + 中文补检知网」。当用户只想要一份论文列表时用 academic-search；当用户要的是「能直接交出去、引用经得起核对」的报告时用本 skill。
agent_created: true
metadata:
  version: "1.0.0"
---

# traceable-research Skill

## 核心立场

**prompt 里写「严禁编造」不算护栏。** 本skill 的一切流程都建立在一个实测事实上：
2026-10-12 抽查一份文献综述，正文 51 个引用里 **50 个是编造的**（如
`10.1016/j.envres.2021.111609`），而当时项目只有 URL 侧闸口、引用侧没有。
因此本 skill 的三条硬规则：

1. 文献表/来源表由代码生成，LLM 不参与其生成
2. 报告正文引用交付前必须过代码闸门对账（DOI + URL 两条）
3. 检索已由代码完成时，**不给 LLM「检索员」角色**——它在无工具时会凭记忆编清单

## 前置检查（每次任务开始前执行，不要跳过）

```bash
# 1) 定位项目根：优先读环境变量 ARA_HOME，否则用默认路径
ARA="${ARA_HOME:-$HOME/academic-research-agent}"
test -d "$ARA/src" || { echo "未找到项目，请设 ARA_HOME 指向 academic-research-agent 仓库根"; exit 1; }

# 2) 环境与依赖
test -x "$ARA/.venv/Scripts/python.exe" || echo "缺虚拟环境：先 python -m venv .venv && pip install -r requirements.txt"
test -f "$ARA/.env" || echo "缺 .env：需要 OPENAI_API_KEY；LLM 必须支持 function calling（CrewAI 依赖）"

# 3) 中文检索前置（仅当主题含中文时）：知网需已安装并完成登录初始化
#    未初始化时提示用户先跑 cnki-mcp init，本skill 不代做登录
```

知网/万方/维普不爬取——付费库无公开 API 且禁止爬虫，这是合规红线，不是缺陷。
中文核心刊覆盖不足时走「人工补检知网」流程，见 `references/troubleshooting.md`。

## 工作流 A：文献检索（当前主维护线）

```bash
cd "$ARA" && .venv/Scripts/python.exe src/main.py --mode literature --topic "<主题>"
```

- 中文主题会自动构造英文检索式（术语表驱动，对象⊕条件组合，规则见
  `references/query-construction.md`）；推荐中英混写，如
  `--topic "城镇污水处理 侧流 生物除磷 side-stream EBPR"`
- 产出：`reports/literature_report.md`（综述）+ `reports/literature_references.tsv`
  （真实文献表，可直接粘进 Excel）
- **必看 stdout 的「质量过滤明细」**——中文被剔除时那里会写清原因与样例；
  出现「中文文献剔除 N 篇」时按 `references/troubleshooting.md` 处理，不要装作没看见

## 工作流 B：市场/竞品调研（归档线，带硬前置）

⚠️ **该线存在已知缺陷，产物必须人工复核。** 市场线的 scout 角色在无工具时会
角色扮演检索，把不存在的检索（如「检索政策文件返回 0 条」）写进报告正文。
实测该痕迹已被本 skill 的核验脚本捕获（案例见 `references/guardrails.md`）。

在缺陷修复前（跟踪项目 `docs/scope-decision-2026-10-13.md`），使用市场线的规则：

1. 每次跑完**必须**执行产物核验（下一节），出现「需人工复核」即视为不合格
2. 报告中任何「检索返回 0 条 / 未检索到相关结果」的表述一律视为**未经证实的断言**，
   不得引用、不得写进任何对外材料
3. 交付给立项会或领导时，优先只交付文献线结论；市场线仅作旁证并标注 C 级/待核实

## 产物验证（交付前必跑，不可跳过）

```bash
cd "$ARA" && python skill/traceable-research/scripts/verify_report.py \
  reports/literature_report.md --refs reports/academic_results.json
```

- 退出码 0 = 通过；1 = 存在白名单外引用（**必须修，不得交付**）；2 = 需人工复核
- 本脚本纯标准库、不 import 项目代码，可在任何环境对**任意**报告做带外抽检
- 项目自测（改动护栏后必须全绿）：`scripts/selftest_guardrails.py`（14 项）、
  `scripts/selftest_quality_filter.py`（11 项）、`scripts/selftest_memory.py`（51 项）
- 交付文献清单时用 TSV 里的真实记录，**不要从报告正文反推参考文献**

## 交付话术纪律

- 「证据支持 / 不支持 / 缺口」分开写，**不给立项建议**——判断权在人不在 Agent
- A/B/C 分级、「待核实」「证据不足」等限定词原样保留，不许在转述时升格
- 引用条数、来源条数、被引数等数字必须来自产物，不得凭印象填写

## references（按需加载，不要一次全读）

| 文件 | 何时读 |
|---|---|
| `references/guardrails.md` | 需了解两道闸口实现、实测数据、核验脚本用法与真实案例 |
| `references/quality-criteria.md` | 需判断中文文献为何被剔除、白名单/黑名单/学位论文豁免规则 |
| `references/query-construction.md` | 需理解或调试中英文检索式构造；召回跑偏时先读 |
| `references/troubleshooting.md` | 检索报错、中文全被过滤、限流、LLM 超时、产物缺失 |

## 绝不做的事

- 不把付费库（知网/万方/维普）写爬虫
- 不把 `.env`、API key、记忆库内容提交进任何仓库或分享给他人
- 不在无白名单的情况下声称「引用可溯源」
- 不因为「报告已经生成了」就跳过产物核验
