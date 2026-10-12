"""市场 / 竞品调研 Crew：侦察员 → 分析员 → 撰稿员 三角色协作。

与文献检索 Crew 的差异
----------------------
1. 来源**按可信度分层**：只有 A/B 级可作为结论依据，C 级须标注「社区反馈，待核实」；
2. 产品名均为**候选**（从标题/URL 抽取），禁止断言「某公司已推出 X 产品」；
3. 报告需覆盖**技术路线**维度，不只是产品罗列。

可溯源铁律：来源表与产品对比表由 main.py 依据 Web 工具真实返回生成，
撰稿员只负责分析与撰写，禁止自行编造任何链接、产品名或功能。
"""
from crewai import Agent, Task, Crew, Process


def build_market_crew(topic: str, llm, tools, search_results: str = "",
                      memory: str = ""):
    context_block = (
        f"## 真实检索结果（含可信度分级，严禁编造产品名/链接/功能）\n"
        f"{search_results}\n"
        f"（以上为可溯源的真实来源。产品/机构名为**代码从标题与 URL 抽取的候选**，"
        f"非经核实；撰稿时只能引用表中出现的名称，URL 须逐字照抄）"
        if search_results else
        "（未预置检索结果，请使用 Web 检索工具获取真实来源；"
        "所有 URL 必须来自工具返回，产品名不得凭印象编造）"
    )
    # 长期记忆：操作者偏好与领域约定（block 自带标题，此处只拼接）
    if memory:
        context_block += f"\n\n{memory}"

    scout = Agent(
        role="市场情报侦察员",
        goal=(
            f"围绕「{topic}」搜集市场上的相关产品、竞品、技术方案、政策与用户反馈。"
            f"重点补全检索结果中缺失的维度（尤其是竞品名与技术路线）。"
        ),
        backstory=(
            "你擅长竞品分析与市场扫描，能区分产品定位、目标人群与核心功能。"
            "你知道只搜技术词搜不到具体产品，会主动从多角度补搜。"
            "**你绝不虚构产品名或公司名**——不确定的一律标注「待核实」。"
        ),
        tools=tools,
        llm=llm,
        verbose=True,
    )
    analyst = Agent(
        role="市场分析员",
        goal=(
            f"分析「{topic}」的市场格局、主要玩家、技术路线、功能同质化程度与差异化空白。"
            f"**必须按来源可信度分层结论**：A/B 级作为事实依据，C 级仅作参考并标注。"
        ),
        backstory=(
            "你擅长从真实信息中提炼市场结构与机会点。"
            "你对来源可信度敏感——会明确区分「官方发布的事实」与「社区的主观反馈」，"
            "不会把未核实的候选产品名当作确证事实。"
        ),
        llm=llm,
        verbose=True,
    )
    writer = Agent(
        role="调研报告撰稿员",
        goal="将调研结果整理为结构化市场分析报告。来源必须来自给定真实检索结果，逐字照抄。",
        backstory=(
            "你熟悉商业 / 产品分析报告的写法，结论清晰、有数据支撑。"
            "你严格遵循可溯源铁律：绝不编造来源，所有链接必须来自提供的真实检索结果。"
            "涉及产品/厂商的表述一律用「检索到」「据X来源」等措辞，避免断言未核实信息。"
        ),
        llm=llm,
        verbose=True,
    )

    scout_task = Task(
        description=(
            f"使用 Web 检索，围绕「{topic}」补搜主要产品/竞品/技术方案/政策，"
            f"列出名称、定位、核心功能、适用人群、收费模式。"
            f"注意从**多个角度**检索：中文产品名、国外竞品名、技术路线词、应用案例。\n"
            f"【严禁】虚构产品名或公司名；不确定的标注「待核实」。"
        ),
        expected_output="竞品 / 产品清单（含定位、功能要点，并注明来源可信度）。",
        agent=scout,
    )
    analyze_task = Task(
        description=(
            f"分析「{topic}」的市场格局、技术路线、功能同质化程度、尚未被满足的差异化空白。\n"
            f"【分层要求】只有 A/B 级来源（官方/学术/主流媒体）可作为结论依据；"
            f"C 级（社区）只能作为「用户反馈倾向」的旁证，须明确标注可信度不足。\n"
            f"若某个判断缺少 A/B 级来源支撑，必须明确说明「证据不足」。\n\n{context_block}"
        ),
        expected_output="市场格局分析 + 技术路线梳理 + 差异化空白判断（标注证据等级）。",
        agent=analyst,
        context=[scout_task],
    )
    write_task = Task(
        description=(
            f"撰写「{topic}」市场调研报告（markdown），含：\n"
            f"1. 市场全景（含技术路线分类）\n"
            f"2. 主要玩家与产品定位\n"
            f"3. 关键判断（逐条注明来源可信度等级）\n"
            f"4. 差异化机会与切入建议\n"
            f"5. 证据不足之处（诚实说明）\n\n"
        f"【硬性约束】\n"
        f"- 来源链接必须 100% 来自下方真实检索结果，逐字照抄 URL；\n"
        f"- 禁止改写、禁止新增任何未出现的来源；\n"
        f"- **正文内不得自行书写任何 http(s) 链接**：提及来源时只写「（检索到 X，见对比表）」"
        f"即可，真实链接由系统自动附加的对比表提供；\n"
        f"- 产品/机构名均为**候选**，措辞须用「检索到」而非断言；\n"
        f"- 文末不要自行生成对比表——系统会自动附加由代码生成的来源表。\n\n{context_block}"
        ),
        expected_output="市场调研报告 markdown（不含来源对比表）。",
        agent=writer,
        context=[analyze_task],
        output_file="reports/market_report.md",
    )

    return Crew(
        agents=[scout, analyst, writer],
        tasks=[scout_task, analyze_task, write_task],
        process=Process.sequential,
        verbose=True,
    )