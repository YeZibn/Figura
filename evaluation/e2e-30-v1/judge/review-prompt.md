# 独立复核提示 v1.0

在独立上下文中先使用 prompt.md 和原始证据给出独立裁决，再读取初评结果。不得先根据初评标签寻找支持理由。不能重跑或修复 Figura。

逐项比较两次判定，明确分歧发生在数值、语义、产物选择、视觉、要求解释还是证据缺失。沿用同一答案和容差。保存你的完整 verdict 及 review 对象：initial_verdict_ref、independent_verdict_ref、agreements、disagreements、recommended_resolution、requires_human_arbitration。

不能因为两次模型意见相同就宣称结果绝对正确。参考冲突、采集错误和无法判定的视觉问题应明确留给仲裁。任何规则变更必须产生新版本，不在单题中临时降低阈值。
