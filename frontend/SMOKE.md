# Desktop client smoke checklist

Run the automated contract check and production build from `frontend/`:

```bash
npm run smoke
npm run build
```

For repeatable browser verification, run `npm run dev`, open `http://127.0.0.1:1420/`, and check:

1. The three-panel workspace opens in mock mode.
2. `Chart analysis`, `Sales review`, and `Untitled session` can be selected; the conversation and attachment panel update.
3. The `+` session action creates a named empty session and clears stale attachment content.
4. The sample chart attachment shows its preview, file metadata, and observation state.
5. Tool call/result rows start collapsed and expand through their keyboard-accessible controls.
6. Entering text and pressing Enter shows the user message, thinking indicator, and mock assistant response.
7. An empty session shows the start-analysis empty state; an empty attachment list shows its own empty state.
8. Narrowing the window keeps the composer usable and stacks the secondary panel below the conversation.
