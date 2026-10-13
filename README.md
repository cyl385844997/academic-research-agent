# academic-research-agent

> 学术前期研究 Agent —— 聚焦**文献检索**单线：真实学术库采集 → 代码级可溯源护栏 → 结构化文献综述报告。

本仓库是逐步迭代的个人 / 团队项目。当前版本只做**文献检索**（不做市场 / 竞品调研，
不做申请书全文、不写论文全文）。垂直领域（环境工程 / 污水处理）的知识沉淀留到后续版本。

## 为什么做这个

市面上已有 40+ 款课题申报 / 学术写作 AI 工具，但普遍存在两个问题：

1. **参考文献不可溯源**：通用大模型会编造 DOI / 期刊。本 agent 强制「文献表由代码从真实学术库抓取生成」，LLM 只做分析，并在写稿后再用代码对账一遍 DOI。
2. **缺乏个人 / 领域语境**：通用 SaaS 生成的本子没有「你自己的研究积累」。本项目的 `knowledge/` 目录预留用于沉淀领域知识与个人项目材料（后续版本）。

## 可溯源铁律（核心设计）

**文献表由代码生成，LLM 绝不参与其生成；报告正文里的引用还要再过一道代码闸口。**

采集与分析分离：

```
代码采集（资料员）→ 真实记录 → 代码生成 TSV 文献表 + 注入 Crew 上下文
                                        ↓
                              LLM 只做分析与撰写（研究员/撰稿员）
                                        ↓
代码对账（护栏）→ 剥离不在检索结果内的 URL / DOI → 追加代码生成的文献表
```

- `main.py` 先依次调用真实学术库 → 解析 → 写出权威 TSV；
- 真实结果作为上下文注入 Crew，Agent **只做分析**，任务中明确禁止编造文献；
- 报告生成后，代码两道闸口兜底：
  - `sanitize_report_urls()` —— 剥离不在检索结果内的 URL（标记「来源待核实」）
  - `sanitize_report_citations()` —— 剥离不在检索结果内的 DOI（标记「DOI 不可溯源，已剔除」）

### 为什么 prompt 里写「严禁编造」不够（实测记录）

| 实测 | 结果 |
|---|---|
| 早期版本让 LLM 自己生成文献表 | 出现「真实 DOI 指向完全不同的论文」「DOI 根本不存在」 |
| 仅 URL 闸口、引用层无闸口（2026-10-12 前） | 文献综述正文 51 个引用中 **50 个是编造的**，仅 1 个能溯源 |
| 补上 DOI 闸口 + 去掉「检索员」角色后重跑 | 正文 108 处引用、82 个唯一 DOI，**0 编造**（闸口零剔除） |

两条结论已固化为红线，写进 `docs/v0.2-spec.md`：

1. **prompt 约束一律不算护栏**——凡「模型不许编」的要求，都要有代码级白名单对账兜底。
2. **检索已由代码完成时，不要再给 LLM 一个「检索员」角色**——它在没有工具时会凭参数记忆编一份清单，经上下文传给下游分析与撰稿，是假引用的源头。本项目 Crew 已据此改为「分析员 → 撰稿员」两角色。

## 中文文献支持（以北大核心期刊为唯一标准）

本项目**同时支持中文与英文文献检索**，检索结果标注 `语言:zh` / `语言:en`，
文献表单列「语种」字段，综述正文也会分别梳理中英文研究进展。

### 质量标准：北大中文核心期刊白名单

中文文献只保留**发表在北大核心期刊上**的记录，这是唯一的质量判据。
白名单来源：《北大〈中文核心期刊要目总览〉2023年版》第十版，
由用户提供原始目录文档后程序化提取并逐条核验，**共 77 种**，见
`src/tools/core_journals.py`。

| 分组 | 数量 | 举例 |
|---|:---:|---|
| 环境科学（主基准） | 27 | 中国环境科学、环境科学学报、环境工程学报、生态环境学报 |
| 给水排水·土木工程 | 11 | **中国给水排水**、**给水排水**、土木与环境工程学报、建筑结构学报 |
| 水文·海洋·地理 | 13 | 水文、海洋工程、湖泊科学、湿地科学 |
| 水利灌溉 | 6 | 排灌机械工程学报、节水灌溉、农业工程学报 |
| 能源与动力 | 9 | 工程热物理学报、动力工程学报（污水厂能耗优化相关） |
| 微生物·生态 | 11 | 微生物学报、生态学报、应用生态学报 |

**不在名单内的中文文献一律剔除**（如「工程管理与技术探讨」「数据期刊」等付费灌水刊）。

### 关于知网 / 万方 / 维普

这三家是**付费订阅数据库，均未提供公开检索 API，且明确禁止爬虫与批量抓取**。
因此本项目**不做自动爬取**——这是合规要求。

实际影响：**中文核心刊文献在免费库中的覆盖有限**，程序能拿到的中文文献
往往很少甚至为零（会主动预警）。这是数据源限制，不是程序缺陷。
**正式写立项材料前建议人工补检知网**，见下方操作建议。

### 推荐检索词写法

程序把 `--topic` 原样送给学术数据库，**中英文混写可同时覆盖两类文献**：

```bash
# 推荐：中英混写
--topic "城镇污水处理 侧流 生物除磷 side-stream EBPR"
```

> ⚠️ **英文检索质量明显更高**。免费英文库（S2 / OpenAlex）能命中
> Water Research、ES&T 等顶级期刊；中文部分则多为灌水刊。
> 若只需要高质量文献，直接用英文检索词。

### 人工补检知网的建议

1. 用**专业术语**而非口语表述（如「城镇排水管道检测与修复」而非「查水管」）；
2. 限定年份近 5 年，并勾选**北大核心 / CSSCI**；
3. 用「被引」或「相关度」排序找高影响力文献；
4. 找到的文献可手动补进 `literature_references.tsv`。

---

## 能力边界（当前版本）

| 模块 | 模式 | 说明 |
|------|------|------|
| 文献检索 | `--mode literature` | 代码采集 + 分析员→撰稿员两角色，产出文献综述报告 + TSV 文献表（DOI 经代码对账） |
| 记忆库 | `--mode memory` | 偏好与领域约定的长期记忆，TTL 分级复审 |
| 市场调研 | `--mode market` | **已归档，暂不维护**（见下方「已归档内容」） |

### 四级文献源（中英文并行）

```
中文 → 知网（专业检索式 + 北大核心白名单）
英文 → Semantic Scholar → OpenAlex → Crossref（自动容错）
```

**输入中文即可**：程序会用 LLM 把中文主题转换为国际期刊通用术语的英文检索式，
与中文检索并行执行。例如「侧流生物除磷」自动转成
`(sidestream OR side-stream) AND ("biological phosphorus removal" OR EBPR)`。

> ⚠️ 英文检索式的构造规则（2026-10-12 修复）：条件角色取**全部等价词**，
> 对象角色 cap 3，且对象与条件做**组合查询**。旧版每角色只取首个等价词，
> 导致「高水位」被直译为 `high water level`，实测 55 条召回大半是
> 潮位 / 沼泽 / 地衣等无关文献；修复后 91 条主体回到排水管网压力流水力学。

**文献源均无需 API key**（知网需已安装 [cnki-mcp](https://github.com/SepineTam/cnki-mcp) 并完成登录初始化）。

---

## 快速开始

```bash
# 1) 安装（建议 Python 3.10 ~ 3.12）
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

# 2) 中文检索需额外准备 cnki-mcp（一次性）
git clone https://github.com/SepineTam/cnki-mcp.git
cd cnki-mcp && uv sync && uv run playwright install chromium
uv run cnki-mcp init      # 浏览器内完成知网认证

# 3) 运行
cd ..
python src/main.py --mode literature --topic "侧流生物除磷"
```

## 安装

建议使用 **Python 3.10 ~ 3.12**（CrewAI 对 3.13 兼容性不稳定）。

```bash
git clone <本仓库地址>
cd academic-research-agent
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 然后编辑 .env 填入你的 API key
```

## 配置（.env）

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | LLM 密钥 |
| `OPENAI_MODEL` | 模型名 |
| `OPENAI_BASE_URL` | OpenAI 兼容端点（可选）。已验证可用：`https://apihub.agnes-ai.com/v1`、`https://token.sensenova.cn/v1` |
| `SEMANTIC_SCHOLAR_API_KEY` | 可选，提升文献检索速率 |

> ⚠️ LLM 必须支持 **function calling**（工具调用），CrewAI 的检索工具依赖此能力。
> 可用 `curl <BASE_URL>/models` 查看端点支持的模型名。

## 用法

```bash
# 文献检索与综述
python src/main.py --mode literature --topic "side-stream EBPR wet weather overflow"

# 记忆库
python src/main.py --mode memory --topic "高水位"      # 查相关记忆
python src/main.py --mode memory --topic "refresh"     # 从会话日志自动提炼（演练）
```

执行完成后，报告生成在 `reports/` 目录：

- `literature_report.md` —— 分析报告（摘要 / 背景 / 中英文现状 / 研究空白 / 有价值方向）
- `literature_references.tsv` —— 真实文献表（**可直接粘贴进 Excel**）

## 记忆库：让 Agent 记住你的偏好

跑过几次之后你会发现，同一条纠正不该反复说第二遍。记忆库就是为此存在的。

```bash
# 记一条本次会话要点（日后自动从中提炼长期记忆）
python src/main.py --mode memory --topic "log 用户要求：报告里的实测值要脱敏"

# 自动提炼「值得长期记住」的信息——默认只演练，加 --confirm 才真正落库
python src/main.py --mode memory --topic "refresh"
python src/main.py --mode memory --topic "refresh" --confirm

# 手动加一条偏好，或直接用记事本改 memory/entries/*.md
python src/main.py --mode memory --topic "add 以后给我 TSV 表格，不要 xlsx"
python src/main.py --mode memory --topic "list"      # 看全部
python src/main.py --mode memory --topic "stats"     # 统计
python src/main.py --mode memory --topic "pending"   # 看待裁决的提案

# TTL 分级复审（user 90 天 / project 30 天 / domain 365 天）
python src/main.py --mode memory --topic "stale"             # 查久未确认的记忆
python src/main.py --mode memory --topic "confirm <ID>"      # 确认续期
python src/main.py --mode memory --topic "drop <ID>"         # 归档
```

运行 `literature` 时，程序会按主题自动召回相关记忆，
以「优先于你的通用写作习惯」的措辞注入分析过程。

**三条设计取向**（细节见 `memory/README.md`）：

1. **你可以随时直接编辑记忆**——一条记忆就是一个 Markdown 文件，记事本就能改，
   改完立即生效。不用学任何命令。
2. **LLM 只提议、不直接落库**。自动提炼出来的东西分两类：
   确实全新的、以及需要人工裁决的（与既有记忆重复、或口径矛盾）。
   后者进 `pending.md` 等你裁定——因为错记忆一旦自动生效，会持续污染后续所有输出。
3. **记忆库不入库**。本仓库是 public，而记忆含你的个人偏好与在办课题，
   已由 `.gitignore` 排除，仅目录说明随仓库保留。

## 已归档内容（暂不维护）

2026-10-13 决策：项目收缩为**文献检索单线**。以下内容已实跑验证并保留在仓库中，
但不作为当前开发重点；如需恢复完整双线行为，可回到 tag `v0.2-dual-line`：

| 内容 | 位置 | 说明 |
|------|------|------|
| 市场 / 竞品调研 | `--mode market`、`src/crews/market_crew.py`、`src/tools/market_query.py`、`src/tools/source_credibility.py` | 曾实跑产出 13 条分级来源的真实市场报告；含来源 A/B/C 分级逻辑 |
| 双线合稿层 | `scripts/merge_dual_reports.py`、`scripts/build_dual_line_evidence.py` | 两篇报告合成一篇 + 代码级证据底稿（交叉带 / 盲区） |

决策依据见 `docs/scope-decision-2026-10-13.md`。

## 目录结构

```
academic-research-agent/
├── README.md
├── AGENTS.md                     # 面向 AI agent / 协作者的项目说明书
├── requirements.txt
├── .env.example
├── .gitignore
├── src/
│   ├── main.py                   # CLI 入口 + 多源容错 + 文献表生成 + 两道护栏
│   ├── tools/
│   │   ├── literature_tool.py    # Semantic Scholar 文献检索
│   │   ├── openalex_tool.py      # OpenAlex 备用文献检索
│   │   ├── crossref_tool.py      # Crossref 备用文献检索
│   │   ├── cnki_tool.py          # 知网检索（经 cnki-mcp）
│   │   ├── core_journals.py      # 北大核心期刊白名单（77 种）
│   │   ├── domain_lexicon.py     # 领域术语表（中英对照）
│   │   ├── query_translator.py   # 中文主题 → 英文检索式构造
│   │   ├── memory_*.py           # 记忆库：存储 / 提炼 / 工具包装
│   │   ├── market_*.py           # 【归档】市场调研相关
│   │   └── web_tool.py           # 【归档】Web 检索
│   └── crews/
│       ├── literature_crew.py    # 文献检索：分析员 → 撰稿员（无检索员）
│       └── market_crew.py        # 【归档】市场调研三角色
├── docs/
│   ├── scope-decision-2026-10-13.md   # 单线范围决策记录
│   ├── v0.2-spec.md                  # 双线方案（历史决策，含收缩说明）
│   └── company_profile-schema-v1.md  # 条件档案 schema（已暂缓）
├── scripts/                      # 护栏回归自测 + 实跑脚本
├── knowledge/                    # 预留：领域知识沉淀（后续版本）
└── reports/                      # 生成的报告（默认不入库）
```

## 架构

文献检索链路（`Process.sequential`）：

- **代码采集（资料员，不经 LLM）**：多源检索 → 解析 → 去重 → 质量过滤（中文按北大核心白名单）→ 均衡 → 生成 TSV 与注入上下文；
- **分析员**：归纳研究现状、识别研究空白（须分别梳理中文与英文进展）；
- **撰稿员**：产出结构化 markdown 报告（**不负责生成文献表**）；
- **代码对账**：写稿后剥离伪造引用（URL + DOI 两道闸口），追加代码生成的文献表。

> 检索员角色已移除：检索由代码完成，Agent 无需复述代码已拿到的结果——
> 实测该角色在无工具时会编造文献清单，是假引用的源头之一。

## 路线图

- [x] v0.1 文献检索 + 市场调研（CrewAI 多角色，文献表代码生成、可溯源）
- [x] 记忆库 TTL 分级复审（user 90 / project 30 / domain 365 天，过期降权不删除）
- [x] v0.2 可溯源护栏补齐（DOI 对账 + 移除检索员角色）；双线实跑后收缩为文献检索单线
- [ ] 检索链路封装为一条可复用的工作流（配置化 / 一条命令跑完整链路）
- [ ] 接入 `knowledge/` 领域知识库（环境工程 / 污水处理术语、个人项目语境）
- [ ] 申请书「梳理」模块（立项依据三段式、研究内容→目标→关键科学问题拆解）
- [ ] 申请书「撰写」模块（对接修订 / 批注留痕纪律，输出可进 Word 修订模式）
- [ ] 学术论文撰写模块（大纲→综述→正文，复用 EasySlides / Agnes 出图）
- [ ] v1.0 Windows 桌面应用（CustomTkinter + PyInstaller 打包为可双击 .exe；先厚能力、最后包壳）

## 贡献

本仓库为公开项目，欢迎通过 **Issue** 提建议、通过 **Pull Request** 提交改进。
提交前请在 Issue 中说明改动意图，保持 `tools/` 与 `crews/` 的职责清晰。

## 免责声明

AI 生成的文献与报告仅供参考，引用前请逐条核对原始来源（点开 DOI 确认真实性）。
学术诚信第一：agent 是辅助工具，核心研究思路、立项依据必须由研究者本人完成。