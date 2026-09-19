---
name: git-commit-workspace
description: 分析当前工作区改动，生成带 Conventional Commit scope 的中文 Git 提交信息，执行必要校验并提交到本地；用户要求整理并提交当前改动时使用。
---

# 工作区 Git 提交

把当前工作区中属于同一项工作的改动整理成一个清晰、可追溯的本地 Git 提交。提交主题统一使用：

```text
<type>(<scope>): <中文摘要>
```

其中 `scope` 表示这次改动实际影响的能力范围，使用简短、具体的英文 kebab-case 名称，而不是笼统的系统归属或单个文件名。

例如：

```text
feat(prompt-assemble): 引入分层中文 Prompt 装配体系
fix(chart-measure): 修复柱状图基准线偏移
refactor(chart-segmentation): 重构轻量化图表拆解流程
feat(run-resume): 支持运行中断后的断点续行
docs(openspec-sync): 同步图表分析规格
```

## 适用边界

- 只有在用户明确要求提交、调用本 Skill，或明确说“写提交内容并提交”时，才执行 `git commit`。
- 用户只要求分析改动或拟定提交信息时，只输出候选信息和分析，不提交。
- 只提交本地，不执行 `git push`。
- 不擅自执行 `commit --amend`、`reset`、`rebase`、删除文件或修改用户已有改动；除非用户明确要求。
- 工作区干净时直接报告“没有可提交改动”，不要创建空提交。

## 提交类型与 scope

根据实际 diff 和用户意图判断，不根据文件名机械判断：

| type | 使用场景 |
| --- | --- |
| `feat` | 新增用户或系统能力 |
| `fix` | 修复错误行为、数据或边界条件 |
| `refactor` | 重构内部结构，预期行为不变 |
| `perf` | 性能、资源占用或吞吐优化 |
| `test` | 只增加或调整测试 |
| `docs` | 只修改文档、OpenSpec 或说明文字 |
| `build` | 构建、打包、依赖或运行配置变化 |
| `ci` | CI/CD 流程变化 |
| `chore` | 其他不改变产品行为的维护工作 |
| `revert` | 明确撤回某个已有提交 |

选择规则：

- scope 必须对应这次改动的具体能力或子系统，例如 `prompt-assemble`、`chart-segmentation`、`run-resume`、`gateway-idempotency`、`frontend-preview`。
- scope 使用小写英文和连字符，通常由“领域-能力”组成；必要时可以使用更具体的三段式名称，例如 `chart-measure-bars`。
- 不要把 scope 写成笼统的 `agent`、`backend`、`frontend` 或 `src`，除非改动确实没有更具体的能力边界。
- 不要直接使用文件路径、类名、Issue 编号或临时任务名作为 scope；scope 应能让读者从提交记录中理解改动内容。
- scope 不使用逗号、斜杠或多个并列范围。修改横跨多个领域时，选择主要用户价值或主要实现边界对应的一个 scope；如果是彼此独立的工作，应拆成多个提交。
- 测试和实现同时修改时，使用实现对应的 type/scope；只有测试本身变化时才使用 `test`。
- 新增能力即使同时重构了代码，也优先使用 `feat`；修复错误即使涉及结构调整，也优先使用 `fix`。
- 摘要使用简体中文、动宾结构、说明结果而不是罗列文件；保持简洁，通常不超过一行。

## 工作流程

### 1. 读取改动范围

先检查：

```bash
git status --short
git diff --stat
git diff --name-status
git diff --cached --stat
git ls-files --others --exclude-standard
git log -10 --pretty=format:'%h %s'
```

需要理解语义时读取相关 diff 和新文件内容。不要因为历史提交的格式没有 scope 就沿用旧格式；本 Skill 从现在开始使用 scoped subject。

重点确认：

- 改动是否属于一项连贯工作。
- 是否存在未完成、明显无关或属于用户的并行改动。
- 是否包含 `.env`、密钥、令牌、会话数据、缓存、临时输出或大体积生成文件。
- 是否有需要同步的 OpenSpec 或配置契约。

如果发现无法安全区分的无关改动、敏感文件或明显不完整的工作，先停止提交并说明具体路径；不要用 `git add -A` 掩盖问题。

### 2. 生成提交说明

根据 diff 生成一个 subject，并为非 trivial 改动生成正文：

```text
<type>(<scope>): <中文摘要>

- 说明主要行为变化或结构变化
- 说明重要的兼容性、配置或规格影响（如有）

验证：
- `<实际执行的验证命令>`
```

正文只写已从 diff 或命令结果确认的事实，不编造未执行的测试。纯小改动可以省略正文，但 subject 仍必须包含 scope。

### 3. 执行与改动相关的校验

至少执行：

```bash
git diff --check
```

根据改动范围追加校验：

- Python 或 Agent 改动：优先运行相关测试；无法准确缩小范围时使用 `conda run -n agent python -m pytest -q`。
- 前端改动：在 `frontend/` 运行 `npm run build` 和 `npm run smoke`。
- OpenSpec 改动：运行仓库支持的严格规格校验，例如 `openspec validate --specs --strict --no-interactive`；如果存在具体 change，也校验该 change。
- 仅提交信息、纯文档或不影响代码的说明变更，不为了形式运行无关的全量测试，但仍执行 `git diff --check`。

测试失败时不要把失败写成成功验证，也不要为了提交擅自修改测试或绕过失败。若失败与当前改动无关，报告失败命令和判断依据，让用户决定是否继续；有明显回归则停止提交。

### 4. 暂存并提交

用户已经明确授权本地提交时，不需要重复确认，但应在提交前在进度消息中给出最终 subject、scope、暂存路径和验证结果。

- 只使用明确解析出的相关路径执行 `git add -- <paths>`，不要默认使用 `git add -A`。
- 暂存后检查 `git diff --cached --stat`、`git diff --cached --check`，并确认没有敏感文件或无关改动。
- 使用上一步生成的 subject 和正文执行 `git commit`；安全处理引号和多行中文，不把 diff 中的未经转义内容拼进 shell。
- 提交后执行 `git status --short` 与 `git log -1 --pretty=format:'%h %s'`，确认提交成功且没有意外残留。

### 5. 汇报

成功后简要说明：

- 提交哈希和完整 subject。
- 使用的 type/scope 及其理由。
- 实际执行的验证命令及结果。
- 是否仍有未提交改动。

不要声称已经推送远程；本 Skill 默认只完成本地提交。
