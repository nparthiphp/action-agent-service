# Action Agent console (React)

The separate web console for the Action Agent core: runs and approvals, the step lane, the action
catalog and the audit trail. It only calls the core's HTTP API. The core also serves a built-in
single-page console at `/` that needs no Node; this one is for a team that wants to extend the UI.

Stack: React 18, TypeScript, Vite. No router or UI library.

## Run it (development)

```bash
# 1. the core, in the repo root
uvicorn action_agent.core.app:create_app --factory --port 8000

# 2. this console (Node 20 or newer)
cd ui
npm install
npm run dev          # http://localhost:5173
```

The dev server proxies `/v1` to the core, so no CORS setup is needed. Another core address:
`AA_CORE_URL=http://host:8000 npm run dev`.

## Build and deploy

`npm run build` writes static files to `dist/`. `docker compose up --build` in the repo root also starts
the console at http://localhost:8080 (nginx serves it and proxies `/v1` to the core). The Docker files
are untested.

To host it on a different origin from the core, set `VITE_API_BASE=https://core.example` at build time
and `AA_CORS_ORIGINS=https://console.example` on the core.

## Layout

| Path | What it holds |
|---|---|
| `src/api.ts`, `src/types.ts` | The only code that talks to the core, and its response types |
| `src/App.tsx` | Shell, polling, kill switch, audit check |
| `src/views/` | Runs, run detail with approval, catalog, audit trail |
| `src/components/` | Step lane, pills, logo |
| `src/theme.css` | Theme tokens in the first block (`--vm-*`) |

## Limits

- No sign-in: the approver name is typed in and not verified. Add SSO at the gateway and take the
  approver from the verified identity.
- The VertexMind logo mark, colors and fonts are placeholders, not official brand assets. Change the
  tokens at the top of `theme.css`.
- Polls every 4 seconds. There is no live push.
- No automated UI tests yet.
