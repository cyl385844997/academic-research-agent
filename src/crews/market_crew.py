"""市场 / 竞品调研 Crew：侦察员 → 分析员 → 撰稿员 三角色协作。

用于调研学术写作 / 申请书辅助类产品的市场格局与差异化空白。
"""
from crewai import Agent, Task, Crew, Process

from src.tools.literature_tool import literature_search
from src.tools.web_tool import web_search


def build_market_crew(topic: str, llm, tools):
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
        backstory="你擅长从零散信息中提炼市场结构与机会点。",
        tools=tools,
        llm=llm,
        verbose=True,
    )
    writer = Agent(
        role="调研报告撰稿员",
        goal="将调研结果整理为结构化市场分析报告。",
        backstory="你熟悉商业 / 产品分析报告的写法，结论清晰、有数据支撑。",
        llm=llm,
        verbose=True,
    )

    scout_task = Task(
        description=f"使用 Web 检索与文献检索，围绕「{topic}」搜集主要产品/竞品/政策，"
        f"列出名称、定位、核心功能、适用人群。",
        expected_output="竞品 / 产品清单（含定位与功能要点）。",
        agent=scout,
    )
    analyze_task = Task(
        description=f"分析「{topic}」的市场格局、功能同质化程度、尚未被满足的差异化空白。",
        expected_output="市场格局分析 + 差异化空白判断。",
        agent=analyst,
        context=[scout_task],
    )
    write_task = Task(
        description=f"撰写「{topic}」市场调研报告（markdown），含：市场全景表、关键判断、"
        f"差异化机会、下一步建议。",
        expected_output="market_report.md。",
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
