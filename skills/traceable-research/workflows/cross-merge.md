# 工作流 C：两线交叉 + 两稿合并

把文献线与市场线的产物合成**一篇**带交叉讨论的报告。这是本项目交叉能力的落点：
并排贴在一起不叫交叉，真正的信息在两线的**错位处**。

前置：两条线的产物都已落盘，且各自过了产物核验。没有就先跑
[`literature.md`](literature.md) 与 [`market.md`](market.md)。

## 步骤

### 1. 生成代码级证据底稿（无 LLM 调用）

```bash
cd "${ARA_HOME:-$HOME/academic-research-agent}"
.venv/Scripts/python.exe scripts/build_dual_line_evidence.py
```

产出 `reports/dual_line_evidence.md`：学术/市场双区块详表（各保持原生字段）+
10 个主题桶交叉带（每条证据只进一个桶，只引 ID 不重复标题）+ 两线盲区对比。
排序键显式写在表头下方，来源标识一律不截断。

首次运行会同时落 `academic_results.json` / `market_records.json`——
它们是两道闸门的白名单来源。若检索缓存已存在，脚本会直接复用（秒级）。

### 2. 合稿（单次 LLM 调用）

```bash
.venv/Scripts/python.exe scripts/merge_dual_reports.py
```

产出 `reports/dual_line_report.md`，八章结构：

```
摘要 → 引言（范围/两线分工/双套溯源标准）
     → 文献线：能不能做 → 市场线：值不值得做
     → 双线交叉讨论 → 结论与人工对照（留白）
     → 参考文献（代码生成，两线分列） → 附录：检索过程溯源
```

合稿铁律（违反即作废，详见项目 spec 第 10 节）：

1. **只重组不新增事实**——所有事实/数字/文献/机构名来自两篇输入报告
2. **分级与限定词原样保留**——C 级不得在转述时升格
3. **不给立项建议**——结论区只写「证据支持/不支持/还缺什么」
4. **合稿后再跑一次双护栏**——合稿环节同样会编引用
5. **参考文献与溯源由代码生成**——LLM 写了也会被剥离

### 3. ⛔ 核验合稿产物

```bash
python "${SKILL_DIR}/scripts/verify_report.py" \
  "${ARA_HOME:-$HOME/academic-research-agent}/reports/dual_line_report.md" \
  --refs "${ARA_HOME:-$HOME/academic-research-agent}/reports/academic_results.json" \
  --refs "${ARA_HOME:-$HOME/academic-research-agent}/reports/market_records.json"
```

合稿引用了两线的来源，所以两个白名单都要传。退出码含义同其他工作流。

### 4. 交付

正文可直接给用户；**结论区保持留白**（人工对照清单未填），
并明确告诉用户「该不该做由人判断，本稿只交证据」。

## 已知限制

- 合稿层**未接入 `main.py`**（`--mode` 只有 literature / market / memory），
  必须手动跑本工作流的第 1、2 步。
- 交叉讨论质量取决于检索覆盖面：某条线样本太少时，「仅某一线命中」往往只是
  检索覆盖不足，不是「一边热一边冷」的结论。底稿第四节对此有注记。

## 注意

底稿（`dual_line_evidence.md`）适合直接阅读与核对，正文（`dual_line_report.md`）
适合转发。两者内容不重复：底稿是结构化数据，正文是叙述。