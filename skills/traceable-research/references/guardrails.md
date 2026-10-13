# 护栏：两道闸口与实测数据

## 为什么需要护栏（这是本 skill 存在的理由）

2026-10-12 实测：对一份已生成的文献综述做引用对账，正文 51 个 DOI 里
**只有 1 个**能在真实检索清单（`literature_references.tsv`）里找到，
其余 **50 个是撰稿员凭参数记忆编造的**，包括看起来完全合理的
`10.1016/j.envres.2021.111609`、`10.1016/j.watres.2011.07.008`。

当时的状况是：**URL 侧有闸口、引用侧没有**。Crew 提示词里写了
「参考文献必须 100% 来自检索结果、DOI 逐字照抄、严禁编造」——完全无效。

结论（已写入项目 spec 与 AGENTS.md，作为红线）：
**prompt 约束一律不算护栏。凡「模型不许编」的要求，都要有代码级白名单对账兜底。**

## 两道闸门

| 闸口 | 实现 | 处理对象 | 标记 |
|---|---|---|---|
| URL 闸口 | `sanitize_report_urls(report, allowed_urls)` | markdown 链接与裸链 | `（来源待核实）` |
| DOI 闸口 | `sanitize_report_citations(report, allowed_dois)` | 正文全部 DOI 形态串 | `〔DOI 不可溯源，已剔除〕` |

两条都在 `src/main.py`，运行在 Crew 写稿之后、代码生成文献表之前。

### DOI 抽取的三个坑（改这段代码前必读）

1. **不能按 ASCII 括号截断**：ASCE 系列真实 DOI 含括号与冒号，
   如 `10.1061/(ASCE)0733-9429(2003)129:7(504)`。按 `)` 截断会把它切坏。
2. **要按中文标点截断**：报告里常见「`10.1016/j.autcon.2019.04.013，被引121次`」，
   不截断会把后半截并进 DOI，导致白名单比对失败。
3. **不成对的右括号要剥**：`10.1000/xyz123)` → `10.1000/xyz123`；
   成对括号必须保留（同坑 1）。

以上三条均有回归用例锁定：`scripts/selftest_guardrails.py`（14 项）。

## 第三道：带外核验（skill 自带）

项目内的闸口是**进程内**的——只有跑项目流水线才生效。skill 自带
`scripts/verify_report.py`，纯标准库、不 import 项目代码，对**任意** markdown
报告做独立抽检：

```bash
# 文献线：与检索缓存比对
python verify_report.py reports/literature_report.md --refs reports/academic_results.json

# 市场线：与来源记录比对
python verify_report.py reports/market_report.md --refs reports/market_records.json

# 多份一起查，JSON 输出便于归档
python verify_report.py a.md b.md --refs refs.tsv --refs cache.json --json
```

它做四件事：
1. 抽取并规整全部 DOI（同一套规整规则）→ 与白名单比对，报越界项
2. 抽取全部 URL → 与白名单比对
3. 检出闸口标记（`〔DOI 不可溯源…〕`、`（来源待核实）`）——出现即说明产物含被剔除项
4. **检出伪造检索措辞**（如「检索"…"返回0条」）——这是无工具角色扮演式检索的痕迹

退出码：`0` 通过 / `1` 存在白名单外引用（必须修）/ `2` 需人工复核。

### 真实案例（三份产物实测）

| 产物 | 白名单 | 结果 |
|---|---|---|
| 修复后重生成的 `literature_report.md` | `academic_results.json`（74 个 DOI） | ✅ 通过：74 个不同 DOI、108 次引用，0 越界 |
| `market_report.md` | `market_records.json`（13 个 URL） | ⚠️ 需人工复核：URL 全在册，但**第 36、136 行检出伪造检索措辞**「检索"排水管网 高水位 政策 文件"返回0条」 |
| 修复前的旧 `literature_report.md` | `academic_results.json` | 🚨 不通过：**48 个越界 DOI** |

第2 行就是市场线 scout 空转的证据——它声称做过一次检索并返回 0 条，
实际上没有工具、那次检索不存在。**这类断言不得写进任何对外材料。**

## 第三条红线：不给 LLM「检索员」角色

检索由代码完成时，若 Crew 里还有一个 tools 为空的「检索员/侦察员」角色，
它会凭参数记忆编一份清单，经 `context` 传给下游分析与撰稿——
这是假引用的源头之一。项目已据此处理：
`build_literature_crew()` 在有注入检索结果时自动降为「分析员 → 撰稿员」两角色。
**不要改回去。** 市场线的 scout 尚未处理，是已知遗留缺陷。

## 交付前的最小检查清单

- [ ] `verify_report.py` 退出码为 0（不是 2）
- [ ] stdout 的质量过滤明细已读，中文剔除原因已处理或已向用户说明
- [ ] TSV 文献表条数与报告声称的引用条数一致
- [ ] 报告中没有任何「检索返回 0 条」类未经证实的断言
- [ ] 分级与限定词在转述中没有被升格
