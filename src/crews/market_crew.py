"""市场 / 竞品调研 Crew：侦察员 → 分析员 → 撰稿员 三角色协作。

重要（可溯源铁律）：来源链接 / 产品清单由 main.py 依据检索工具的真实返回逐字生成，
撰稿员只负责分析与撰写，禁止自行编造任何链接或产品信息。
检索结果以 `search_results` 形式注入上下文，确保全程基于真实来源。
"""
from crewai import Agent, Task, Crew, Process

from src.tools.literature_tool import literature_search
from src.tools.web_tool import web_search


def build_market_crew(topic: str, llm, tools, search_results: str = ""):
    context_block = (
        f"## 真实检索结果（来自 Web 检索，含真实 URL，严禁编造、严禁替换）\n"
        f"{search_results}\n"
        f"（以上为可溯源的真实来源，撰稿时只能引用其中出现的产品/链接，URL 须逐字照抄）"
        if search_results else
        "（未预置检索结果，请使用 Web 检索工具获取真实来源，且所有 URL 必须来自工具返回）"
    )

    scout = Agent(
        role="市场情报侦察员",
        goal=f"围绕「{topic}」搜集市场上的相关产品、竞品、政策与用户反馈。",
        backstory="你擅长竞品分析与市场扫描，能区分产品定位、目标人群与核心功能。",
        tools=tools,
        llm=llm,
        verbose=True,
    )
    analyst = Agent(
        role="市场分析员",
        goal=f"分析「{topic}」的市场格局、主要玩家、功能同质化程度与差异化空白。",
        backstory="你擅长从真实信息中提炼市场结构与机会点。",
        llm=llm,
        verbose=True,
    )
    writer = Agent(
        role="调研报告撰稿员",
        goal="将调研结果整理为结构化市场分析报告。来源必须来自给定真实检索结果，逐字照抄。",
        backstory=(
            "你熟悉商业 / 产品分析报告的写法，结论清晰、有数据支撑。"
            "你严格遵循可溯源铁律：绝不编造来源，所有链接必须来自提供的真实检索结果。"
        ),
        llm=llm,
        verbose=True,
    )

    scout_task = Task(
        description=f"使用 Web 检索与文献检索，围绕「{topic}」搜集主要产品/竞品/政策，列出名称、定位、核心功能、适用人群。",
        expected_output="竞品 / 产品清单（含定位与功能要点）。",
        agent=scout,
    )
    analyze_task = Task(
        description=f"分析「{topic}」的市场格局、功能同质化程度、尚未被满足的差异化空白。\n\n{context_block}",
        expected_output="市场格局分析 + 差异化空白判断。",
        agent=analyst,
        context=[scout_task],
    )
    write_task = Task(
        description=(
            f"撰写「{topic}」市场调研报告（markdown），含：市场全景表、关键判断、"
            f"差异化机会、下一步建议。\n\n"
            f"【硬性约束】来源链接必须 100% 来自下方真实检索结果，逐字照抄 URL，"
            f"禁止改写、禁止新增任何未出现的来源。文末不要自行生成链接表——"
            f"系统会自动附加由真实检索结果生成的来源表。\n\n{context_block}"
        ),
        expected_output="市场调研报告 markdown（不含来源链接表）。",
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
