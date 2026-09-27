---
name: git-commit-workspace
description: 快速总结当前工作区改动，生成带 Conventional Commit scope 的中文提交信息，并在用户要求时提交到本地。
---

# 快速整理并提交工作区改动

在用户明确要求提交或调用本 Skill 时，将当前工作区中同一项工作的改动提交到本地。只要求拟定提交信息时，不执行提交。

提交主题使用 `<type>(<scope>): <中文摘要>`，例如 `refactor(run-store): 拆分运行时持久化职责`。根据改动选择 `feat`、`fix`、`refactor`、`docs`、`test`、`chore` 等类型；`scope` 用简短、具体的英文 kebab-case 能力名，摘要说明结果。

## 流程

1. 快速查看 `git status --short`、`git diff --stat`、`git diff --cached --stat`，必要时读取相关 diff 和新文件，确认改动范围并拟定提交主题。检查是否混入密钥、`.env`、会话数据、生成文件或明显无关的工作；无法安全区分时说明原因并停止提交。
2. 默认只运行 `git diff --check`。不为提交例行运行 pytest、前端构建、smoke 或 OpenSpec 校验；仅在用户明确要求，或已发现具体问题必须核实时，才运行相应检查。不要把未运行的测试写成已通过。
3. 用明确的相关路径执行 `git add -- <paths>`，避免 `git add -A`。简要确认暂存范围；如有明显无关或敏感内容，停止提交。使用拟定主题执行 `git commit`。非小改动可用一两句正文概括主要变化，无需固定模板。
4. 查看 `git status --short` 和最新提交，简要报告提交哈希、主题、实际检查结果及剩余未提交改动。

只提交本地，不执行 `git push`。未经用户明确要求，不执行 `commit --amend`、`reset`、`rebase`、删除文件或修改已有改动。工作区干净时直接报告没有可提交改动。
