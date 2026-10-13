# 范围决策：项目收缩为「文献检索」单线

- 决策日期：2026-10-13
- 决策人：项目负责人（陈老板）
- 状态：生效，替代 `docs/v0.2-spec.md` 中的双线规划作为当前开发口径
- 回滚点：tag `v0.2-dual-line`（双线实跑完成时的状态）

## 决策内容

**只做文献检索单线。** 市场 / 竞品调研与双线合稿层不再作为当前开发重点。

## 背景

双线路线已于 2026-10-12 实跑验证完成，产出齐备：

| 产物 | 规模 | 状态 |
|---|---|---|
| 学术线文献综述 | 91 篇真实文献（中 1 / 英 90），正文 108 处引用全部可溯源 | 保留 |
| 市场线调研报告 | 13 条真实来源（A 级 4 / C 级 9），URL+抓取日期+分级 | 归档 |
| 双线合稿报告 | 296 行，82 个 DOI 零越界，含交叉讨论与留白结论 | 归档 |
| 代码级证据底稿 | 双表 + 10 个主题桶交叉带 + 盲区对比 | 归档 |

但两条线意味着两套采集器、两套护栏、两套输出结构、两条维护线。对一个
仍在单人维护的项目，**面铺得比需要的宽**。既然文献检索本身已经跑通并达到
可用状态，先把它做扎实（工作流封装、护栏回归、知识沉淀）比同时维持两条线更划算。

## 保留（当前维护范围）

| 模块 | 位置 | 说明 |
|---|---|---|
| 多源采集 | `src/tools/{literature,openalex,crossref,cnki}_tool.py` | 四级文献源，容错降级 |
| 中文质量判据 | `src/tools/core_journals.py` | 北大核心白名单 77 种 |
| 检索式构造 | `src/tools/query_translator.py`、`domain_lexicon.py` | 全部等价词 + 对象⊕条件组合 |
| 两道护栏 | `sanitize_report_urls`、`sanitize_report_citations` | URL / DOI 白名单对账 |
| Crew | `src/crews/literature_crew.py` | 分析员 → 撰稿员（无检索员角色） |
| 记忆库 | `src/tools/memory_*.py`、`memory/` | TTL 分级复审 + 人工裁决 |

## 归档（保留代码，暂不维护）

| 内容 | 位置 |
|---|---|
| 市场调研链路 | `--mode market`、`src/crews/market_crew.py`、`src/tools/market_query.py`、`src/tools/source_credibility.py`、`src/tools/web_tool.py` |
| 实跑脚本 | `scripts/run_market_real.py`、`scripts/run_market_real_highwater.py` |
| 双线合稿层 | `scripts/merge_dual_reports.py`、`scripts/build_dual_line_evidence.py` |

**为什么暂存而不删**：来源分级逻辑（A/B/C）与合稿层的双护栏设计本身有复用价值；
删除是可逆但会丢失上下文的操作，因此先归档、以文档标注，代码量不大（合计约 1500 行）。
若确定不再需要，`git checkout v0.2-dual-line -- <路径>` 可随时取回。

## 归档内容的已知缺陷（恢复使用前必须先修）

1. **市场线 scout 角色空转**：`tools=[]` 时该角色扮演搜索，把不存在的检索
   （如「检索政策文件返回 0 条」）写进报告正文。需按学术线同款方式移除该角色。
2. **合稿层依赖注入式检索数据**：`scripts/run_market_real_highwater.py` 内嵌了
   人工采集的 24 条真实命中作为演示数据，不可当作实时检索通道。

## 后续

1. 把文献检索链路封装为一条可复用工作流（一条命令 + 配置化主题）
2. 护栏回归纳入自测（`scripts/` 下扩充），保证 DOI 对账不被改坏
3. `knowledge/` 领域知识沉淀（环境工程 / 污水处理术语与项目语境）