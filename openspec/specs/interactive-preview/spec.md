# interactive-preview Specification

## Purpose

为 Figura 中所有可用的图片资源提供一致、可访问且安全的细节查看方式，让用户能够在不离开当前运行上下文的情况下检查图像内容。

## Requirements

### Requirement: Supported image resources can open an interactive preview

The client SHALL make an available attachment, visual observation, generated candidate, or generated chart artifact operable as an interactive preview trigger. The trigger SHALL be usable with a pointer or keyboard and SHALL open the corresponding resource without replacing the surrounding workspace context.

#### Scenario: User opens an available image with a pointer

- **WHEN** the user activates an available attachment, visual observation, generated candidate, or generated chart image with a pointer
- **THEN** the client opens an interactive preview for that same image resource
- **AND** the underlying session, run, and metadata context remains intact

#### Scenario: User opens an available image with the keyboard

- **WHEN** keyboard focus is on an available image preview trigger and the user presses Enter or Space
- **THEN** the client opens the same interactive preview as pointer activation
- **AND** the trigger exposes an accessible Simplified Chinese name describing the preview action

#### Scenario: Unavailable image is not opened as a broken preview

- **WHEN** the image resource is pending without usable preview bytes, failed, expired, missing, or unauthorized
- **THEN** the client keeps the status explanation in the inline presentation
- **AND** it does not open a broken-image interactive preview

### Requirement: Interactive preview provides bounded inspection controls

The preview SHALL present the selected image in a bounded overlay that does not expose local source paths or raw resource bytes. It SHALL provide an explicit close action, fit-to-view behavior, and zoom controls with visible current zoom feedback.

#### Scenario: User zooms and fits an image

- **WHEN** the interactive preview is open and the user activates zoom in, zoom out, or fit-to-view
- **THEN** the displayed image changes within the overlay according to the selected control
- **AND** the client keeps the image inside the preview viewport without changing the underlying run data

#### Scenario: User closes the preview

- **WHEN** the user activates the close control, presses Escape, or activates the supported backdrop close area
- **THEN** the overlay closes and focus returns to the preview trigger when that trigger is still mounted

#### Scenario: Preview remains usable for a large image

- **WHEN** the selected image is larger than the available viewport
- **THEN** the client initially fits it within the bounded preview area
- **AND** the user can inspect it through the zoom controls without the overlay escaping the application window

### Requirement: Interactive preview respects resource safety and accessibility

The preview SHALL use the active preview resource boundary and SHALL release temporary client-owned resources when the overlay or its source is no longer needed. The overlay SHALL expose a dialog name, a visible focus treatment, keyboard-operable controls, and status text that does not rely on color alone.

#### Scenario: Preview uses the active resource boundary

- **WHEN** the client opens an image in Mock, Gateway browser, or Tauri mode
- **THEN** it uses the resource resolved for the active backend configuration
- **AND** it does not construct a preview from a local source filename or expose a local server path

#### Scenario: Preview resources are cleaned up

- **WHEN** the preview closes, its source changes, or the owning image component unmounts
- **THEN** the client releases any temporary object URL it created for that resource
- **AND** a later session or run cannot display stale bytes from the previous preview

#### Scenario: Keyboard focus is contained and restored

- **WHEN** the interactive preview opens and the user navigates with a keyboard
- **THEN** focus moves to the named preview dialog and remains operable across its controls
- **AND** closing the dialog restores focus to the originating trigger when possible

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
