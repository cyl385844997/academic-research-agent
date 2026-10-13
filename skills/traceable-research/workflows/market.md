# 工作流 B：市场 / 竞品检索

回答「这个方向市场上有人做吗、格局如何、值不值得进」。产出分级来源的格局报告。

## 步骤

### 1. 确认能出网

```bash
cd "${ARA_HOME:-$HOME/academic-research-agent}"
grep -c TAVILY_API_KEY .env    # 有 Tavily 更稳；无则回退 ddgs
```

- ddgs 回退走 `search.brave.com`，**受限网络下会超时**。遇到超时不要反复重试。
- 若两条路都不通：说明当前环境无法做市场检索，**如实告知用户**，不要用编造的来源凑一份报告。

### 2. 跑检索

```bash
.venv/Scripts/python.exe src/main.py --mode market --topic "<主题>"
```

程序内部：LLM 把题目拆成多维检索式（通用中文 / 通用英文 / 技术路线 / 产品名 /
应用案例，5 条）→ 逐条 Web 检索 → 来源分级（A/B/C，D 级内容农场丢弃）→ 去重 →
Crew 两角色分析撰写 → URL 闸门 → 附代码生成的来源清单。

产品名一律视为**候选**（从标题与 URL 抽取），报告措辞须用「检索到」而非断言。

### 3. ⛔ 产物核验

```bash
python "${SKILL_DIR}/scripts/verify_report.py" \
  "${ARA_HOME:-$HOME/academic-research-agent}/reports/market_report.md" \
  --refs "${ARA_HOME:-$HOME/academic-research-agent}/reports/market_records.json"
```

核验器会检出两类东西：

1. **白名单外 URL** —— 报告引用了检索结果里没有的链接
2. **伪造检索措辞** —— 如「检索"…"返回 0 条」。这类断言是已删除的侦察员角色
   在无工具时角色扮演检索留下的，**是无效断言，不得转述**。

历史产物 `reports/market_report.md` 即因此被检出（第 36 / 136 行）。
**修复（2026-10-13）后的新产物不应再出现该措辞**；若仍出现，说明跑的是旧代码。

### 4. 交付

- `reports/market_report.md` + `reports/market_references.tsv`（URL + 抓取日期 + 分级）
- 结论按可信度分层陈述：A/B 级可作结论依据；C 级只作旁证并标「待核实」
- 市场规模、供应商格局、价格这三类信息缺 A/B 级来源时，**明说「证据不足」**，
  不要用行业常识补

## 注意

- 市场线不做付费库/专利库的深度检索；专利降级方案见
  [`../../docs/v0.2-spec.md`](../../docs/v0.2-spec.md) 第 9 节（项目级文档，按需读）
- 两条线的内容要合并时，走 [`cross-merge.md`](cross-merge.md)，不要自己拼接。