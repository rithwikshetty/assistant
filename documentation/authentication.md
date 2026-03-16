# Authentication and Session Model

`assistant` does not ship a user login flow.

## Runtime Model

- the backend auto-provisions a single local workspace user
- the frontend bootstraps directly from `GET /auth/me`
- there is no sign-in screen, logout flow, refresh-token flow, or external identity provider

## HTTP Behavior

- frontend API requests use the shared `fetchWithAuth(...)` helper
- in the current open-source build this is just the common request wrapper used by the app
- the backend resolves the workspace user server-side through `backend/app/auth/dependencies.py`

## WebSocket Behavior

- the shared chat socket connects to `/conversations/ws`
- the socket no longer requires a bearer token in the query string
- conversation and project authorization is still enforced server-side against the local workspace user

## Authorization Model

- authorization stays in backend services
- conversation and project access checks still run on the server
- role checks still exist in code paths that use them, but the default local workspace user is non-admin

## Relevant Files

- [backend/app/auth/local_user.py](../backend/app/auth/local_user.py)
- [backend/app/auth/dependencies.py](../backend/app/auth/dependencies.py)
- [backend/app/auth/routes.py](../backend/app/auth/routes.py)
- [backend/app/chat/routes/ws.py](../backend/app/chat/routes/ws.py)
- [frontend/contexts/auth-context.tsx](../frontend/contexts/auth-context.tsx)
- [frontend/lib/api/auth.ts](../frontend/lib/api/auth.ts)
