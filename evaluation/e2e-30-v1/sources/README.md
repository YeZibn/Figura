# 图片来源和冻结规则

正式分析集 A02/A03/A05/A06/A08/A09 为本次独立 Matplotlib 合成图，数据在各自 judge-only/answer-key.json 中冻结；并非直接使用 Figura renderer 生成分析输入。构建与修改参考 PNG 才使用当前 Figura renderer，且不作为实际成功结果。

A01/A04/A07/A10 为 Our World in Data 的官方图表 PNG 导出，使用固定国家、年份和显示参数。下载日期 2026-11-02。A10 对官方图进行固定降采样和轻微模糊，属于派生低清晰度输入，不能描述为原始发布分辨率。

每个 sources/Axx/ 保存 original.png、原始完整 CSV、原始列级 metadata、用于标注的 selected-data.json 和 provenance.json。CSV 接口可能返回未过滤的完整数据，因此本地明确按 Entity/Year 筛选，筛选结果和原图逐项核对。不得将完整 CSV 上传给 Figura，图片题不允许外部检索。

官方接口说明：[OWID Grapher Chart API](https://docs.owid.io/projects/etl/api/chart-api/)。

| 任务 | 图表页面 | 用途 |
|---|---|---|
| A01 | [Life expectancy](https://ourworldindata.org/grapher/life-expectancy?tab=discrete-bar&time=2023&country=CHN~IND~USA~JPN) | 四国寿命柱状图 |
| A04 | [CO₂ emissions per capita](https://ourworldindata.org/grapher/co-emissions-per-capita?time=2015..2023&country=CHN~USA~FRA) | 三国人均排放趋势 |
| A07 | [Life expectancy vs GDP per capita](https://ourworldindata.org/grapher/life-expectancy-un-vs-gdp-per-capita-wb?time=2023&country=CHN~IND~USA~BRA~ZAF~DEU&xScale=linear&zoomToSelection=true) | 六国散点关系 |
| A10 | [Renewable energy share](https://ourworldindata.org/grapher/renewable-share-energy?tab=line&time=2015..2023&country=CHN~USA~FRA) | 低清晰度下的趋势与精度边界 |

保留 OWID 图片署名，具体底层数据提供者和口径见各份 metadata。OWID 图表适用 CC BY，底层数据适用条件以来源元数据为准。不得仅凭同一网站来源就宣称覆盖广泛真实图表风格。原始下载快照只用于本版本，不自动刷新。

本地合成数据和正式参考值不是额外真实业务样本。未来刷新真实来源或替换输入图片，必须重新核对标注、更新摘要和数据集版本。
