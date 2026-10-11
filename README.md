# academic-research-agent

> 学术前期研究 Agent —— 聚焦「论文检索」与「市场 / 竞品调研」等科研前期工作，基于 CrewAI 多角色协作，输出可溯源、可粘贴的结构化报告。

本仓库是逐步迭代的个人 / 团队项目。第一版只做**前期工作**（文献检索 + 市场调研），
不生成申请书全文、不写论文全文。垂直领域（环境工程 / 污水处理）的知识沉淀留到后续版本。

## 为什么做这个

市面上已有 40+ 款课题申报 / 学术写作 AI 工具，但普遍存在两个问题：

1. **参考文献不可溯源**：通用大模型会编造 DOI / 期刊。本 agent 的文献检索强制走 Semantic Scholar 真实学术数据库，返回真实 DOI。
2. **缺乏个人 / 领域语境**：通用 SaaS 生成的本子没有「你自己的研究积累」。本项目的 `knowledge/` 目录预留用于沉淀领域知识与个人项目材料（后续版本）。

## 能力边界（v0.1）

| 模块 | 模式 | 说明 |
|------|------|------|
| 论文检索 | `--mode literature` | 检索员→分析员→撰稿员 三角色，产出文献综述报告 + TSV 文献表（含真实 DOI） |
| 市场调研 | `--mode market` | 侦察员→分析员→撰稿员 三角色，产出市场 / 竞品格局分析报告 |

数据源：**Semantic Scholar API（真实文献）+ Web 检索（市场 / 政策 / 竞品）混合**。

## 安装

```bash
git clone <本仓库地址>
cd academic-research-agent
pip install -r requirements.txt
cp .env.example .env   # 然后编辑 .env 填入你的 API key
```

## 配置（.env）

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | LLM 密钥（默认 OpenAI） |
| `OPENAI_MODEL` | 模型名，默认 `gpt-4o-mini` |
| `OPENAI_BASE_URL` | 如需复用 Agnes 等 OpenAI 兼容端点，填此值（如 `https://apihub.agnes-ai.com/v1`） |
| `SEMANTIC_SCHOLAR_API_KEY` | 可选，提升文献检索速率 |
| `TAVILY_API_KEY` | 可选，启用更稳定的 Web 检索；不填则回退 DuckDuckGo（免 key） |

## 用法

```bash
# 论文检索与综述
python src/main.py --mode literature --topic "side-stream EBPR wet weather overflow"

# 市场 / 竞品调研
python src/main.py --mode market --topic "AI 基金申请书 产品 2026"
```

执行完成后，报告生成在 `reports/` 目录。

## 目录结构

```
academic-research-agent/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── src/
│   ├── main.py                 # CLI 入口
│   ├── tools/
│   │   ├── literature_tool.py  # Semantic Scholar 真实文献检索
│   │   └── web_tool.py         # Web 检索（Tavily / DuckDuckGo）
│   └── crews/
│       ├── literature_crew.py  # 论文检索三角色
│       └── market_crew.py      # 市场调研三角色
├── knowledge/                  # 预留：领域知识 / 个人项目材料沉淀（后续版本）
└── reports/                    # 生成的报告（默认不入库）
```

## 架构

每个 Crew 由三个角色顺序协作（`Process.sequential`）：

- **检索**：调用工具收集原始资料（真实文献 + 网络信息）。
- **分析**：归纳现状、识别研究空白或市场差异化机会。
- **撰稿**：产出结构化 markdown 报告，并保证参考文献带真实可溯源的 DOI。

## 路线图

- [ ] v0.2 接入 `knowledge/` 领域知识库（环境工程 / 污水处理术语、个人项目语境）
- [ ] v0.3 申请书「梳理」模块（立项依据三段式、研究内容→目标→关键科学问题拆解）
- [ ] v0.4 申请书「撰写」模块（对接你已有的修订 / 批注留痕纪律，输出可进 Word 修订模式）
- [ ] v0.5 学术论文撰写模块（大纲→综述→正文，复用 EasySlides / Agnes 出图）

## 贡献

本仓库为公开项目，欢迎通过 **Issue** 提建议、通过 **Pull Request** 提交改进。
提交前请在 Issue 中说明改动意图，保持 `tools/` 与 `crews/` 的职责清晰。

## 免责声明

AI 生成的文献与报告仅供参考，引用前请逐条核对原始来源（点开 DOI 确认真实性）。
学术诚信第一：agent 是辅助工具，核心研究思路、立项依据必须由研究者本人完成。
