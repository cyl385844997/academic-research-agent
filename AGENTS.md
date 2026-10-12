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
| `src/tools/literature_tool.py` | Semantic Scholar 真实文献检索（首选源，返回真实 DOI） |
| `src/tools/openalex_tool.py` | OpenAlex 备用文献检索（第二回退源） |
| `src/tools/crossref_tool.py` | Crossref 备用文献检索（第三回退源，已过滤审稿意见等非论文记录） |
| `src/tools/web_tool.py` | Web 检索（Tavily / DuckDuckGo） |
| `src/crews/literature_crew.py` | 论文检索三角色：检索员→分析员→撰稿员 |
| `src/crews/market_crew.py` | 市场调研三角色 |
| `src/main.py` | CLI 入口：`--mode literature|market|memory --topic "..."`；含三级文献源容错 |
| `src/tools/memory_store.py` | 记忆库存储层：分文件读写、召回打分、去重、冲突检测、归档 |
| `src/tools/memory_extract.py` | 记忆自动整理：LLM 提炼候选 + 语义裁决（矛盾 vs 改述） |
| `src/tools/memory_tool.py` | 记忆的 CrewAI 工具包装（Agent 运行时可检索/记待审） |
| `knowledge/` | 领域知识沉淀（v0.2 起），当前为空 |
| `reports/` | 生成报告，默认不入库 |
| `memory/` | 长期记忆库（操作者偏好与领域约定），**默认不入库** |

## 多源容错（文献检索）
`fetch_literature_grounded()` 依次尝试 **Semantic Scholar → OpenAlex → Crossref**，
任一成功即用；三者均失败时**如实报告失败原因**并给出解决建议，绝不编造文献。
实测：免费源在同一 IP 短时间内高频调用会被限流（S2 429 / OpenAlex 503），
因此不要在调试时反复轰炸单一源；需要稳定高频使用应配置官方 API key。

## 中文文献支持
- 检索结果统一标注 `语言:zh` / `语言:en`，文献表含「语种」列，报告分别梳理中英文进展。
- **语种以标题实际字符判定**（中文字符 ≥3 → zh），**不信任数据源的 language 字段**
  ——实测 OpenAlex 会把中文期刊标成 en，导致绕过后续过滤。
- 多源结果会**合并去重 + 中英文均衡**；Crossref 只取其英文记录（中文部分以灌水刊为主）。

## 中文质量判据：北大核心期刊白名单
- 白名单见 `src/tools/core_journals.py`（77 种），源自《北大〈中文核心期刊要目总览〉
  2023年版》第十版，由用户提供原始目录文档后**程序化提取并逐条核验**，无手工臆造。
- **修改白名单时必须核验**：刊名须与目录文档完全一致，否则不得加入。
  （首次编写时有 10 个刊名凭记忆添加、经核验发现并不存在于目录中，已全部剔除。）
- 中文文献不在白名单内 → 一律剔除；英文文献只做主题相关性过滤，不限制期刊。
- 期刊名比对需先归一化（去空格、"（中英文）"等），各源返回格式不一致。
- **不做知网/万方/维普爬取**：付费库无公开 API 且禁止爬虫，合规风险高。
  免费库中文覆盖有限，中文结果被清空属正常，会主动预警并建议人工补检知网。

## 文献质量把关（assess_quality）
- 黑名单（灌水期刊）**优先于**白名单判定——"工程管理与技术探讨"同时含白名单词
  "工程管理"与黑名单整词，必须先判黑名单，否则会把灌水刊误放行。
- 剔除后若过滤比例 ≥40% 或全部被滤掉，**主动向用户预警**并建议换检索词，
  不闷头输出低质文献。
- 修改期刊名单时注意：白名单用于保护中文核心/权威刊，黑名单用于剔除灌水刊，
  两者都会随期刊生态变化而需定期更新。

## 记忆库（memory/）

让 Agent 记住操作者的偏好与领域约定，避免每次都重复纠正。

### 目录结构
```
memory/
  entries/     一条记忆一个文件（YAML frontmatter + 正文），可直接用编辑器改
  daily/       每日会话日志（append-only），refresh 的提炼素材
  archive/     被覆盖/删除的历史版本（可回溯）
  pending.md   待人工裁决的记忆提案
```

### 核心设计原则（改代码前必读）
1. **LLM 只提议，不直接落库**。`memory_extract.extract_candidates()` 产出候选，
   经语义裁决后分流：`new`/`supplement` 才可能入库；`same`（与既有重复）、
   `conflict`（口径相悖）、`unknown`（判不准）一律写入 `pending.md` 等人工裁决。
   理由与「可溯源铁律」同源：模型误判的记忆一旦自动落库，会持续污染后续所有输出。
2. **`refresh` 默认是演练**，须显式 `--confirm` 才真正写库。
3. **冲突熔断**：同一议题（topic_key 匹配）出现相悖口径时，程序不自动择一，
   标记 conflict 交人工裁决。
4. **词面相似度不能判断语义**（实测：`高水位=满管流` vs `高水位=地下水入渗`
   得分 0.48，**高于**真正的重复对 0.41）。故相似度只用于缩小范围，
   矛盾/重复判定必须由 LLM 完成（`adjudicate()`）。
5. **`always` 由 LLM 判断**（「换个主题还成立吗」），不按 kind 一刀切——
   否则主题性事实会污染每次输出。
6. **凭证不入库**：`_has_secret()` 拦截 `ghp_`/`sk-`/AKIA/password/token 等特征，
   命中即丢弃。
7. **不静默覆盖**：更新/删除都先转 `archive/`，可回溯。
8. **local-first**：全部落本地，`.gitignore` 排除，不上传任何服务。

### 常用命令
```bash
python src/main.py --mode memory --topic "高水位"        # 按主题召回
python src/main.py --mode memory --topic "list"          # 列出全部
python src/main.py --mode memory --topic "stats"         # 统计
python src/main.py --mode memory --topic "log <要点>"    # 记一条会话日志
python src/main.py --mode memory --topic "refresh"       # 自动提炼（演练）
python src/main.py --mode memory --topic "refresh" --confirm   # 真正落库
python src/main.py --mode memory --topic "add <正文>"    # 手动加一条偏好
python src/main.py --mode memory --topic "pending"       # 查看待审提案
python src/main.py scripts/selftest_memory.py            # 自测（22 项）
```

### 如何影响输出
`main.py` 在 literature / market 模式下用 `build_memory_block(topic)` 按主题召回，
把结果作为 `memory=` 参数注入 Crew 的 context，措辞为
「必须遵守，优先于你的通用写作习惯」。召回为空时返回空串，不影响主流程。

## 硬性约束：不得让 LLM 生成文献表
任何改动都不得让 LLM 负责「列出参考文献/来源链接」。文献表一律由
`main.py` 调用真实学术库 → 解析 → 代码写出。见下方「可溯源铁律」。

## 可溯源铁律的实现方式（重要）
**文献表 / 来源表一律由代码生成，LLM 绝不参与其生成。**
- `main.py` 先直接调用检索工具获取真实记录 → 解析 → 写出权威 TSV；
- 真实结果作为上下文注入 Crew，Agent **只做分析**，并在任务中明确禁止编造文献/来源；
- 报告生成后，代码剥离 Agent 可能夹带的伪造表格，追加由真实数据生成的表格。
- 任何改动都不得让 LLM 负责「列出参考文献」这件事，否则会出现
  「真实 DOI 指向错误论文」或「DOI 根本不存在」的编造事故。

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
