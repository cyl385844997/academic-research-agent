# academic-research-agent

> 学术前期研究 Agent —— 聚焦「论文检索」与「市场 / 竞品调研」等科研前期工作，基于 CrewAI 多角色协作，输出可溯源、可粘贴的结构化报告。

本仓库是逐步迭代的个人 / 团队项目。第一版只做**前期工作**（文献检索 + 市场调研），
不生成申请书全文、不写论文全文。垂直领域（环境工程 / 污水处理）的知识沉淀留到后续版本。

## 为什么做这个

市面上已有 40+ 款课题申报 / 学术写作 AI 工具，但普遍存在两个问题：

1. **参考文献不可溯源**：通用大模型会编造 DOI / 期刊。本 agent 强制「文献表由代码从真实学术库抓取生成」，LLM 只做分析，从机制上杜绝编造。
2. **缺乏个人 / 领域语境**：通用 SaaS 生成的本子没有「你自己的研究积累」。本项目的 `knowledge/` 目录预留用于沉淀领域知识与个人项目材料（后续版本）。

## 可溯源铁律（核心设计）

**文献表 / 来源表一律由代码生成，LLM 绝不参与其生成。**

- `main.py` 先依次调用真实学术库 → 解析 → 写出权威 TSV；
- 真实结果作为上下文注入 Crew，Agent **只做分析**，任务中明确禁止编造文献；
- 报告生成后，代码剥离 Agent 可能夹带的伪造表格，追加由真实数据生成的表格。

> 实测记录：早期版本让 LLM 自己生成文献表，结果出现「真实 DOI 指向完全不同的论文」
> 甚至「DOI 根本不存在」的情况。改为代码生成后，抽检 14/14 条 DOI 与官方库完全一致。

## 能力边界（v0.1）

| 模块 | 模式 | 说明 |
|------|------|------|
| 论文检索 | `--mode literature` | 检索员→分析员→撰稿员 三角色，产出文献综述报告 + TSV 文献表（含真实 DOI） |
| 市场调研 | `--mode market` | 侦察员→分析员→撰稿员 三角色，产出市场 / 竞品格局分析报告 |

**文献数据源三级容错**（均免 key，任一成功即用）：

| 顺序 | 数据源 | 说明 |
|:---:|---|---|
| 1 | Semantic Scholar | 覆盖 2 亿+ 论文，主力源 |
| 2 | OpenAlex | S2 限流(429)时回退 |
| 3 | Crossref | DOI 注册库，已过滤审稿意见等非论文记录 |

三者均失败时**如实报告失败原因并给出建议，绝不编造文献**。

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
| `TAVILY_API_KEY` | 可选，启用更稳定的 Web 检索；不填则回退 DuckDuckGo（免 key） |

> ⚠️ LLM 必须支持 **function calling**（工具调用），CrewAI 的检索工具依赖此能力。
> 可用 `curl <BASE_URL>/models` 查看端点支持的模型名。

## 用法

```bash
# 论文检索与综述
python src/main.py --mode literature --topic "side-stream EBPR wet weather overflow"

# 市场 / 竞品调研
python src/main.py --mode market --topic "AI 基金申请书 产品 2026"
```

执行完成后，报告生成在 `reports/` 目录：

- `literature_report.md` / `market_report.md` —— 分析报告
- `literature_references.tsv` / `market_references.tsv` —— 真实文献表（**可直接粘贴进 Excel**）

## 目录结构

```
academic-research-agent/
├── README.md
├── AGENTS.md                     # 面向 AI agent / 协作者的项目说明书
├── requirements.txt
├── .env.example
├── .gitignore
├── src/
│   ├── main.py                   # CLI 入口 + 多源容错 + 文献表生成
│   ├── tools/
│   │   ├── literature_tool.py    # Semantic Scholar 文献检索
│   │   ├── openalex_tool.py      # OpenAlex 备用文献检索
│   │   ├── crossref_tool.py      # Crossref 备用文献检索
│   │   └── web_tool.py           # Web 检索（Tavily / DuckDuckGo）
│   └── crews/
│       ├── literature_crew.py    # 论文检索三角色
│       └── market_crew.py        # 市场调研三角色
├── knowledge/                    # 预留：领域知识 / 个人项目材料沉淀（后续版本）
└── reports/                      # 生成的报告（默认不入库）
```

## 架构

每个 Crew 由三个角色顺序协作（`Process.sequential`）：

- **检索员 / 侦察员**：调用工具收集原始资料（真实文献 + 网络信息）。
- **分析员**：归纳现状、识别研究空白或市场差异化机会。
- **撰稿员**：产出结构化 markdown 报告（**不负责生成文献表**）。

文献表由 `main.py` 在 Crew 之外用代码生成并追加，保证可溯源。

## 路线图

- [x] v0.1 论文检索 + 市场调研（CrewAI 多角色，文献表代码生成、可溯源）
- [ ] v0.2 接入 `knowledge/` 领域知识库（环境工程 / 污水处理术语、个人项目语境）
- [ ] v0.3 申请书「梳理」模块（立项依据三段式、研究内容→目标→关键科学问题拆解）
- [ ] v0.4 申请书「撰写」模块（对接修订 / 批注留痕纪律，输出可进 Word 修订模式）
- [ ] v0.5 学术论文撰写模块（大纲→综述→正文，复用 EasySlides / Agnes 出图）
- [ ] v1.0 Windows 桌面应用（CustomTkinter + PyInstaller 打包为可双击 .exe；先厚能力、最后包壳）

## 贡献

本仓库为公开项目，欢迎通过 **Issue** 提建议、通过 **Pull Request** 提交改进。
提交前请在 Issue 中说明改动意图，保持 `tools/` 与 `crews/` 的职责清晰。

## 免责声明

AI 生成的文献与报告仅供参考，引用前请逐条核对原始来源（点开 DOI 确认真实性）。
学术诚信第一：agent 是辅助工具，核心研究思路、立项依据必须由研究者本人完成。
