## Context

参见 proposal.md 的动机。当前实现位于 src/figura/tools/measurements，入口接受来源、家族与范围，结果是闭合的十类 observations 联合。笛卡尔传感器已有线性轴校准；雷达顶点和热力图单元仍直接输出 null；树图主要依靠有色矩形包含关系找父级。柱传感器的宽泛颜色去重能删除真实系列，图例附近颜色匹配也可能把维度文字关联为系列。

本轮诊断使用 13 张 photo 图片：10 张单图、3 张 Gallery（20 个图表实例）。10 张得到最终回答，3 张人工中断，直方图另有一次 Provider 402 后重跑；这些是诊断事实，不是抽取准确率。许多数值来自模型估读。原始图片生成数据尚未确认为可恢复，因此不能将此前估读当作精确标准答案。

## Goals / Non-Goals

**Goals:**
- 用可复现可见目标验证传感器，而不是以模型回答完整性验证测量。
- 共享视觉事实与校准支持，同时保留十类原生结构。
- 每个非空语义数值有来源链；缺失、冲突和局部观察可明确表达。
- 在一个 Change 内完成基线、合同和算法，统一发布。

**Non-Goals:**
- Agent 循环收敛、自动工具重试、Run 次数上限、前端新交互和端到端完成率保证。
- 新家族、专业扩展、透视/三维图、断轴和未经识别的非线性映射。
- 通过 renderer 私有信息、标准答案或嵌入图片元数据辅助生产测量。
- 旧合同适配层、旧实现迁移或 ChartSpec/ChartFigure 业务模型重写。

## Decisions

### 1. 单次共享观察上下文，家族决定布局和解释

入口完成授权、解码和 scope 后，构建一次调用内的上下文：来源坐标、有效掩码、OCR 候选、布局区域候选、颜色/连通对象和校准候选。可在 measurements 下新增 context.py、layout.py 和 evidence.py；contracts.py 是对外字段唯一所有者。

上下文不持久化、不跨调用缓存、不新增 RunExecutionState 字段。各家族选择适合的区域候选，笛卡尔、圆形、径向与矩形分区布局不强制共用一个检测器。相比把所有图表统一成矩形/线/点，此设计避免丢失原生语义。

流水线：授权来源 → 可见像素/scope → 共享候选 → 指定家族几何 → 语义关联/校准 → 合同验证 → 工具事实/标注。

### 2. 区域分工严格受 scope 约束

在有效掩码内区分数据几何区域与校准/关联区域。图例可参与系列对应，但不可作为柱/点/线；色条可支持数值，但不可作为热力单元。区域判定不明确时保留候选并返回问题，不能强行裁掉绘图区内部合法对象。

scope 沿用 0..1000 整数数组点、多边形 include/exclude，排除优先。数据和 OCR 均不能越过有效范围；像素输出保持原来源坐标。工具提供一份合法 include/exclude 示例，错误字段路径遵循现有参数失败合同。测量不调用 Sources 的 Panel 创建能力。算法可内部裁剪计算，但结果必须映射回来源，不能暴露临时裁剪为独立图表。

### 3. 颜色观察不等于系列身份

移除 bars 的宽泛 RGB 候选抑制，不以调小一个全局距离阈值代替修复。主体颜色保留，边缘色仅在局部邻接和对象轮廓有支持时归属同一对象；小数据对象不能仅凭面积排名删除。以形状、连通结构、区域与图例关系决定对象和系列；相同颜色不保证同一系列，相近颜色不构成合并依据。

透明填充使用白底实际合成色，不能用 renderer 配色倒推。折线抗锯齿、面积透明度和不同配色变体作为独立回归，防止颜色修复制造碎片系列。

### 4. OCR 按角色关联，校准保留失败依据

OCR 每调用复用识别结果，候选角色为标题、轴名、刻度、类别、图例、数据标签和分组标题。角色由区域、排列、几何邻接共同支持。角色冲突保持 ambiguous；雷达维度不参与普通图例抢占，树图分组标题不强制映射为叶子。

线性轴使用刻度位置和值的稳健拟合，保留被接受/拒绝的候选及残差。数字解析支持负号、小数、百分号、明确数量级；不能混合单位。支持反向轴、非零起点；没有证据不默认基线零。对明显非线性/断轴返回 unsupported 或 partial（保留已有几何），不能把不适用的线性校准写为成功。

径向校准按中心到刻度/环的距离拟合，热力校准沿真实色条位置匹配并关联刻度。至少两个不同支持值、非退化位置和足够支持跨度才能接受映射；阈值按分辨率与校准残差确定，并写入测试参数。色条颜色重复导致多解时返回 null。误差表示像素读取和拟合误差，不是统计置信区间。

### 5. 完整结果合同统一升级为 schema_version 3

保留来源、chart_type、image_size、coordinate_system、status、plot_area_px、observations、confidence、warnings、truncated。新增必填闭合字段如下；空集合合法，不凭空填支持信息。

| 字段 | 子字段及含义 | 写入/消费 |
|---|---|---|
| coverage | scope_kind(full_source/scoped)、requested_scope(null 或原规范范围)、structure_status(established/partial/unknown)、detected_counts(按家族闭合计数字段) | 路由记录范围，传感器记录结构；模型读取，评测检查，不计算猜测百分比 |
| issues[] | code、field_path(JSON Pointer)、evidence_ids、message | 传感器记录缺口；仅描述事实，不包含 next_action 或自动重试命令 |
| evidence[] | id、kind(ocr/geometry)、source-frame bounds/points、OCR text/confidence（按 kind 闭合联合） | 共享/家族生成；标注、校准与数值引用 |
| calibrations[] | id、kind(axis/radial/color_scale)、axis_role(x/y/radial/color/null)、supported、support_evidence_ids、parameters(按 kind 闭合联合)、residual_value、support_domain | 校准层生成；数值校验与详细读取 |
| value_provenance[] | field_path、method(direct_text/axis_calibration/radial_calibration/color_scale_calibration/geometry_ratio/derived)、evidence_ids、calibration_ids、input_paths、error_bound(null 或有依据的非负值) | 家族生成；每个语义数值一条，derived 引用本结果的输入数值路径 |

内部所有者均为 measurements；工具实现加来源身份后验证并提交现有工具执行事实。Prompt/历史消费者允许摘要，但完整结果仍经现有读取引用访问。不新增数据库表、前端决策状态、Schema 内任意 object 字段或本地路径。

每个非空语义数值（含比例）必须恰有一条有效 provenance；纯像素几何、置信度和内部校准参数不适用逐值要求。直接文字必须有 OCR 依据及明确关联；校准值引用 supported calibration 与对象几何；derived 引用已支持输入，禁止环；geometry_ratio 引用几何与明确分母。数字文字与几何不一致且无法判定时保留两份证据，权威 observation 值为 null，并记录 value_conflict，避免静默选择。

所有集合有显式 codec 上界，与现有 512 观察、32 警告和结果编码预算协调：实施时按单对象所需依据数量推导证据/依据上界，先保留可输出观察的依赖闭包，再截断无关候选。绝不留下悬空引用；未能保留依据的数值清空，必要时删去完整观察并设置 partial/truncated。这里是结果编码边界，不是 Run 调用上限。

状态规则：measured 表示主要结构及该家族适用数值/关联没有已知关键缺口；partial 表示存在可用对象但关键结构/校准/关联缺失或截断；no_evidence 无可靠对象；unsupported 为发现结构不在可解释范围。局部测量能 measured，但 coverage 明确 scoped。置信度仍是候选强弱，不是正确率。

### 6. 家族 observations 补齐必要表达

| 家族 | 检测/计算方法 | 必要合同与异常表达 |
|---|---|---|
| bar | 主体柱组件、类别分组、方向/堆叠、基线与端点轴映射 | 12 柱/3 系列不丢红色；baseline_value 有依据；非零轴不默认长度等于值；堆叠区段取端点差 |
| line | 连续轨迹与标记组合，排除图例；无标记仅在支持刻度采样 | 点增加 category_id/category_label（可 null）；marker 与 axis_tick_sample 区分；断段不桥接 |
| scatter | 绘图区标记组件，重叠标志和独立 x/y 校准 | 图例不计点；大小保留像素，只有明确尺寸图例才支持业务值；本次不强求反推 bubble 业务值 |
| pie | 中心/内外半径、角覆盖、标签引线关联 | ratio 保持角度来源；百分比文字独立证据核对；不输出无总量支持的绝对值 |
| area | 合成色区域的上下边界，按共同 x 类别/刻度采样 | segments 增加 samples（position/category、upper/lower/series_value）；stacked 值为上下差；unknown stacking 不自动相减；保留断段 |
| histogram | 数值区间边界与柱顶，独立于类别解释 | interval_start/end 校准；y_measure unknown 与可测柱高分离，仍 partial；邻接不代表必须等宽 |
| box_plot | 轮廓、填充与线段共同找箱体，再找中位/须/端帽/离群点 | 支持普通横竖方向；下须≤Q1≤median≤Q3≤上须，不合规则返回冲突/未知；须不称样本 min/max |
| radar | 中心/辐射轴/外围标签联合定位，系列沿轴交点，径向刻度拟合 | vertex position_px 可 null；dimension_id 必须指向 spokes；缺失不填轴端点；无径向支持 value null |
| heatmap | 行列规则网格作为单元基础，色条独立定位 | 格内明文优先、色条为独立支持；冲突 null；同色相邻格不合并；色条不进入 grid |
| treemap | 叶子矩形、分组边界/标题带、包含/分区关系联合 | node 增加 role(leaf/group/unknown)、area_ratio_basis(parent_plot/root_plot)、area_ratio_parent_id；标题带/间距是否计入由分母几何证据确定；层级不明保留 null，不造根 |

单个完整图与 Gallery 对应 Panel 必须共用算法；不能以文件名、标题关键词或固定 renderer palette 分支。家族函数可拆分，统一入口不添加 legacy 别名。几何与证据标注来自同一已验证结果，不能另跑检测产生不同对象。

### 7. 同源生成与独立评测

建议新增 tests/fixtures/figura_measurement/manifest.json、cases/*.json（ChartFigure 源、可见目标、误差规则）和 images/；scripts/generate_figura_measurement_fixtures.py 生成测试图与 photo 展示图，scripts/evaluate_figura_measurements.py 在 agent 环境离线调用生产测量入口。标准答案不进入授权资源、模型请求或生产算法。生成目标几何可用于评测，不可传给传感器。

先查找原始生成源；不可恢复时保存旧图片诊断校验值，建立重新生成的新基线并注明 regenerated，不伪造旧精确真值。同一 case 是图片/答案唯一所有者；photo README 链接生成说明，避免双份手改。提交仅模拟图和数据，不包含会话/Run/API 密钥。

manifest 记录 case_id、image hash/size、源数据/renderer 版本与字体、scope/Panel polygons、目标对象/关联、可见性、误差及来源。真实 OCR 与固定 OCR 候选分组报告；运行提供环境、样例 hash、结果合同/代码版本、每家族计数与数值指标。

匹配按空间位置及系列/类别/维度关系做一对一匹配，不依赖随机对象 ID。折线无 marker 仅检查已声明的采样目标；遮挡不要求还原隐藏对象。结构错、漏检、误检、关联错误、数值缺失、数值误差与无依据非空值分别计数。

基础数值容差在实施算法前写入 manifest：轴/径向为两个来源像素对应的单位误差加参考校准残差（实际传感器残差不得放宽验收）；比例按两像素边界误差或明确角度误差传播；色条按两个色条像素对应单位误差并检验颜色匹配；明确文字按预声明 OCR 规范化规则核对。容差随渲染尺寸变化但不随预测误差变化。初始 13 样例结构与关联全匹配，所有声明可读目标非空且在容差内，无依据非空值为零；缺失/冲突变体要求正确 null/issues。

Gallery 使用 manifest 固定 Panel 范围与 Sources 正常授权接口测量；另验证局部 scope 调用不创建 Panel。Agent 自主分割质量不在本次通过门槛。报告输出本地生成目录，不提交实时执行数据。

### 8. 消费与维护边界

审计 measurement_source、Registry 描述/Schema、可视化、资源摘要、历史读取、工具结果序列化和相关测试。只调整读取新结构所需代码，不加入新的 Agent 循环规则或前端控件。更新 docs/figura/tools.md 及必要的 sources/agent 交叉引用，不把测量事实写入 ChartSpec 主模型。

## Risks / Trade-offs

- 自己 renderer 产生的样例偏简单 → 加入独立绘制/受控扰动、同色网格、图内图例、彩色箱线等变体；报告明确仅回归范围，不宣称外部 benchmark 准确率。
- 布局先错导致后续联动失败 → 保留布局证据，家族联合验证，区域歧义 partial；不用固定比例裁边。
- OCR 环境差异 → 固定候选与真实 RapidOCR 分层；记录字体、环境与依赖，使用 agent Conda 环境。
- 证据使结果变大 → 依据去重、依赖闭包截断与 codec 校验；摘要引用完整结果。
- 完整合同 breaking → 统一 Registry 发布、旧 Run 结束后切换、历史事实不改写；不添加转换执行器。
- 缺口诚实表达可能减少 measured 数量 → 验收分别检查结构和数值，避免靠状态掩盖能力不足。

## Migration Plan

1. 固定旧图 hash 与诊断说明，建立基线、误差和预期失败测试。
2. 一起实现新合同、共享基础、十个传感器和所有当前消费者；不先单独上线新 Schema。
3. 跑家族/合同/范围/真实 OCR/标注回归与完整 Python 测试；任何实际 frontend 改动必须追加 build/smoke。
4. 停止准入并结束或明确取消旧 Registry 非终态 Run，核查绑定后发布新 Registry/Schema，再恢复准入。
5. 回滚时同样结束新 Registry Run 并回滚整套代码/Registry；不将新事实转换成旧执行合同，保留历史事实作为原始记录。
