"""论文检索 Crew：检索员 → 分析员 → 撰稿员 三角色协作。

角色与任务在此文件中定义，便于后续迭代时直接调整。
"""
from crewai import Agent, Task, Crew, Process

from src.tools.literature_tool import literature_search
from src.tools.web_tool import web_search


def build_literature_crew(topic: str, llm, tools):
    researcher = Agent(
        role="文献检索员",
        goal=f"围绕「{topic}」检索真实、权威、近年的学术文献，确保每条记录可溯源（DOI/期刊）。",
        backstory=(
            "你是环境工程与污水处理领域的文献检索专家，熟悉侧流生物增强、主流-侧流耦合、"
            "雨季溢流处理等方向。你只使用 Semantic Scholar 等真实学术数据库，绝不编造文献。"
        ),
        tools=tools,
        llm=llm,
        verbose=True,
    )
    analyst = Agent(
        role="文献分析员",
        goal=f"归纳「{topic}」的研究现状、主要方法、争议点与未解决的研究空白。",
        backstory="你擅长从大量文献中提炼脉络，识别研究缺口，并评估哪些方向具备立项价值。",
        tools=tools,
        llm=llm,
        verbose=True,
    )
    writer = Agent(
        role="学术撰稿员",
        goal="将检索与分析结果整理为结构化文献综述报告，并产出可粘贴的 TSV 文献表。",
        backstory=(
            "你熟悉中文学术写作规范，能按「研究背景→现状→缺口→本研究切入点」逻辑链组织内容，"
            "并生成带 DOI 的参考文献表。"
        ),
        llm=llm,
        verbose=True,
    )

    search_task = Task(
        description=(
            f"使用文献检索工具与 Web 检索工具，围绕「{topic}」收集不少于 15 篇真实文献。"
            f"优先近 5 年、高被引论文。输出每篇的标题/作者/年份/DOI/摘要要点。"
        ),
        expected_output="一份带 DOI 的真实文献清单（不少于 15 条），按相关性排序。",
        agent=researcher,
    )
    analyze_task = Task(
        description=(
            f"基于检索结果，分析「{topic}」的研究现状、主流技术路线、主要争议与未解决空白，"
            f"指出 2-3 个具备立项价值的方向。"
        ),
        expected_output="研究现状综述 + 研究空白清单 + 立项价值判断。",
        agent=analyst,
        context=[search_task],
    )
    write_task = Task(
        description=(
            f"撰写「{topic}」文献综述报告（markdown），结构：摘要、研究背景、现状梳理、"
            f"研究空白、参考文献（含真实 DOI）。同时附一份 TSV 文献表"
            f"（标题\\t年份\\t作者\\tDOI\\t期刊\\t被引）。"
        ),
        expected_output="literature_report.md + 文末 TSV 文献表。",
        agent=writer,
        context=[analyze_task],
        output_file="reports/literature_report.md",
    )

    return Crew(
        agents=[researcher, analyst, writer],
        tasks=[search_task, analyze_task, write_task],
        process=Process.sequential,
        verbose=True,
    )
