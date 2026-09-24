## 过程产物层

下面只提供当前 run 的有界 staged chart、verification、artifact 和 measurement 索引。原生 JSON tool message、多模态图片和 resource reference 才是详细证据。

```json
{artifact_summary}
```

同一 `collection_id` 下的子图各自保留验证结果；不能用一张子图通过替代其他子图的结果。`staged_ref` 只能用于授权预览；只有 `published_artifact_id` 才能用于正式下载。读取 `verification.status` 和 issues；失败或未决图片不可称为已发布。

测量索引是有界摘要。要决定是否使用测量证据，回到原生 tool observation 读取完整 refs、overlay、issue 和视觉证据，再按服务端范围校验结果组装。
