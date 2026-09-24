# attachment-workspace Specification

## Purpose

Let the ChartAgent desktop workspace accept real local images, register them as session-scoped attachments, preview them safely, and provide authorized attachment IDs to the Agent without eagerly loading image bytes into model context.

## Requirements

### Requirement: User can select and preview image attachments

The desktop client SHALL let the user choose one or more supported local image files for the active session. Before upload, it SHALL validate supported media type and configured size limits, show a local preview when the browser provides one, and preserve the selected file's filename and media type in the attachment view.

#### Scenario: Supported image is selected

- **WHEN** the user chooses a supported image file
- **THEN** the workspace shows a local preview and a pending attachment entry without sending the image to the model

#### Scenario: Unsupported or oversized image is rejected

- **WHEN** the user chooses a file with an unsupported media type or size above the configured limit
- **THEN** the workspace shows a Simplified Chinese validation error and does not upload or register the file

#### Scenario: User clears a pending image

- **WHEN** the user removes a selected image before sending it
- **THEN** the local preview is released and the image is absent from the next upload or message request

### Requirement: Gateway registers uploaded images within the active session

The local Gateway SHALL accept a bounded binary upload for an existing named session, validate its media type, size, readability, and content, and return an opaque session-scoped `attachment_id` with safe metadata. Uploaded bytes SHALL be stored below a persistent application-owned attachment directory and SHALL NOT be returned in JSON responses, written into SQLite records, or sent to the model during registration.

#### Scenario: Image upload returns safe metadata

- **WHEN** the desktop client uploads a valid image for an active session
- **THEN** the Gateway returns an `att_...` identifier, filename, media type, byte count, content hash, and availability metadata without a local path or image payload

#### Scenario: Upload survives a Gateway restart

- **WHEN** the Gateway restarts after a valid image upload and the persistent attachment directory remains accessible
- **THEN** the attachment remains registered and loadable through its prior ID

#### Scenario: Upload targets an unknown session

- **WHEN** the client uploads an image using an unknown or malformed session identifier
- **THEN** the Gateway rejects the request without creating an attachment or revealing filesystem details

#### Scenario: Uploaded bytes are isolated by session

- **WHEN** an attachment ID is used from a different session
- **THEN** attachment metadata and image loading are rejected as unauthorized

### Requirement: User can inspect registered attachment metadata

The workspace SHALL retrieve and display the active session's registered attachments, including filename, media type, byte count, attachment ID, preview availability, and a state such as registered, unavailable, or observation available. The metadata response SHALL not expose canonical local paths or raw image bytes. When an attachment is available, the workspace SHALL be able to obtain its preview through the Gateway's session-scoped content resource.

#### Scenario: Registered attachment appears after reload

- **WHEN** an active session with a persistent attachment is loaded after a page or Gateway restart
- **THEN** the attachment panel shows its safe metadata and a preview backed by the Gateway content resource when validation succeeds

#### Scenario: Persistent source is unavailable

- **WHEN** attachment metadata exists but its source is missing, unreadable, changed, or no longer valid
- **THEN** the workspace marks the attachment unavailable, avoids a broken or unauthorized path, and offers the existing re-upload recovery

#### Scenario: Session switch clears stale attachment selection

- **WHEN** the user switches to another session
- **THEN** the attachment panel and pending attachment selection update to the new session without exposing attachments from the previous session

### Requirement: User can remove a registered attachment

The workspace SHALL provide an explicit remove action for a registered attachment. A successful removal SHALL remove it from the active attachment list and prevent it from being selected for future messages; the historical transcript MAY retain a bounded attachment ID reference but SHALL no longer be able to load the source.

#### Scenario: Registered attachment is removed

- **WHEN** the user confirms removal of an attachment that is not being used by an active upload
- **THEN** the Gateway deletes its metadata and source bytes, and the workspace removes it from the attachment panel

#### Scenario: Attachment removal fails

- **WHEN** the Gateway rejects attachment removal or cannot complete the storage operation
- **THEN** the workspace keeps the attachment entry visible, shows a bounded Simplified Chinese error, and does not remove its selection state optimistically

### Requirement: Attachment previews use a safe session-scoped resource

The client SHALL construct previews from a Gateway content URL addressed by the active session ID and opaque attachment ID. Preview requests SHALL not contain or expose canonical local paths, and an unavailable response SHALL be rendered as an unavailable attachment state.

#### Scenario: Available attachment preview is loaded

- **WHEN** the client requests content for an authorized available attachment
- **THEN** the Gateway returns the bounded image bytes with the validated media type and the workspace displays the image

#### Scenario: Preview is unauthorized or invalid

- **WHEN** the client requests content for an attachment from another session or whose source fails validation
- **THEN** the Gateway returns a bounded error and the workspace displays the unavailable state without exposing source details

### Requirement: Messages carry authorized attachment references without eager loading

The desktop client SHALL be able to submit a text message with zero or more attachment IDs belonging to the active session. The Gateway SHALL provide safe attachment metadata to the Agent for that turn, and the Agent MAY call `load_image` when visual inspection is useful. Uploading or attaching an ID SHALL NOT force an image load or include image bytes in the initial model message.

#### Scenario: Text message includes an attachment

- **WHEN** the user sends a message with a registered attachment ID
- **THEN** the Agent receives the text and safe attachment metadata, and the response remains associated with that session

#### Scenario: Agent chooses to inspect the image

- **WHEN** the Agent calls `load_image` with the authorized attachment ID
- **THEN** the existing attachment-access validation runs and the image becomes available only on the next model turn

#### Scenario: Agent does not need visual inspection

- **WHEN** the Agent can answer without examining the image
- **THEN** it may respond without calling `load_image` and infrastructure does not force a model-visible image

### Requirement: Attachment failures are bounded and visible

Attachment registration, lookup, and load failures SHALL return bounded structured errors with stable error codes. The workspace SHALL show actionable Simplified Chinese feedback while preserving the conversation workflow. Errors MUST NOT reveal credentials, canonical paths, raw bytes, or unbounded provider details.

#### Scenario: Changed or missing temporary source

- **WHEN** an attachment source is missing, unreadable, changed, oversized, or no longer authorized
- **THEN** the Gateway rejects the operation with a bounded error and the workspace marks the attachment unavailable

#### Scenario: Upload failure does not corrupt the composer

- **WHEN** an upload fails after the user has entered a message
- **THEN** the workspace shows the upload error, keeps the message text available for correction, and does not submit a message with an unknown attachment ID

### Requirement: Attachment previews use one recoverable resource lifecycle

The desktop client SHALL load registered attachment previews through the client
backend boundary rather than trusting a local filesystem path or embedding
source bytes in session metadata. It SHALL represent loading, available,
unavailable, and invalid-media states separately, and SHALL offer a bounded
retry action when a transient resource request may recover.

#### Scenario: Registered attachment preview loads after reload

- **WHEN** the workspace restores an attachment whose Gateway preview resource
  is available
- **THEN** it displays the image preview and keeps the filename, media type,
  size, and attachment state visible

#### Scenario: Preview request is still loading

- **WHEN** the workspace has metadata for an available attachment but its
  preview request has not completed
- **THEN** it displays a loading state without mislabeling the attachment as
  unavailable or loaded into model context

#### Scenario: Preview failure can be retried safely

- **WHEN** a preview request fails with a retryable transport or temporary
  Gateway error
- **THEN** the workspace preserves the attachment metadata, shows bounded
  recovery feedback, and allows the user to retry without re-registering the
  same source

#### Scenario: Preview bytes are not an implicit model load

- **WHEN** the workspace successfully displays an attachment preview
- **THEN** it does not mark the attachment as loaded into model context or send
  a new Agent request solely because the client displayed the image

### Requirement: Client distinguishes new selection from active source

桌面客户端 SHALL 区分“本次新选择附件”和“当前 session 活动源附件”。发送消息后可以清空待上传选择，但不得在没有用户替换或移除意图时清空活动源。

#### Scenario: Follow-up keeps the active source

- **WHEN** 用户发送首条带图请求后继续发送不带新附件的追问
- **THEN** 后续请求仍携带或引用当前活动源 context
- **AND** 用户不需要重复上传同一图片

### Requirement: Client exposes panel and source recovery states

客户端 SHALL 能显示面板复用、需要源绑定、审核修复中、审核重试耗尽和未发布候选等状态，并使用简体中文提供可行动说明。

#### Scenario: Review repair is visible

- **WHEN** 后端正在依据审核诊断生成新候选
- **THEN** 客户端显示正在修复和重新审核，而不是立即显示运行失败
