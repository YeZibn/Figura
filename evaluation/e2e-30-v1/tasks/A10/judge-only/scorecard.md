# A10 真实图降清晰度：不伪造精度：评分表

关键项全部通过才通过，参考图不做像素匹配。

| ID | 关键要求 | 预期 |
|---|---|---|
| structure | 折线图；可再生能源占一次能源消费的比例；百分数；2015—2023 | "line / renewable primary energy share / percent / 2015–2023" |
| direction | 三国首尾变化方向正确 | {"China": "increase", "United States": "increase", "France": "increase"} |
| ranking | 2023 高低顺序正确 | ["France", "China", "United States"] |
| uncertainty | 明确无法可靠恢复四位小数，不编造精确值 | "无法从低清图片可靠恢复四位小数" |

容差、轮次、证据要求见 answer-key.json。
