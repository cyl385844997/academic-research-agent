# memory/ — 长期记忆库

让 Agent 记住你的偏好与领域约定，避免每次重复纠正。

> ⚠️ **本目录不入库**（见 `.gitignore`）。记忆内容含个人偏好与在办课题等私密上下文，
> 本仓库为 public，不应公开。仅目录说明与 `.gitkeep` 随仓库保留。

## 结构

```
memory/
  entries/     生效的记忆，一条一个文件
  daily/       每日会话日志（refresh 的提炼素材）
  archive/     被覆盖/删除的历史版本（可回溯）
  pending.md   待人工裁决的记忆提案
```

## 记忆长什么样

`entries/U-0001.md`：

```markdown
---
id: U-0001
kind: user          # user=你的偏好 / domain=领域口径 / project=在办事项
title: 交付偏好：给可粘贴表格
tags: [偏好, 交付]
topic_key: 交付格式  # 同议题的相悖口径会被检测为冲突
status: active      # active / superseded / rejected / draft
always: false       # true=每次都注入，不做相关性筛选
source: 用户长期偏好
---

预算表优先给可直接复制粘贴的 TSV，不要主动生成 .xlsx。
```

**你可以直接用记事本 / VSCode 改这些文件**，改完立即生效，无需重启。

## 怎么用

```bash
# 看看和某个主题相关的记忆
python src/main.py --mode memory --topic "高水位"

# 记一条本次会话要点（供日后自动提炼）
python src/main.py --mode memory --topic "log 用户要求：报告里实测值要脱敏"

# 从最近的会话日志自动提炼「值得长期记住」的信息（默认只演练）
python src/main.py --mode memory --topic "refresh"
python src/main.py --mode memory --topic "refresh" --confirm   # 确认落库

# 手动添加 / 查看 / 统计
python src/main.py --mode memory --topic "add 以后给我 TSV 表格，不要 xlsx"
python src/main.py --mode memory --topic "list"
python src/main.py --mode memory --topic "stats"
python src/main.py --mode memory --topic "pending"     # 查看待裁决提案
```

## 设计取向：为什么 LLM 不直接落库

自动提炼由 LLM 做，但**只提议、不直接写入生效记忆**：

| LLM 判定 | 处理 |
|---|---|
| 全新条目 / 对既有条目的补充 | 可入库 |
| 与既有记忆是同一件事 | 不新增，写入 `pending.md` 建议合并 |
| 与既有记忆口径相悖 | 冲突熔断，写入 `pending.md` 等人工裁决 |
| 判不准 | 一律转人工（宁缺毋滥） |

理由：模型会误判什么值得记、也会误判是否矛盾。一旦自动落库，**错误记忆会持续污染
后续所有输出**，而且你很难察觉它是什么时候进来的。人工确认一次的成本远低于
长期被一条错记忆误导。

另外三条硬性保护：

- **凭证不入库**：`ghp_`/`sk-`/AKIA/`password=` 等特征命中即丢弃。
- **不静默覆盖**：改写或删除都先转 `archive/`，可回溯。
- **冲突不自动择一**：同一议题出现两种口径时停下，交你裁定。

## 记忆如何影响输出

`literature` / `market` 模式运行时，程序按主题召回相关记忆，
以「必须遵守，优先于你的通用写作习惯」的措辞注入 Crew 上下文。
召回为空时直接跳过，不影响主流程。
