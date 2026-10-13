# 工作流 A：文献检索

回答「这个主题的研究现状是什么、能不能做」。产出可溯源的综述 + 文献表。

## 步骤

### 1. 确认主题写法

- 推荐**中英混写**，一次覆盖两类文献：
  `--topic "城镇污水处理 侧流 生物除磷 side-stream EBPR"`
- 纯中文可以，程序会构造英文检索式；但**英文源质量明显更高**
  （S2 / OpenAlex 能命中 Water Research、ES&T 等顶级期刊）
- 用专业术语，不用口语（「城镇排水管道检测与修复」而非「查水管」）

需要理解检索式怎么构造、召回跑偏怎么查 → 读
[`../references/query-construction.md`](../references/query-construction.md)。

### 2. 跑检索

```bash
cd "${ARA_HOME:-$HOME/academic-research-agent}"
.venv/Scripts/python.exe src/main.py --mode literature --topic "<主题>"
```

程序内部：领域词典/LLM 解析主题 → 知网 + 英文三源检索 → 解析去重 →
质量过滤（中文按北大核心白名单）→ 中英文均衡 → 写 TSV → Crew 两角色分析撰写
→ 两道闸门对账 → 附代码生成的文献表。

耗时参考：四源全跑约 4-5 分钟，Crew 两角色约 100 秒（LLM 端点慢时更久）。

### 3. ⛔ 必看 stdout 的质量过滤明细

程序会打印剔除条数、原因分布与样例，以及中文专项提示：

```
📋 质量过滤明细：剔除 11/103 条 —— 主题不相关 9 条；非北大核心期刊 2 条
⚠️ 中文文献剔除 11 篇（主题不相关 9 篇；非北大核心期刊 2 篇）——属数据源限制…
```

看到「中文文献剔除 N 篇」**不能装作没看见**，按
[`../references/quality-criteria.md`](../references/quality-criteria.md) 判断：
换检索词，还是走人工补检知网。

### 4. ⛔ 产物核验

```bash
python "${SKILL_DIR}/scripts/verify_report.py" \
  "${ARA_HOME:-$HOME/academic-research-agent}/reports/literature_report.md" \
  --refs "${ARA_HOME:-$HOME/academic-research-agent}/reports/academic_results.json"
```

退出码：`0` 通过 / `1` 有白名单外引用（必须处理）/ `2` 需人工复核。
细节见 [`../references/guardrails.md`](../references/guardrails.md)。

### 5. 交付

给用户的是：

- `reports/literature_report.md` —— 综述正文
- `reports/literature_references.tsv` —— **真实文献表，可直接粘贴进 Excel**
- 摘要 + 研究空白 + 3 条以内最值得注意的发现

纪律：不给立项建议；「证据不足」原样转述；数字以产物为准。

## 中文为零时的处理

知网/万方/维普是付费库，不爬取。中文为零时：

1. 先看 stdout 的剔除原因——是「非北大核心期刊」还是「主题不相关」
2. 若是主题不相关，说明检索式过严，换核心刊常用术语
3. 仍为零 → 走人工补检流程（[`../references/troubleshooting.md`](../references/troubleshooting.md)），
   把结果按 TSV 列序补进 `literature_references.tsv`
4. 补检后重跑第 4 步核验（缓存与文献表不同步会报越界，属预期）

## 注意

历史产物 `reports/market_report.md` 是修复前生成的，含伪造检索措辞；
本工作流不涉及它，但若用户要引用市场结论，转 [`market.md`](market.md)。