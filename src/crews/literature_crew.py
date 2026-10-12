"""论文检索 Crew：检索员 → 分析员 → 撰稿员 三角色协作。

重要（可溯源铁律）：参考文献 / TSV 文献表由 main.py 依据检索工具的真实返回
逐字生成，撰稿员只负责分析与撰写，禁止自行编造任何文献。
检索结果以 `search_results` 形式注入上下文，确保全程基于真实文献。
"""
from crewai import Agent, Task, Crew, Process

from src.tools.literature_tool import literature_search
from src.tools.web_tool import web_search


def build_literature_crew(topic: str, llm, tools, search_results: str = "",
                          memory: str = ""):
    # 把真实检索结果作为硬上下文注入分析与撰写环节
    context_block = (
        f"## 真实检索结果（来自真实学术数据库，含真实 DOI，严禁编造、严禁替换）\n"
        f"{search_results}\n"
        f"（以上为可溯源的真实文献，撰稿时只能引用其中出现的论文，DOI/标题须逐字照抄。\n"
        f" 注意区分语种：标注 语言:zh 的是中文文献，语言:en 的是英文文献。\n"
        f" 分析时需分别说明中文研究与英文研究的进展差异，综述中应同时覆盖两类文献。）"
        if search_results else
        "（未预置检索结果，请使用文献检索工具获取真实文献，且所有 DOI 必须来自工具返回）"
    )
    # 长期记忆：操作者偏好与领域约定（block 自带标题，此处只拼接）
    if memory:
        context_block += f"\n\n{memory}"

    researcher = Agent(
        role="文献检索员",
        goal=f"围绕「{topic}」检索真实、权威、近年的学术文献，确保每条记录可溯源（DOI）。",
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
        goal=(
            f"基于真实检索结果，归纳「{topic}」的研究现状、主流技术路线、争议与未解决空白。"
            f"需分别梳理中文文献与英文文献的研究进展，并对比二者差异。"
        ),
        backstory=(
            "你擅长从真实文献中提炼脉络，识别研究缺口，并评估哪些方向具备立项价值。"
            "你熟悉环境工程/污水处理领域的中英文文献生态，能识别中文期刊与英文顶刊的证据权重差异。"
        ),
        llm=llm,
        verbose=True,
    )
    writer = Agent(
        role="学术撰稿员",
        goal="将分析结果整理为结构化文献综述报告。参考文献必须来自给定真实检索结果，逐字照抄。",
        backstory=(
            "你熟悉中文学术写作规范。你严格遵循可溯源铁律：绝不编造文献，"
            "所有引用必须来自提供的真实检索结果，标题/作者/DOI 须逐字照抄，不得新增未出现的文献。"
        ),
        llm=llm,
        verbose=True,
    )

    search_task = Task(
        description=(
            f"使用文献检索工具，围绕「{topic}」收集真实文献（优先近 5 年、高被引）。\n"
            f"若上方已提供检索结果，请直接采用并核对；否则自行检索不少于 15 篇。\n"
            f"输出每篇的标题/作者/年份/DOI/摘要要点，并确保 DOI 真实可溯源。"
        ),
        expected_output="一份带真实 DOI 的文献清单。",
        agent=researcher,
    )
    analyze_kwargs = {}
    if not search_results:
        analyze_kwargs["context"] = [search_task]

    analyze_task = Task(
        description=(
            f"基于检索结果，分析「{topic}」的研究现状、主流技术路线、主要争议与未解决空白，"
            f"指出 2-3 个具备立项价值的方向。"
            f"须分别梳理中文文献与英文文献的研究进展，并指出两者的差异与互补关系。\n\n{context_block}"
        ),
        expected_output="研究现状综述（含中英文对比）+ 研究空白清单 + 立项价值判断。",
        agent=analyst,
        **analyze_kwargs,
    )
    write_task = Task(
        description=(
            f"撰写「{topic}」文献综述报告（markdown），结构：摘要、研究背景、现状梳理"
            f"（含中文研究进展与英文研究进展两部分）、研究空白、具备立项价值的研究方向。\n\n"
            f"【硬性约束】参考文献必须 100% 来自下方真实检索结果，逐字照抄标题/作者/DOI，"
            f"禁止改写、禁止新增任何未出现的文献。文末不要自行生成 TSV——"
            f"系统会自动附加由真实检索结果生成的文献表。\n\n{context_block}"
        ),
        expected_output="文献综述报告 markdown（不含 TSV 文献表）。",
        agent=writer,
        context=[analyze_task],
        output_file="reports/literature_report.md",
    )

    if search_results:
        # 检索已由代码完成（fetch_literature_grounded），**不设「文献检索员」角色**。
        # 实测（2026-10-12）：tools=[] 时该角色会凭参数记忆编一份文献清单，
        # 经 context 传给分析员/撰稿员，是正文假引用的源头之一；且其产出无法对账。
        # 资料员/研究员分工铁律：检索由代码持有，LLM 只分析已保存的数据。
        return Crew(
            agents=[analyst, writer],
            tasks=[analyze_task, write_task],
            process=Process.sequential,
            verbose=True,
        )

    return Crew(
        agents=[researcher, analyst, writer],
        tasks=[search_task, analyze_task, write_task],
        process=Process.sequential,
        verbose=True,
    )
