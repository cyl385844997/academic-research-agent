"""学术前期研究 Agent - 入口 CLI。

用法：
  python src/main.py --mode literature --topic "side-stream EBPR wet weather overflow"
  python src/main.py --mode market    --topic "AI 基金申请书 产品 2026"

依赖（在项目根目录执行）：
  pip install -r requirements.txt
  cp .env.example .env   # 然后填入你的 API key
"""
import os
import argparse

import dotenv

dotenv.load_dotenv()

from langchain_openai import ChatOpenAI

from src.crews.literature_crew import build_literature_crew
from src.crews.market_crew import build_market_crew
from src.tools.literature_tool import literature_search
from src.tools.web_tool import web_search


def get_llm():
    """构造 LLM。默认 OpenAI；若配置 OPENAI_BASE_URL 则走兼容端点（如 Agnes）。"""
    kwargs = dict(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        api_key=os.getenv("OPENAI_API_KEY", ""),
        temperature=0.3,
    )
    base = os.getenv("OPENAI_BASE_URL")
    if base:
        kwargs["base_url"] = base
    return ChatOpenAI(**kwargs)


def main():
    parser = argparse.ArgumentParser(description="学术前期研究 Agent（论文检索 / 市场调研）")
    parser.add_argument(
        "--mode",
        choices=["literature", "market"],
        required=True,
        help="literature=论文检索综述；market=市场/竞品调研",
    )
    parser.add_argument("--topic", required=True, help="研究主题 / 检索词")
    args = parser.parse_args()

    llm = get_llm()
    tools = [literature_search, web_search]

    if args.mode == "literature":
        crew = build_literature_crew(args.topic, llm, tools)
    else:
        crew = build_market_crew(args.topic, llm, tools)

    result = crew.kickoff()
    print("\n===== 执行完成，报告见 reports/ 目录 =====\n")
    print(result)


if __name__ == "__main__":
    main()
