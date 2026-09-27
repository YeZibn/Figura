---
name: figura-implementation-overview
description: Maintain Figura's layered system overview and component documents from current code and OpenSpec evidence, including complete model field inventories and internal data flows. Use for Figura architecture documentation, not code implementation.
---

# 维护 Figura 分层系统文档

保持 `docs/figura-implementation-overview.md` 为全局入口：只说明大组件的职责、状态、跨组件内容流转和专题文档入口。各专题位于 `docs/figura/`，说明各自边界内的流程、模型关系、**每个收录模型的全部字段**、读写边界和不变量。专题集合不是预先封闭的目录：每次变化都要重新判断领域归属，必要时建立新的子文档。不要把细节重新堆进 Overview，也不要以每个 change 为单位增设章节。

## 范围与事实层级

- 新系统以 `src/figura/` 的当前工作树和 `openspec/figura/openspec/specs/` 为依据。`src/chartagent/` 和 chartagent store 只作明确标记的旧系统参考；`docs/figura-architecture-design.md` 是设计草案，不证明已实现。
- 分别标明“当前代码已存在”“主规格要求”“活动 change 设计中”“旧系统参考”“待决定”。未提交代码可写“当前工作树已存在”，不能写“已归档”；任务勾选不能单独证明实现或验证通过。
- 保留用户已有改动。先看 `git status --short` 和目标文件 diff。只编辑 Overview、`docs/figura/` 专题文档、必要导航链接，以及用户明确要求调整的本 skill/配套读取 skill；不借文档任务修改代码或 OpenSpec。
- 不读取 `.env`、密钥、原始 Provider 响应或本机会话数据；文档不写敏感 payload、绝对运行路径或图像字节。

## 文档分层

1. **全局 Overview**：产品边界、组件总图、跨组件内容流和状态矩阵。实线只画当前新 Figura 已运行的路径；设计中的连接用虚线或单独的目标流程表示。组件链接到专题文档。
2. **专题文档**：每个职责边界一篇，包含职责与输入输出、内部组成、按步骤的数据流、模型清单与关系、完整字段合同、跨组件接口、不变量及失败分支、状态与依据。
3. **完整字段合同**：对文档收录的每个模型枚举全部字段。使用 `Model.field` 完整路径；嵌套模型、联合类型、枚举、集合元素和 DTO 独立展开或精确链接。每行写类型、必填/默认、语义与约束、写入者、权威位置、读取者、公开/修订规则。不能用“关键字段”“等”或省略号代替剩余字段。字段只在权威所属文档定义一次；其他文档链接并说明消费方式。
4. **流转**：每步写明输入对象/字段、校验、产生或改变的对象、提交边界、下游和失败/恢复分支。区分引用与所有权、事实与投影、持久值与调用期值。

## 根据领域自主决定文档归属

不要按文件夹名、类名前缀、调用顺序或现有文档数量机械分配。更新前先从代码和规格判断新概念或变化的：**语义目的、权威事实/合同的 owner、身份或值语义、创建与生命周期、核心不变量、写入者和消费者**。再决定文档位置：

1. 若已有专题拥有该事实或合同，并负责其生命周期与不变量，更新该专题的内部流程及完整字段表。其他专题仅记录如何消费或映射，链接到 owner，不复制字段定义。例：`ProviderAttempt` 是 Run 的耐久尝试，归 Run 执行专题；`ProviderResponse` 的调用期形状归 Provider 边界。`ToolCallFact` 归 Run 执行，`ToolInvocation` 归 Tool 边界。
2. 若一个概念有独立职责、权威 owner、生命周期/不变量，且现有专题都不能无歧义地容纳它，**新建 `docs/figura/<领域名>.md`**。按职责命名，不因单个新类或单次 change 就拆文档；也不为保持既有目录数量而把不同领域强行合并。
3. 跨领域的调用期值或投影先找其合同定义者；共享基础合同若确实没有单一业务 owner，可建立小型共享合同专题并写清消费者。Agent 的编排文档可主要描述决策和流转；当前没有 Agent 自有持久模型时，不虚构字段表来填充。
4. 领域边界变化时更新 Overview 的组件节点、箭头和下钻链接；有新专题时将其加入导航。跨界流程改变时同步更新生产者与消费者各自的流程描述，但完整字段仍只在 owner 文档出现一次。对归属尚无证据的概念明确记为待决定，不悄悄塞入相邻专题。

## 取证和更新

从仓库根目录核对相关模型定义、序列化、写入、读取和公开投影；行为合同另读对应主规格。活动 change 需要读 proposal/design/specs/tasks 和工作树代码。先运行 `openspec store list --json` 确定 store id，再按需运行 `openspec list --json --store <id>` 或 `openspec status --change <name> --json --store <id>`。

新增或改变模型时，先按上节判断归属，再同步更新：全局状态/组件边（若跨边界变化）、owner 专题的内部流程和完整字段表、消费者专题中的映射、相关不变量和导航。纯文件移动、实现重构或 SQLite 迁移若不改变组件合同，只更新实现映射。不能核实的字段或关系标为待核实，不编造设计。

交付前检查：每个收录模型恰有一个定义位置，其字段与当前定义或已确认规格逐项对应；嵌套、可空、默认和枚举无遗漏；链接存在；全局图与专题流转及状态标签一致；执行 `git diff --check` 和适用的文档/skill 校验。文档编辑本身不需要应用测试，只报告实际检查。
