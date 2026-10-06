## Context

动机与功能范围见 [proposal.md](proposal.md)。以下实现事实记录本 change 开始前的基线：

- 普通请求由四份 Markdown 合并为稳定 SYSTEM 指令，再追加 Registry 工具目录、可选摘要与资源／异常状态索引。
- 全部 12 个工具都有工具级 `description`。11 个参数 Schema 没有字段说明；Figure Schema 只有少量饼图相关说明。原生 Provider 工具只提前暴露名称、描述和参数，不暴露 `result_schema`。
- `build_summary_request()` 将摘要规则内嵌在 Python 字符串；输入为旧摘要、旧来源引用和完整选定 Run 消息。摘要输出校验接受扁平 `items`，每项含 `text/source_refs`；Runtime 补充 trust 和 Run outcome。
- `read_history` 能读完整 Figure、OCR／测量内容；字段选择从外层响应的 `content` 内部开始。搜索是文本匹配，不是语义检索。
- `read_resource_image` 复用了通用历史引用 Schema，其输入目前接受不能产生图像的 message、tool_result、chart_figure。
- Panel 分割保留裁剪矩形内原 RGB，通过 alpha=0 隐藏多边形外区域。观察解码直接转 RGB，导致原像素进入 OCR／测量；已经以纯内存图像确认，原 `(220,30,40,0)` 解码为 `(220,30,40)`。

对应行为合同见本 change 的五份 delta specs。新 `image-observation-decoding` 由 Tools 观察解码边界拥有，不新增服务或独立领域文档。

## Goals / Non-Goals

**Goals:**

- 使目标选择、证据判断、历史取回、参数填写和结果解释有连续的正向指导，重要参数无需依靠名称猜测。
- 固定规则、动态数据、原生 Schema 与专用摘要任务有明确来源，避免同一合同出现多份不一致副本。
- 修复透明图像的可见内容与检测输入不一致问题，并为共享解码建立可复用验证。
- 保持现有执行／恢复身份、来源授权与工具结果存储；摘要输出合同升级为机器可读 v2。

**Non-Goals:**

- 不改变压缩触发阈值、目标占比或 Run 选择算法；不增加摘要表、列或数据库迁移，也不将摘要替代原事实。
- 不增加工具失败自动重试、语义搜索、自动读取全部历史图像或隐藏的 Figure patch 能力。
- 不全面重构 Provider 的结果 Schema 暴露方式，也不把所有 Schema 改成按图表类型分支的条件校验。
- 不改旧 chartagent、前端、发布审核、图表数据模型或当前检测算法的能力边界。

## Decisions

### 1. 保留四份普通资产，整体审校内容

继续按 `agent → evidence → workflow → response` 加载，不通过增加一份通用补丁提示叠加旧规则。每份文件完整改写，但保留当前有效合同。

| 资产 | 组织内容 | 不承担的内容 |
|---|---|---|
| `agent.md` | 目标与多目标识别；必要动作；当前要求、历史偏好与更正；模型决定、工具校验 | 详细参数、固定调用顺序、完整资源字段 |
| `evidence.md` | 用户数据、直接视觉、OCR、测量、摘要／索引的含义；状态、局部范围、单位、引用和不确定性 | 每次读取的动态值、操作步骤 |
| `workflow.md` | 现有信息评估→按需取回／观察→构建与回看→交付；明确各步可跳过 | 参数 JSON 副本、强制 OCR→测量流水线 |
| `response.md` | 结论／数据／图像交付；估计与未知；完成阶段与实质限制；仅必要内部细节 | 技术实现解释、泛化免责声明 |

改写方式采用“判断条件→有用动作→证据边界”。禁止编造等原则在 evidence 层集中定义，workflow 用操作性说明承接，response 只解释呈现方式。文件之间允许简短衔接，不靠文件名引用让模型访问不存在的文件系统。

必须覆盖的决策：

1. 已有用户数据足够时直接回答或绘图；测量工具已有 OCR 辅助，不因流程习惯强制再做独立 OCR。
2. 摘要足够时直接使用；有引用时直接 `read_history`；找不到来源才 `search_history`；需新的视觉判断才读图。
3. OCR `available` 表示本次 OCR 能力可用性，空 snippets 与不可用不同；截断／未检出不证明完整性或不存在。
4. 按字段使用部分证据；`measured` 不保证所有值、标签或范围完整，`partial` 也不意味着全部字段不可用。
5. 观察范围保留必要轴、刻度与图例，明确涂白、OCR 整框过滤和几何截断；Panel 与附件坐标独立。
6. 修改已有图：读取完整 Figure、保留未修改且有依据的内容、提交新的完整 assembly，按需 render。不存在原地 patch 或自动渲染。
7. 新图可以有描述性标题、轴名和中性的系列显示标识；不得声称是原图原标签或杜撰业务单位。类别、数据值和业务系列含义仍必须有依据。
8. 参数错误针对字段修正；不确定性选择有机会解决问题的动作。warnings 和 retryable 不强制同参数重试。达到目标或没有有效补充路径时交付结果。

备选方案是合并所有规则成单个长 prompt；会失去当前职责与维护边界，因此保持分层。只改措辞而不补决策指导不能解决已发现的实际使用问题。

### 2. 工具用途与字段语义分别维护

工具级描述采用“用途／来源→关键输出→限制／后续”的短段落。参数说明直接放进定义工具的原生 Schema，Provider 投影自动保留；不新增独立 prompt_guidance 注册字段，不复制 result Schema 到 SYSTEM 工具目录，不用 Description 数量作为质量标准。

| 工具 | 工具描述的目标内容 | 关键参数说明 |
|---|---|---|
| `load_image` | 用于观察授权 Attachment／Panel；返回元数据，原图附加下一请求；历史或其他图像资源可用 read_resource_image | source_kind/source_id 的类型与已有引用来源 |
| `decompose_chart_image` | 依据先前图像观察提交区域，创建独立 Panel；按输入顺序返回引用；不自动确认语义边界或加载新图 | 原附件归一化 `{x,y}`、多边形顺序与 Panel 命名 |
| `search_history` | 文本搜索消息、工具结果、异常调用状态与资源；返回摘录／引用／分页，不执行旧工具 | query、run_id、source_kind、默认页大小、cursor 保持查询与筛选 |
| `read_history` | 读取原始消息、结果／错误／未知状态和完整资源内容；包括完整 Figure；不会隐式加载图像 | reference、content-relative field_path、0-based start/end |
| `read_resource_image` | 原图、OCR／测量标注、ChartRender；附加下一请求；ChartFigure 必须先渲染或找已有 ChartRender | 限定可读资源 kind，完整引用，复用真实返回标识 |
| `extract_text` | 候选文本、像素框、置信度、available/truncated；空不等于不存在；成功批次提供标注图 | 共享来源与 scope；结果框为 x/y/width/height 原来源像素 |
| `measure_bars` | 柱体几何、方向／模式、基线、类别／系列、像素长度／相对比例；有效校准后才有图表值 | 共享来源与 scope；保留值轴与基线线索 |
| `measure_lines` | 分段轨迹、marker 或 axis_tick_sample、坐标轴与可能校准值；采样不代表全部原始点 | 共享来源与 scope；保持轴刻度，避免切断目标轨迹 |
| `measure_scatter` | 可见点／系列、校准坐标、合并／遮挡标记；不恢复隐藏点或证明真实样本数 | 共享来源与 scope；保持校准与系列关联线索 |
| `measure_pie` | 二维圆饼几何与有支持的比例／标签；比例不等于绝对值；不支持类型与局部覆盖限制 | 共享来源与 scope；避免丢失支持扇区范围的可见几何 |
| `assemble_chart_figure` | 1–4 个完整 ChartSpec 构成新 Figure；返回 figure_ref／摘要；引用仅核验授权成功，不核实数据真值；不绘制 | schema_version、layout、charts、chart_id、measurement_refs 及 ChartSpec 数据语义 |
| `render_chart_figure` | 已接受 Figure→PNG；摘要及下一请求图像；生成不代表审核；修改须新 assembly | 嵌套 figure_ref 的 run_id/call_id 来自成功 assembly |

简易字段类型与范围由 Schema 负责。对影响选择或解释的主要结果语义，在工具描述／evidence 说明；结果具体值及错误仍由实际 tool observation 提供。无需为内部 result Schema 的每个简单字段填充文案。

### 3. 补齐共享范围、历史选择器与 ChartSpec 注释

范围参数在 `measurement_schema.py` 一处维护：选定来源的左上角为原点，x 向右、y 向下，以各自宽高归一化到 0–1000；点为 `[x,y]`；include 并集减 exclude 并集；缺少 include 则从全图起步；至少有一个区域字段；无有效观察像素会失败。实际坐标映射公式保持现有实现，不借文案整理调整边缘像素语义。

分割参数在 `image.py` 使用 `{x,y}`，创建按多边形包围盒裁剪的独立 Panel；后续 scope 和结果坐标相对 Panel 本身。不同参数格式各自注释，不将拆分点形状复用给观察范围。

历史参数注释示例：

- `reference={kind:chart_figure,run_id,call_id}` 配合 `selector.field_path="/figure"` 读取完整 Figure。
- 工具结果读取时，`/result` 是相对返回 content 的成功结果；不是 `/content/result`。
- `start=0,end=10` 是所选字符串的前 10 字符或数组的前 10 项；若选择对象则不能直接切片。
- cursor 和 query/run_id/source_kind 必须保持匹配；page_size 可按既有规则选择，不新增语义搜索或无 query 列表能力。

ChartSpec 注释由 Charts 的原生 Schema 拥有。完整说明 bar/pie 为 category/value、line/scatter 为 x/y、类别折线使用从 0 起的位置、同系列 x 严格递增，以及当前要求的类别覆盖／系列对应；保持已有校验规则和未知值不补零。结构 Schema 不能表达的现有语义仍由 validator 执行。本轮不改数据模型或新增条件分支 Schema。

### 4. 缩小历史图像读取输入

在 history 工具模块定义专用图像引用 Schema，只含 attachment、panel、ocr、measurement、chart_render；通用 reference Schema 仍服务 search/read。参数和结果的 resource_ref 使用相同受限图像合同。保持授权、成功状态与图像一致性检查，不改变 read_history 对 chart_figure 的完整内容读取。

message/tool_result/figure 引用送入图像工具时在参数校验阶段失败；描述指明替代动作。底层 Reader 继续拒绝不适用资源，不因为 Schema 收窄删除内部防线。

### 5. 独立加载摘要资产与明确增量规则

新增 `assets/compaction.md`，复用 importlib.resources 的 UTF-8 加载路径，提供 `build_compaction_instruction()`。可用一个私有资源读取 helper 共享空文件检查，但不建立通用模板框架。`_STATIC_ASSETS` 保持四项，普通请求绝不加载 compaction。

摘要资产结构：职责／输入信任边界、保留优先级、旧摘要与新增历史合并、证据状态、引用规则、严格 JSON 输出。生成目标是后续请求可继续任务，而不是历史逐条复述。更正覆盖旧结论时保留最新有依据的状态；仍有效的偏好与资源引用可保留。无必要内容时各分组可空。

新的 v2 输出使用固定分组字段，避免把所有状态塞入一组无法机器区分的自由文本条目：

```json
{
  "current_goal": [],
  "constraints": [],
  "decisions": [],
  "facts": [],
  "progress": {"completed": [], "in_progress": [], "pending": [], "blocked": []},
  "open_questions": [],
  "resources": [],
  "proposals": []
}
```

每个分组中的条目均为 `{"text":"...","source_refs":[...]}`；每项必须有一个或多个相关、逐字来自输入的 message/tool_result 引用。`progress.pending` 仅放用户明确要求或接受但尚未完成的工作；助手提出但用户未接受的行动放入 `proposals`，不得伪装成待办。`completed` 要有结果证据，`in_progress` 要有已开始的证据，`blocked` 要说明障碍；稳定数据或观察放在 `facts`，资源标识与恢复所需定位信息放在 `resources`。`current_goal` 表示仍有效的目标，旧目标完成或被更正后应移除或更新。

摘要请求只提供 `previous_summary`、其来源引用和新增历史，不向模型暴露持久化合同版本。提示词要求模型按输入实际提供的旧摘要内容与来源进行归纳，无论旧摘要字段布局如何，都完整输出当前 v2 合同；内容含义不清时不得猜成用户已接受的待办。上一 checkpoint 中系统生成的 `trust` 和 `run_outcomes` 只用于信任边界／运行背景；输出时不得让模型生成它们，`run_outcomes` 继续由 Runtime 追加和合并。

内部 checkpoint 的 `summary_contract_version` 与摘要操作 binding 升为 2。普通请求投影同时读取 v1／v2 JSON，不在读取旧 checkpoint 时强制迁移；下一次成功压缩写入 v2 checkpoint。存储表结构未变化。变更部署前已绑定的 v1 摘要操作由于 registry/prompt/合同身份改变而按既有严格请求身份校验进入 fallback，不放宽绑定检查。格式／引用校验不能证明语义正确，文档与测试不得声称具有事实验证能力。

`build_summary_request()` 继续只组装一个独立 SYSTEM 指令与原来源 JSON；无工具／图像。移除摘要指令中“接近约 50% 窗口占用”，程序保留现有容量判断、估算和目标。缺失／空摘要资产显式失败并在摘要准备边界转为现有 `invalid_summary_input` fallback，保持原历史与旧 checkpoint；不回退到硬编码旧 prompt。普通静态资产加载失败保留既有明确失败语义。

`prompt_digest` 根据加载后的实际指令生成；摘要 registry identity 升为 `context-compaction-v2`，请求绑定与 checkpoint 都记录摘要合同版本 2。重试严格复用同一请求身份，不引入指令快照表或“忽略 digest”的兼容路径。现有 package-data `agent/prompting/assets/*.md` 已覆盖新文件，验证安装资源可读取即可。

### 6. 在观察解码边界处理 alpha

修复点选在五种观察工具共同调用的 `decode_scoped_image()`，不改 Panel 文件内容与 Sources 元数据，以便也覆盖带透明度的附件。备选的“分割时改写 RGB”为仅修新 Panel，无法处理既有 Panel 和透明附件；单纯 white compositing 也不能给 OCR／Pie 提供完全透明边界，因此统一处理颜色与 mask。

处理顺序：

1. 保留现有解码／大小保护，按 RGBA 取得 alpha；对透明度与白底做合成，生成用于检测的 RGB。
2. alpha>0 为固有可见 mask；部分透明色采用实际白底合成颜色，不采用任意阈值丢弃边缘。
3. 若显式传 scope，将其几何 mask 与可见 mask 相交；未传 scope 则仅使用固有可见 mask。
4. 有不可见像素时返回有效 mask，并将无效像素置白。全不透明且没有 scope 时继续返回 mask=None，保持已有快路径。
5. 有 scope 但有效像素为空，抛 ObservationScopeError→invalid_observation_scope；无 scope 且全透明，抛 ValueError→image_unavailable。解码完成前不启动 OCR／几何。
6. 沿用 OCR 整框过滤和 Pie 显式 mask；其他几何从中和后的 RGB 检测。保留截断／片段的真实能力边界，不承诺整体对象过滤或补全被排除数据。

保持图像宽高、坐标系、结果字段和源文件不变；标注图仍由原来源与已提交观察重建，不把解码副本持久化；标注底图也按白底合成 alpha，避免反馈重新暴露隐藏 RGB。底图保留范围外的可见上下文，不因此重做检测。

### 7. 验证结构、行为与文案完整性分别验收

- Loader／请求测试：普通四份顺序、专用摘要隔离、缺失／空资产失败、无工具与无图像、digest 与同一绑定恢复。
- 工具测试：12 个工具仍按原顺序投影；重要描述保留在 native Schema；合法引用仍接受，非图像引用在 handler 前拒绝；选择器与 Figure 原文读取工作。
- 图像测试：透明区隐藏 RGB 变化不改变解码可见数据／mask；半透明白底颜色；显式 scope 与 alpha 交集；OCR 整框过滤；全透明和空交集错误；不透明图片与源尺寸不变。
- 集成回归：使用真实 Panel crop、假 OCR 返回／既有图表 fixture 验证五个观察适配器的共享解码效果，不以 OCR 对合成文字的随机识别率作为断言。
- 文案审校：用“直接绘图、解释、局部提取、历史数值取回、已有 Figure 修改、失败后选择、源图对比”七类场景核对引导，无固定无意义工具序列、不完整字段规则或相互矛盾承诺。不为每句中文写字符串断言来冒充模型行为评估。
- 先运行相关窄测试，再 `conda run -n agent python -m pytest -q` 和 `git diff --check`。如未跑真实模型，不宣称模型准确率、决策质量已经得到验证。

## Risks / Trade-offs

- [提示润色不保证所有模型按预期决策] → 结构／行为回归与场景审校分别报告；不把文案测试当作模型效果指标。
- [白底合成改变透明图像的检测结果] → 这是修复目标；不透明输入保持不变，alpha>0 部分保留、原坐标不变，新增透明 fixture 验证。
- [完全透明边界使 OCR 整框过滤更严格] → 仅候选框触及不可见像素时拒绝，部分透明仍可观察；必要上下文由范围选择规则指导。
- [增加注释使请求稍大] → 只补关键语义、少量格式示例，不复制结果手册；token 估算与既有压缩机制处理实际请求规模。
- [旧 Run／已绑定请求遇到新 registry 或 prompt] → 版本升级与现有身份校验保持严格，部署前完成活动 Run 的协调，不在本 change 增加迁移执行器。

## Migration Plan

1. 完成代码、资产、参数说明和回归后，将 bootstrap Registry 从 figura-web-v7 升为 figura-web-v8。明确这是图像读取参数收窄和观察语义修复，不仅是描述编辑。
2. 部署前查询当前活动 Run，让其结束或协作停止并完成协调；不删原始事实，不对 v7 unresolved calls 使用 v8 handler。
3. 启动新版后，新请求使用新资产与 Registry；已有摘要 checkpoint 与旧闭合历史仍按原合同读取。数据库、env 与工具名称无需迁移。
4. 同步 overview 与 Agent／Tools／Memory／Sources 的受影响说明，清理 Agent 专题已有重复职责表；明确实现、主规格、change 状态。
5. 回滚代码与资产必须成套，保留原数据；v8 活动 Run 同样先完成协调，不能在回滚后用旧 registry 偷换其执行合同。
