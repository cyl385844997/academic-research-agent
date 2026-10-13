"""前置检查闸门：跑任何检索工作流之前先过这一关。

对应 Skill 的「Mandatory Load Order」——非零退出即停止，不要修复、不要绕过。
检查项按「最可能挡住后续执行」排序：

  1. 项目根可定位（ARA_HOME 或默认路径）
  2. 项目关键文件齐全
  3. .env 存在且含 LLM 凭据
  4. 当前 Python 能导入项目依赖（crewai）
  5. Skill 自带的核验器可用
  6. 中文检索前置：cnki-mcp（仅当主题含中文时提示）

用法：
  python preflight.py                # 基础检查
  python preflight.py --topic "排水管网"   # 附带中文检索前置提示
  python preflight.py --deep         # 额外跑项目三套护栏/质量自测
"""
import os
import subprocess
import sys

FAILS = []
WARNS = []


def ok(msg):
    print(f"  [OK]   {msg}")


def warn(msg):
    WARNS.append(msg)
    print(f"  [WARN] {msg}")


def fail(msg, how):
    FAILS.append(msg)
    print(f"  [FAIL] {msg}")
    print(f"         处理：{how}")


def main():
    argv = sys.argv[1:]
    topic = None
    if "--topic" in argv:
        i = argv.index("--topic")
        topic = argv[i + 1] if i + 1 < len(argv) else ""
    deep = "--deep" in argv

    print("=== 前置检查 ===")

    # 1) 项目根
    ara = os.getenv("ARA_HOME") or os.path.join(os.path.expanduser("~"),
                                                 "academic-research-agent")
    if not os.path.isdir(ara):
        # Skill 目录结构：<repo>/skills/traceable-research/scripts/ → 上三级是仓库根
        ara = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                           "..", "..", ".."))
    if not os.path.isdir(os.path.join(ara, "src")):
        fail(f"未找到项目根（当前尝试：{ara}）",
             "clone https://github.com/cyl385844997/academic-research-agent "
             "后 export ARA_HOME=<其根目录>")
        print("\n结论：不通过")
        return 2
    ok(f"项目根：{ara}")

    # 2) 关键文件
    must = [
        ("src/main.py", "CLI 入口"),
        ("src/tools/core_journals.py", "北大核心白名单"),
        ("skills/traceable-research/scripts/verify_report.py", "核验器"),
    ]
    for rel, desc in must:
        p = os.path.join(ara, rel)
        if os.path.exists(p):
            ok(f"{desc}：{rel}")
        elif "旧路径" not in desc:
            warn(f"{desc}缺失：{rel}")

    # 3) .env
    env_path = os.path.join(ara, ".env")
    if not os.path.exists(env_path):
        fail("缺少 .env", f"cp {os.path.join(ara, '.env.example')} {env_path} "
                          "并填入 OPENAI_API_KEY")
    else:
        has_key = False
        has_base = False
        try:
            for line in open(env_path, encoding="utf-8"):
                line = line.strip()
                if line.startswith("OPENAI_API_KEY=") and len(line.split("=", 1)[1].strip()) > 8:
                    has_key = True
                if line.startswith("OPENAI_BASE_URL=") and line.split("=", 1)[1].strip():
                    has_base = True
        except OSError:
            pass
        if has_key:
            ok(".env 含 OPENAI_API_KEY")
        else:
            fail(".env 里没有可用的 OPENAI_API_KEY", "编辑 .env 填入真实 key")
        if not has_base:
            warn("未设置 OPENAI_BASE_URL——受限网络下将无法连通 LLM。"
                 "已验证可用：https://apihub.agnes-ai.com/v1")

    # 4) 依赖：当前解释器缺 crewai 只算提示——工作流命令本来就用项目 venv 跑；
    #    只要项目 venv 里有 crewai 就能继续。全都没有才是阻断。
    def _has_crewai(py):
        try:
            r = subprocess.run([py, "-c", "import crewai;print(crewai.__version__)"],
                               capture_output=True, text=True, timeout=60)
            return (r.returncode == 0, (r.stdout or "").strip())
        except Exception:  # noqa: BLE001
            return (False, "")

    venv_py = os.path.join(ara, ".venv", "Scripts", "python.exe")
    if os.name != "nt":
        venv_py = os.path.join(ara, ".venv", "bin", "python")
    venv_ok, venv_ver = (False, "")
    if os.path.exists(venv_py):
        venv_ok, venv_ver = _has_crewai(venv_py)
        if venv_ok:
            ok(f"项目虚拟环境可用：{venv_py}（crewai {venv_ver}）")
        else:
            fail("项目 .venv 存在但缺少 crewai",
                 f"{venv_py} -m pip install -r requirements.txt")
    else:
        warn(f"未找到项目虚拟环境（{venv_py}）——工作流命令需要它")

    cur_ok, cur_ver = _has_crewai(sys.executable)
    if cur_ok:
        ok(f"当前解释器可用（crewai {cur_ver}）")
    elif venv_ok:
        warn("当前解释器缺 crewai——执行工作流命令时请改用上面的项目虚拟环境解释器")
    else:
        fail("当前解释器与项目虚拟环境都缺 crewai",
             "pip install -r requirements.txt 后重试")

    # 5) 本 Skill 的核验器
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    verifier = os.path.join(skill_dir, "verify_report.py")
    if os.path.exists(verifier):
        ok(f"核验器就位：{verifier}")
    else:
        fail("核验器缺失", "确认 Skill 目录完整（scripts/verify_report.py）")

    # 6) 中文检索前置：cnki-mcp 可能装在 ~ 下，也可能是项目的同级目录
    if topic and any("\u4e00" <= ch <= "\u9fff" for ch in topic):
        candidates = [os.path.join(os.path.expanduser("~"), "cnki-mcp"),
                      os.path.abspath(os.path.join(ara, "..", "cnki-mcp"))]
        if any(os.path.isdir(c) for c in candidates):
            warn("主题含中文：请确认 cnki-mcp 已完成知网认证初始化"
                 "（浏览器内授权）。未初始化时知网召回为 0，只能命中免费库")
        else:
            warn("主题含中文但未找到 cnki-mcp（查过 ~ 与项目同级目录）——"
                 "中文文献将只走免费库，核心刊覆盖有限")

    # 7) 可选深检
    if deep:
        print("\n=== 深度自测（护栏 / 质量过滤 / 记忆库）===")
        py = os.path.join(ara, ".venv", "Scripts", "python.exe")
        py = py if os.path.exists(py) else sys.executable
        for script in ("scripts/selftest_guardrails.py",
                       "scripts/selftest_quality_filter.py",
                       "scripts/selftest_memory.py"):
            p = os.path.join(ara, script)
            if not os.path.exists(p):
                warn(f"自测缺失：{script}")
                continue
            try:
                r = subprocess.run([py, p], cwd=ara, capture_output=True,
                                   text=True, timeout=180)
                tail = [ln for ln in (r.stdout or "").splitlines() if "结果" in ln]
                if r.returncode == 0:
                    ok(f"{script} 通过" + (f"（{tail[-1].strip()}）" if tail else ""))
                else:
                    fail(f"{script} 未通过", "先修自测再继续——护栏失效会让编造引用重新流入")
            except subprocess.TimeoutExpired:
                warn(f"{script} 超时（>180s）")

    print("\n" + "=" * 46)
    if FAILS:
        print(f"结论：不通过（{len(FAILS)} 项阻断）：" + "；".join(FAILS))
        return 2
    print(f"结论：通过（{len(WARNS)} 项提示）")
    for w in WARNS:
        print(f"  · {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())