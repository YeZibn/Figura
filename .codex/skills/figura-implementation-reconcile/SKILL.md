---
name: figura-implementation-reconcile
description: Reconcile a completed or partial Figura change with code and observed verification, updating its per-change implementation record and index only.
---

# 回填 Figura 实际实现

在 Figura change 实现后，或用户明确要求核对“计划和实际做完的内容”时使用。本 skill 将实现记录对齐到代码证据；不实现功能，也不替代 OpenSpec 主规格同步或归档。

记录结构遵循 [方案写入 skill 的 Change 记录模板](../figura-implementation-plan/SKILL.md)。五部分是“概览与决定、实现合同、核心流程、实现对照、验证与交接”。回填时保留原计划和用户决策，再按字段、组件、API、状态及流程写出实际状态与差异。没有代码或验证证据时标为“未核实”，不得推断为完成。

## 命令与证据采集

从 Figura 仓库根目录执行。先确认 Figura store；只对支持 store 参数的 OpenSpec 命令传实际返回的 store id。

```sh
git status --short -- docs/figura-implementation-content.md docs/figura-implementation src/figura
rg -n "^##|^###" docs/figura-implementation-content.md
rg --files docs | rg '^docs/figura-implementation/'
openspec store list --json
openspec list --json --store figura
openspec status --change "change-id" --json --store figura
rg --files src/figura
rg -n "class |def |Provider|Run|Session|Checkpoint" src/figura
git diff --check -- docs/figura-implementation-content.md docs/figura-implementation/changes
git diff --cached --check -- docs/figura-implementation-content.md docs/figura-implementation/changes
```

使用实际 store id 替换示例中的 `figura`。只按 status 提供的路径读取活动 change；归档 change 用 archive 文件列表按名称定位。默认不重跑应用测试；用户明确要求本次复验时，再按对应实现的 focused test 命令执行并记录实际输出。不得复制旧测试结果来声称本次验证通过。

## 核对流程

1. 读取索引，跟随 change 链接打开详细记录。若目标仍以内嵌旧格式保存在 `figura-implementation-content.md`，在原章节内回填；除非用户要求整理/迁移，不顺带移动其他记录。
2. 检查相关 Figura OpenSpec 工件及 `../../../src/figura/` 代码，按记录合同比较计划与实际字段和行为。活动工件按 status 路径读取；归档工件按 archive 文件列表定位。
3. 只记录本次实际观察到的测试、构建和 OpenSpec validation 结果。区分历史记录和本次运行，不因回填而自动运行测试。
4. 逐项核对字段、组件、API、状态转换和流程步骤，标记“已实现 / 部分实现 / 未实现或延期 / 未核实”。仅在对应代码已检查时标“已实现”；仅在 OpenSpec 主规格及归档状态已确认时更新对应生命周期状态。
5. 更新目标 change 记录和索引行中的实施状态、OpenSpec 状态、简短交付摘要与链接。计划、当前代码、规格要求和差异分开记录；保留仍有效的用户决策及未实现计划。

## 数据与文件边界

- 只修改实现索引和目标 change 记录，不改代码、OpenSpec change 工件、主规格或归档目录。
- `$openspec-sync-specs` 用于 delta spec 到主规格的同步；`$openspec-archive-change` 用于归档。不要用本 skill 代替这两步。
- 若 change 仍活动、任务未完成或缺少验证结果，如实记录部分状态。若代码与计划冲突，说明差异及影响，不要静默把计划改写成“已确认”。
- 若核对发现还有待开发任务，报告差距并停留在回填，不继续实现。

完成后报告记录改了什么、计划与实现的差异、验证依据及未完成项。
