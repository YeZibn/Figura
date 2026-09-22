## ADDED Requirements

### Requirement: Figure coverage distinguishes complete source from requested subset

每个 figure SHALL 明确其 `coverage.basis` 是 `full_source`、`requested_subset` 或
`not_applicable`，并分别记录 source series、represented series 和 intentionally omitted
series。集合级 complete/incomplete 判断 SHALL 结合该 basis，而不得把所有省略都判成错误。

#### Scenario: Same-source requested subset remains complete for its task

- **WHEN** 一个 figure 只按 transform 请求绘制同一 panel 的 Actual 系列
- **THEN** figure 可以在该任务范围内标记 complete
- **AND** Target 作为有意省略保留在 coverage 中
- **AND** 不要求把同一附件的其他 panel 加入集合

#### Scenario: Full-source omission remains incomplete

- **WHEN** reconstruct figure 声称覆盖整个 source panel 但缺失一个源系列
- **THEN** figure 标记 incomplete 或返回结构化覆盖问题
- **AND** 不得通过 requested_subset 标签掩盖该缺失

### Requirement: Collection members preserve their individual task contexts

集合 SHALL 为每个 child figure 保留独立的 generation context、source scope、coverage 和
candidate identity；集合装配不得把一个 child 的 panel 或省略决策传播到另一个 child。

#### Scenario: Two panel transforms stay independently reviewable

- **WHEN** 一个 collection 包含两个不同 panel 的转换结果
- **THEN** 每个 child 可被单独定位和审核
- **AND** 一个 child 的 source mismatch 不会被另一个 child 的成功掩盖

