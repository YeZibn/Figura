---
name: figura-implementation-read
description: Read Figura's current implementation overview and verify relevant code and OpenSpec facts before discussing the architecture or next change; read-only.
---

# 读取 Figura 当前实现

用于回答“现在实现了什么、下一步做什么、某字段归谁、某流程如何运转”。从仓库根目录执行命令。此 skill 只读取；用户要更新总览时使用 `$figura-implementation-overview`，要写新 change 方案时使用 OpenSpec。

## 读取顺序

1. 读 `docs/figura-implementation-overview.md` 的状态、总图、组件、核心数据和流程；先确定用户问题涉及的模块。
2. 查看相关 `src/figura/` 代码和 `openspec/figura/openspec/specs/` 主规格。具体字段以实际类型、编解码及持久化读写代码核对；接口行为同时核对调用方和实现方。
3. 问题涉及进行中的 change 时，查看该 change 的 proposal、design、specs、tasks 和 `openspec status`；涉及历史决定时，按 change 名称查 archive。只打开相关文件。
4. 检查 `git status --short`。未提交代码可以描述为“当前工作树已实现”，但不能因此声称 change 已归档或验证已通过。
5. 设计草案 `docs/figura-architecture-design.md` 和旧版 `src/chartagent/` 仅在比较、迁移或兼容性问题中查阅。草案中的对象或字段不自动属于当前实现。

## 命令

```sh
git status --short
sed -n '1,240p' docs/figura-implementation-overview.md
rg --files src/figura
rg -n '^(class |def |    def )' src/figura
rg --files openspec/figura/openspec/specs
openspec store list --json
openspec list --json --store figura
openspec status --change <change-id> --json --store figura
rg --files openspec/figura/openspec/changes/archive | rg '<change-id>'
```

先通过 `openspec store list --json` 确定真实 store id，再替换示例中的 `figura`。`<change-id>` 是占位符，不要原样执行。代码搜索先限定相关模块，再打开具体文件。不要读取 `.env`、密钥或生成的会话数据。

## 回答规则

- **实现事实**：说明代码位置、字段 owner 和流转；必要时指出仅存在于工作树。
- **规格合同**：说明主规格或活动 change 的要求，以及与代码是否一致。
- **计划内容**：明确标记为计划，不画成已运行组件。
- **验证结果**：只引用本次实际执行或有明确来源的历史结果，注明时间范围。
- Overview 与代码冲突时，先按代码说明现状并指出总览待更新；不要在只读任务中改写文档。

输出围绕用户的问题给出结论和可核查路径，不复述完整 Overview。
