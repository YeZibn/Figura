---
name: figura-implementation-overview
description: Create or update Figura's single current-implementation overview after a change or on request, using code and OpenSpec evidence; edits only that overview document.
---

# 维护 Figura 实现总览

维护 `docs/figura-implementation-overview.md`，让读者快速看到当前实现的组件、数据所有权、关键流转和未完成部分。每次 change 实现后按事实增量更新；不生成逐 change 实现记录。新方案、任务和验收条件仍写入 OpenSpec。

## 执行边界

- 只编辑上述 Overview。发现代码、主规格或 change 之间的差异时，在总览标明状态和来源，并在交付时报告；不借此修改代码或 OpenSpec。
- 代码证明“工作树已实现”；主规格证明“当前规格”；归档目录证明“已归档”。任务勾选、proposal 和设计草案都不能单独证明实现或验证通过。
- 不读取 `.env`、API key、原始 provider 响应或本机会话数据。总览不得包含密钥、绝对运行路径、未脱敏 payload。
- 保留用户已有的工作树改动；先看 `git status` 和目标文件 diff，再更新目标文档。

## 证据采集命令

从 Figura 仓库根目录执行：

```sh
git status --short
git diff -- docs/figura-implementation-overview.md
rg --files src/figura
rg -n '^(class |def |    def )' src/figura
rg --files openspec/figura/openspec/specs
openspec store list --json
openspec list --json --store figura
openspec status --change <change-id> --json --store figura
rg --files openspec/figura/openspec/changes/archive | rg '<change-id>'
```

用 store list 的结果替换示例 store id；仅对活动 change 执行 `status`，并把 `<change-id>` 替换成实际名称。随后读取目标模块的模型、协调器、编解码、存储及调用代码，以及相应主规格和 change 工件。需要确认未提交代码的改动时，用 `git diff -- <相关文件>`；不要把 `HEAD` 当成工作树内容。若没有相关 change，省略 change 命令。

## 文档结构

保持以下五节，合计以易读的一份总览为目标；新增内容优先修改现有表和图，不为每个 change 加一套章节。

```markdown
# Figura 实现总览
> 更新日期：YYYY-MM-DD。范围：当前工作树；OpenSpec 状态单独注明。

## 1. 当前边界
一句话说明已落地能力；表格区分已实现、进行中和未实现的主要模块。

## 2. 组件与关系
一张 Mermaid 总图，节点为真实组件和持久化边界；一张组件表记录职责、源码入口、输入/输出。计划组件放在文字状态表，不接入实线运行路径。

## 3. 核心数据归属
按 Provider、Tool、Run/执行事实分组。每行一个核心对象或一组紧密相关字段，列出 owner、关键字段、持久化/公开边界和源码依据；不重复 OpenSpec 的完整字段规格。

## 4. 关键流转
用短步骤说明创建 Run、提交模型响应、工具执行与恢复、终态；复杂的跨组件流程最多补一张局部时序图。写明原子提交和未知结果处理。

## 5. 规格、change 与待完成
主规格链接、活动/归档 change 状态、主要未实现模块，以及本次核对的来源与验证情况。
```

## 更新方法

1. 读取现有 Overview 与 `git status`，确定本次 change 涉及哪些节点、字段和流程。首次创建时按上面五节建文档。
2. 对每个声称“已实现”的变化，至少核对定义、写入/调用路径和读取/恢复路径；对外字段还核对投影或隐私边界。示例：新增持久字段应核对 dataclass、codec、SQLite 写入和读取，而不只看任务清单。
3. 只更新受影响的图节点、组件行、数据行、流程步骤和 change 状态。字段名使用代码中的真实名称；说明 owner，不虚构未来对象。
4. 区分“代码存在于工作树”“主规格已同步”“change 已归档”“验证已运行”。未归档但任务全勾选时仍写“活动 change”。当前任务没有运行测试时写“本次未运行应用测试”，不要复制历史结果作为本次结果。
5. 检查图的箭头与实际调用关系一致、表格没有孤立字段、链接存在、状态描述一致。执行：

```sh
git diff --check -- docs/figura-implementation-overview.md
git diff -- docs/figura-implementation-overview.md
```

最后简述更新了哪些架构事实、依据、未核实处及本次实际执行的检查。不要为了填满总图加入低层实现细节；详细约束链接到主规格或归档 change。
