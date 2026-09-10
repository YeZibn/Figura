# Desktop client smoke checklist

Run the automated contract check and production build from `frontend/`:

```bash
npm run smoke
npm run build
```

The browser client uses mock data by default. To use the local Python Gateway,
start it in another terminal and set the explicit frontend mode:

```bash
conda run -n agent python -m chartagent.gateway --port 8765
VITE_CHARTAGENT_MODE=gateway npm run dev
```

For repeatable browser verification, run `npm run dev`, open `http://127.0.0.1:1420/`, and check:

1. The three-panel workspace opens in mock mode.
2. In mock mode, the sample sessions can be selected; the conversation and attachment panel update.
3. The `+` session action creates a named empty session and clears stale attachment content.
4. The sample chart attachment shows its preview, file metadata, and observation state.
5. Tool call/result rows start collapsed and expand through their keyboard-accessible controls.
6. Entering text and pressing Enter shows the user message, thinking indicator, and mock assistant response.
7. An empty session shows the start-analysis empty state; an empty attachment list shows its own empty state.
8. Narrowing the window keeps the composer usable and stacks the secondary panel below the conversation.
9. In Gateway mode, creating a session and submitting text use the local Python service; stopping the service shows a Chinese connection error and does not switch to mock data.
