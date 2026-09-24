## REMOVED Requirements

### Requirement: Generated result preview preserves artifact actions and statuses

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

## ADDED Requirements

### Requirement: Staged and published chart previews have distinct actions

交互预览 SHALL 使用同一安全资源边界打开授权的暂存图或正式图表。暂存图 SHALL 显示验证中、失败或不可用的有界诊断，不能提供正式 artifact 下载或暗示已发布；只有已发布图表 MAY 提供下载。资源过期、无权限或缺少图像字节时不得打开无效预览。

#### Scenario: Failed staged chart is previewable
- **WHEN** 失败尝试的暂存图仍在保留期内且用户有权限
- **THEN** 用户可用共享缩放预览检查该图
- **AND** 看不到正式产物下载动作

#### Scenario: Published chart can be downloaded
- **WHEN** 已验证的正式图表有可用资源
- **THEN** 用户可分别预览及下载它
- **AND** 警告发布结果在预览中保留警告
