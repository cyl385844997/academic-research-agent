# AGENTS.md — academic-research-agent

> 本文件面向 AI agent 与代码协作者。人类读者请看 README.md。

## 项目定位
垂直领域（环境工程 / 污水处理）的**学术前期研究 Agent**。
- v0.1（当前）：聚焦「论文检索」与「市场 / 竞品调研」两类前期工作，以 Python CLI 形态运行。
- 规划形态：**Windows 桌面应用**，内部逻辑仍由 Python + CrewAI 实现（GUI 为外壳，不重写核心）。

## 从 wisp-science 借鉴并内化的四条原则
1. **可溯源铁律（Evidence Capsules 思想）**
   任何检索 / 生成结果必须能回溯到原始来源。文献强制带真实 DOI；市场信息强制标注来源 URL。
   每份报告末尾附「参考文献 / 来源校验清单」。**绝不接受编造的文献或来源**——这是项目红线。
2. **Local-first & Bring Your Own Model**
   API key 仅存于本地 `.env`，绝不入库、绝不硬编码、绝不后台上传。模型端点可配置
   （OpenAI 或 Agnes 等 OpenAI 兼容端点，见 `.env.example` 的 `OPENAI_BASE_URL`）。
3. **Skills 模块化**
   能力以可复用模块组织（`src/tools/`、`src/crews/`），单一职责、自带说明，便于迭代与替换。
4. **MCP 科学数据库扩展（规划中）**
   未来数据源以 MCP server 封装（PubMed、GEO 及环境工程相关库），不写死在业务代码里。

## 目录职责
| 路径 | 职责 |
|------|------|
| `src/tools/literature_tool.py` | Semantic Scholar 真实文献检索（返回真实 DOI） |
| `src/tools/web_tool.py` | Web 检索（Tavily / DuckDuckGo） |
| `src/crews/literature_crew.py` | 论文检索三角色：检索员→分析员→撰稿员 |
| `src/crews/market_crew.py` | 市场调研三角色 |
| `src/main.py` | CLI 入口：`--mode literature|market --topic "..."` |
| `knowledge/` | 领域知识沉淀（v0.2 起），当前为空 |
| `reports/` | 生成报告，默认不入库 |

## 运行（开发期）
```bash
pip install -r requirements.txt
cp .env.example .env          # 填 OPENAI_API_KEY，或设 OPENAI_BASE_URL 指向 Agnes
python src/main.py --mode literature --topic "side-stream EBPR wet weather overflow"
python src/main.py --mode market    --topic "AI 基金申请书 产品 2026"
```

## 贡献约定
- 改动前先读本文件与 README，保持「可溯源铁律」「local-first」两条不变。
- 新增数据源走工具 / MCP 层，不污染 crews 业务逻辑。
- `reports/` 产物不入库（已在 `.gitignore`）。

## 安全与隐私红线
- 凭证只在本地 `.env`，已被 `.gitignore` 排除；任何情况下不提交 `.env`。
- 不接入任何会后台上传用户数据的服务。
- 模型可自托管 / 兼容端点，数据不出本机。

## 版本路线
- v0.1 ✅ 论文检索 + 市场调研（CrewAI，真实可溯源文献）
- v0.2 接入 `knowledge/` 领域知识沉淀
- v0.3 申请书「梳理」模块
- v0.4 申请书「撰写」模块（对接修订 / 批注留痕纪律）
- v0.5 学术论文撰写（复用 EasySlides / Agnes 出图）
- v1.x Windows 桌面应用（目标是可双击运行的 .exe）：Python 核心 + GUI 壳（倾向 CustomTkinter 画窗口、PyInstaller 打包）；**先厚能力、最后包壳**——开发期保持 CLI 便于调试，能力稳定后再套界面。
