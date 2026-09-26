---
name: figura-implementation-read
description: Read Figura's implementation index, per-change record, code, and relevant OpenSpec context before discussing or planning work; read-only.
---

# 阅读 Figura 实现现状

在讨论新方向、编写方案或回答“目前实现/决定了什么”之前，整理 Figura 当前实现事实和已有决定。此 skill 只读取，不写文件。

## 读取方式

1. 先读 `../../../docs/figura-implementation-content.md` 的文档约定和 change 索引，再跟随目标 change 的链接读取详细记录。详细记录位于 `../../../docs/figura-implementation/changes/`。可用 `rg --files docs | rg '^docs/figura-implementation/'` 查看现有文件。
2. 当前 Provider、Run 记录可能仍以内嵌旧格式存在于索引文档中。若索引没有详细记录链接，按 change 标题定位对应的旧章节并只读；不要把新五部分模板误认为这些旧记录已经迁移。
3. 对“已实现”字段和行为，检查相关 `../../../src/figura/` 代码；不能把计划文档、OpenSpec 状态或历史测试记录当成代码实现证据。
4. 涉及行为合同或 OpenSpec change 时，执行 `openspec store list --json` 确认 Figura store，并对支持 store 参数的命令使用实际 store id（当前通常是 `figura`）。活动 change 路径以 status 输出为准；历史 change 从 archive 文件列表定位。
5. `docs/figura-architecture-design.md` 和 `src/chartagent/` 是参考材料。只有用户要求比较、迁移或兼容性分析时才深入读取；不能把参考内容自动当成 Figura 决策。

## 常用只读命令

从 Figura 仓库根目录执行：

```sh
git status --short -- docs/figura-implementation-content.md docs/figura-implementation src/figura
rg -n "^##|^###" docs/figura-implementation-content.md
rg --files docs | rg '^docs/figura-implementation/'
rg --files src/figura
rg -n "class |def |Provider|Run|Session|Checkpoint" src/figura
openspec store list --json
openspec list --json --store figura
openspec status --change "change-id" --json --store figura
```

OpenSpec store id 以查询结果为准。只读相关规格和工件；不要读取 `.env` 或打印密钥。

## 事实分类

按需要区分并给出来源：

- **当前实现**：从 `src/figura/` 代码核对到的行为和字段。
- **已确认决定**：用户明确确认且未被后续修订的选择。
- **计划/暂定**：尚未实现或仍属暂定的内容。
- **差异/待确认**：计划、OpenSpec 与当前代码间的冲突或信息缺口。

代码描述实际行为；主规格描述已同步的行为合同；活动 change 描述拟实现范围；实现记录索引说明各 change 的状态和入口。不要将这些事实合并成单一状态。实现记录模板见 [方案写入 skill](../figura-implementation-plan/SKILL.md)，其五部分为：概览与决定、实现合同、核心流程、实现对照、验证与交接。旧式内嵌记录若未迁移，应指出结构差距，但不要猜补或静默改写。

## 输出

围绕用户的问题给出现状、证据路径、计划与实现差异，以及真正阻碍后续方案的待确认项。没有重要歧义时直接给结论，不为套模板而提出问题。

不得修改实现索引、change 记录、OpenSpec 工件、代码或其他文件。用户要求写入新方案时使用 `$figura-implementation-plan`；要求按已完成实现回填时使用 `$figura-implementation-reconcile`。
