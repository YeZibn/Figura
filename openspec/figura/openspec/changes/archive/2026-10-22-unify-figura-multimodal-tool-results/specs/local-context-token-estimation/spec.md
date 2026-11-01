## MODIFIED Requirements

### Requirement: Images have one explicit approximate cost
Figura SHALL exclude image URLs and base64 image bodies from text counting and SHALL add 1,024 estimated tokens for each image occurrence actually included in the request. This rule SHALL be identical across Providers and SHALL NOT be described as native visual token accounting. Changing the counting rule SHALL change the estimator version.

This rule SHALL apply to image occurrences inside native tool-result content as well as other supported image content. Resource references and metadata for images not actually loaded SHALL contribute only their text cost, not visual cost. Adjacent hint and identity text actually sent SHALL be included in text counting. Moving an image from a synthetic user message to its native tool result SHALL NOT change its per-occurrence visual cost or cause Base64 text counting.

#### Scenario: Count repeated image occurrences
- **WHEN** the request includes two image blocks, including two occurrences of the same image
- **THEN** it adds 2,048 image tokens without text-tokenizing either image body or URL

#### Scenario: Count tool-result pixels and hints exactly where sent
- **WHEN** two native tool results each include an image, hint and identity text, while an older result contains only an attachment reference
- **THEN** the estimate adds 2048 image tokens plus text costs for sent data/hints/references and no image cost for the unloaded older reference
