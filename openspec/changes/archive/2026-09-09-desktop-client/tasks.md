## 1. Frontend and Tauri foundation

- [x] 1.1 Create the React + TypeScript + Vite frontend project with package scripts and a browser development entry.
- [x] 1.2 Add the Tauri 2 desktop shell configuration and development command without introducing Python sidecar packaging.
- [x] 1.3 Add shared frontend TypeScript types for sessions, conversation items, attachments, and run state.

## 2. Client boundary and mock data

- [x] 2.1 Define a replaceable client interface for session listing, session creation, session selection, session data loading, and message submission.
- [x] 2.2 Implement deterministic mock session, conversation, attachment, tool-result, and visual-observation data shaped like the future backend contract.
- [x] 2.3 Add frontend state management for active session, messages, attachments, composer text, loading state, errors, and expanded execution details.

## 3. Workspace interface

- [x] 3.1 Implement the application shell with session, conversation, and attachment/details regions.
- [x] 3.2 Implement session list selection and new-session interaction with active-state and stale-selection reset behavior.
- [x] 3.3 Implement chronological rendering for user, assistant, tool call/result, visual observation, and error items.
- [x] 3.4 Implement collapsed-by-default execution details with accessible expand/collapse controls.
- [x] 3.5 Implement attachment cards with filename, media type, size, preview, and separate registered/loaded/observation states.
- [x] 3.6 Implement the message composer with empty-input validation, submission feedback, and mock assistant response handling.
- [x] 3.7 Localize all user-facing labels, prompts, mock session names, sample messages, and interaction feedback to Simplified Chinese while preserving technical identifiers.

## 4. Responsive states and verification

- [x] 4.1 Add loading, empty, error, and no-attachments states without disrupting the primary conversation workflow.
- [x] 4.2 Add responsive layout behavior for narrow desktop windows so content remains readable and the composer remains usable.
- [x] 4.3 Add frontend tests or a repeatable browser verification covering session switching, new-session creation, message submission, detail expansion, and attachment display.
- [ ] 4.4 Verify the built UI loads in Tauri development mode and document browser and Tauri startup commands using the Conda agent environment where Python commands are involved.
- [x] 4.5 Run OpenSpec validation and review the implementation against every desktop-client scenario before marking the change complete.
