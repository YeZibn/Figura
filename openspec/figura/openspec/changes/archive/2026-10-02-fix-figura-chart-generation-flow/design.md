## Context

动机见 `proposal.md`。本次定位来自最新 `test` Session 的两次 Run：第二次先因 pie 带 `series` 装配失败，模型修正后装配与渲染均成功；随后重新装配去掉总标题并再次渲染成功。五次 Provider attempt 都已提交响应，最后一条带工具调用的 assistant 没有 continuation，下一次本地 `prepare` 拒绝了请求，因此没有第六次 attempt 和最终答复。使用实际历史进行只读请求重建已复现该错误。

两张实际 PNG 分别出现总标题与子标题重叠、去掉总标题后子标题顶部裁切；来源备注未呈现，饼图只有类别没有百分比。原始 HTTP 响应没有保存，不能从历史判断最后一次 `reasoning_content` 原本是缺失、null 还是空字符串。

DeepSeek 官方 [thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/) 要求带工具的后续请求回传历史 reasoning；[响应字段文档](https://api-docs.deepseek.com/api/create-chat-completion/) 将其声明为可空字符串。现有响应归一化使用真值判断，Runtime、codec 和 SQLite 又要求非空字符串，丢失了显式空值语义。上一 change 的跨 Run 对应关系和 prepare-before-claim 顺序保持有效。

## Goals / Non-Goals

**Goals:** 用现有内容字段表达真实返回值；从解析、提交、重启读取到当前及历史 Run 回放保持相同语义；在一次修复中完成可测试的装配、绘图、图像回看和最终答复链路。

**Non-Goals:** 不补造 reasoning，不删减历史，不切换 Provider 或关闭 thinking，不新增业务资源、样式参数、review 状态或兼容层。不重开用户的失败 Run，不改旧 chartagent，不修改前端协议。

## Decisions

### 1. 用 continuation 是否存在表达字段是否返回

| 实际 DeepSeek 响应 | 内部表示 | 保存和后续请求 |
| --- | --- | --- |
| 字段缺失 | `continuation=None` | 不产生事实；需要 reasoning 的历史继续拒绝 |
| 显式 null | continuation 对象，`reasoning_content=None` | 保存 SQL NULL，回传 JSON null |
| 空字符串 | continuation 对象，`reasoning_content=""` | 保存空字符串，回传空字符串 |
| 非空字符串 | continuation 对象，原始字符串 | 按现有机制保存和回传 |
| 其他类型 | 非法响应 | 拒绝，不转换或修补 |

`ProviderContinuation.reasoning_content` 与 `ProviderContinuationFact.reasoning_content` 扩展为 `str | None`，不增加 presence、status 或其他持久字段。格式版本和事实版本仍为 1，数据库新约束表达允许的值域。仅 DeepSeek 允许上述显式空值，Qwen/MiMo 保持现有非空 continuation 语义。共同类型扩展不能放宽其他 Provider 的校验。

非流式归一化在丢弃原始值前检查实际字段存在性。Mapping 使用 key 存在性；SDK 对象依据实际返回字段或 extra 字段，不能把 SDK 未设置字段的默认 null 当成真实返回。采用一个局部 sentinel 或小型已有访问函数扩展即可，不建立新的抽象框架。

流式归一化同样检查字段存在性并校验类型：未返回任何字段表示缺失；只有显式 null 表示 null；至少一个字符串片段时按顺序拼接，空片段也表示字段存在。混合 null 与字符串时 null 不贡献文本。这些仅为归一化局部状态，不进入数据库。

`runtime/coordinator.py`、`runtime/codecs/records.py`、请求校验、存储读取与 SQLite 使用一致规则。字符串保持原文，UTF-8 上限 512 KiB；null 不含文本字节。提交仍必须匹配 Run、响应、Provider、format/schema version 且完全原子。请求组装沿用 `(run_id, response_record_id)`，不增加通用 Session Memory 字段，输出 payload 保留原始 JSON 类型。

曾考虑统一用 `""` 代替 missing/null，以及缺失时关闭 thinking。两者会改写 Provider 事实或执行选择，无法证明符合真实返回，因此采用保留原值和严格缺失拒绝。

### 2. 本地失败复用安全终止文案

`AgentExecutor` 的 prepare 异常分支区分已知 Provider 校验错误与未知异常。通过内部允许列表映射形成简体中文原因，例如“DeepSeek 工具历史缺少必要的 reasoning continuation，无法继续请求。”，不直接保存 `str(exception)`、远端响应或原始 payload。其他不安全或未知异常使用现有通用文案。

Coordinator 和 terminal repository 将受信且有界的文案写入已有 `Run.terminal_message`，保持 `terminal_code=execution_failed` 和终止事务/CAS 规则。文案不得超过 256 UTF-8 字节，内部校验失败应拒绝写入，调用方使用有界固定映射，不能通过裁切原始错误实现安全性。既有 HTTP `terminalMessage` 投影使用该内容，事件仍只写 terminal code，不新增错误详情事件或 Provider attempt。

曾考虑新增 Provider 预检事件或 error detail 表；已有终止文案足以让用户理解本次失败，额外模型没有必要。

### 3. 固定画布中先为文字分配空间

渲染保持现有服务端尺寸上限、列数、图像校验和结果字段。`charts/chartfigure/rendering.py` 统一处理总标题区域、每个子图的标题区域、绘图区及来源备注区域，不再用绘图区外的负坐标放置备注或固定 top 值猜测文字高度。

先按可用宽度换行，使用实际文字尺寸预留区域，再绘制图形。中文字体配置应在创建文字对象前生效。有无总标题、1–4 子图、1/2 列共享同一规则；来源与 note 非空时都可见。长文本允许有界换行及服务端字号调整，若仍无法容纳，返回现有有界渲染失败，不静默裁切后报成功。工具输入不增加字体、边距或百分比开关。

pie 依据完整非负 dataset 和正总和计算 `value / sum * 100`，显示一位小数及 `%`；保持类别标签，不把百分比写回 ChartSpec。零值可省略百分比标签，避免无意义叠字；独立舍入可能使显示总和为 99.9%/100.1%，不修改原始数据凑整。过密标签不能用遮挡图像作为成功结果，应调整服务端布局或明确失败。

曾考虑让模型去掉标题或传 margin 等字段；固定布局属于 renderer 的责任，因此不扩展模型内容。

### 4. 在工具契约中说明 pie 输入

在实际 `assemble_chart_figure` 描述及嵌入 ChartSpec schema 的相应字段描述中说明：pie 点使用 category/value，series 不提供或为 null，axes 不提供或为 null；需要两个系列的饼图时使用两个 ChartFigure child。继续允许现有 schema 的合法字段集合，语义校验保持严格且错误有路径，模型仍可在失败后修正。不新增 pie 专用内容模型或另一个装配工具，不扩张全局 prompt。

### 5. 以可控响应重建完整成功和失败路径

使用临时 Session、合成柱状图数据与可控 DeepSeek 响应：第一 Run 产生测量，第二 Run 先出现可修正装配错误，再成功装配、渲染、收到回看图像并提交最终答复。分别验证最后一次返回 nonempty/empty/null 均可继续；真正 missing 必须安全失败且没有新 attempt。测试包括跨 Run、流式、重启读取、原子回滚、隐私和旧 Provider 行为。

测试不得打开用户真实 `.figura` 数据执行迁移或清理，不保留 reasoning 文本到公开快照。视觉验收使用临时产物验证标题、备注、百分比位置；不能仅以 PNG 成功生成判断布局正确。离线测试证明本地语义和序列化，不声称已证明真实 DeepSeek 接受 null；真实服务端验证需要独立、明确的请求范围。

## Risks / Trade-offs

- [历史原值已经丢失] → 保留旧事实原状，真实缺失仍拒绝，不推断修复旧 Run。
- [SDK 默认 null 与字段实际存在混淆] → 覆盖真实字段集合和 Mapping 两种输入，以及字段未设置的对象。
- [DeepSeek 服务端空值行为尚未真实验证] → 原值回传符合已公开字段契约；记录离线与真实验证边界，不自动付费重试。
- [固定画布不能容纳任意密集文字] → 有界换行、布局及清晰渲染失败，保持尺寸和文件上限。
- [SQLite 表重建影响事实关联/删除触发器] → 事务迁移保留全部身份、索引、外键和不可变/Session purge 触发器，覆盖迁移失败回滚。

## Migration Plan

1. 实现归一化、统一类型校验和 schema 9 的新建/升级路径；迁移重建 continuation 表以允许 DeepSeek NULL/空串，保留其他 Provider 非空和字节约束。
2. 从 schema 8 以及现有可升级旧版本进入 9，保留所有 continuation、response ref、时间戳、checkpoint 和 terminal 状态。移除旧的非空统一判断，不增加旧类型兼容 façade。
3. 在临时数据库验证 fresh install、带事实迁移、外键/触发器、失败回滚和重启读取，再实现失败文案及绘图修复。
4. 完成定向和完整回归后再由用户触发规格同步/归档。升级前备份私有数据；回退使用原数据库备份和旧代码，不将新空值事实强制塞回 schema 8，不自动降级数据库。
