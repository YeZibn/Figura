---
name: figura-implementation-record
description: Maintain Figura's implementation-content Markdown when the user asks to record, refine, or reconcile a change's scope, fields, contracts, or actual implementation status. This skill documents decisions; it does not create OpenSpec changes or implement code by itself.
---

# Figura 实现内容记录

Maintain `docs/figura-implementation-content.md` in the Figura repository as the single running record of concrete implementation decisions. The change roadmap names work; this document explains the selected work and its fields. OpenSpec change artifacts, when created, hold the formal change contract.

## Before editing

- Read the relevant section of the implementation record and the matching entry in `docs/figura-implementation-change-roadmap.md`. Inspect current `src/figura/` code and any active Figura OpenSpec change that bears on the request. Use `openspec store list --json` to resolve the Figura store before OpenSpec reads; pass `--store figura` on subsequent supported commands.
- Treat `docs/figura-architecture-design.md` as a design draft and `src/chartagent/` as the old implementation. Consult them when useful, especially when the user requests comparison, but verify each borrowed field or rule against the current Figura decision. Do not silently promote a draft statement to an accepted requirement.
- Separate what the user has confirmed from suggestions, open questions, and code that actually exists. Check current official provider documentation when recording changeable API IDs, parameters, or capabilities.

## Update the record

- Edit the section for the requested change; create a new section in the same document when a new change is discussed. Preserve earlier sections and decisions unless the user revises them. Record a revised decision with its reason and affected downstream changes.
- For implementation fields, specify the relevant type, nullability, owner, source, write timing, persistence or transient lifetime, and public/private exposure. Distinguish user-requested values, server-resolved configuration, immutable Run facts, temporary provider inputs, and normalized results. Include only dimensions that matter to the field.
- State the change's deliverable and its handoff to later changes. Mark items as **已确认**, **暂定**, **待确认**, or **已实现**. Use **已实现** only after inspecting the code; report validation only when it was actually performed.
- If this record conflicts with the roadmap, an active OpenSpec change, or code, name the discrepancy and its impact. Reconcile files only within the user's requested scope; do not create or alter OpenSpec artifacts or application code solely because this recording skill was invoked.

Report the document updated, the main decisions captured, and any unresolved conflict or field. Do not imply that documenting a change means it has been implemented.
