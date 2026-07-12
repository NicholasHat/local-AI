# UI Migration Plan

## Goal

Replace the current Streamlit shell with a professional chat dashboard that feels closer to modern hosted chat products, while keeping the local-only Python backend intact.

The migration should optimize for product quality and a clean separation between presentation and assistant logic, not for minimizing implementation cost.

## Recommended direction

Use a split architecture:

- Python backend for model access, tool dispatch, memory, ingestion, and vector search.
- Web frontend for conversation UI, uploads, document panels, and status.
- A narrow HTTP API between them.

A modern React-based frontend is the safest default if the goal is a polished chatbot interface with good component structure. If you want the lightest possible surface, a single-page HTML/JS dashboard can still work, but it will be harder to keep polished as the app grows.

## Target experience

The final UI should support:

- A chat transcript with distinct assistant, user, and tool-event styling.
- A composer that feels like a professional chatbot input area.
- A left sidebar or dock for documents, status, model settings, and resets.
- Upload and indexing feedback that feels integrated, not bolted on.
- Visual treatment that is calm, intentional, and clearly product-grade.
- Responsive behavior on desktop and mobile.

## Architecture plan

### 1. Define the backend boundary

Introduce a small API layer around the existing Python app.

Minimum endpoints:

- `GET /health`
- `GET /conversation`
- `POST /chat`
- `POST /upload`
- `POST /conversation/reset`
- `GET /documents`

Keep the existing core modules as the source of truth. The frontend should not own assistant state.

### 2. Keep assistant logic stable

Do not move agent decisions into the frontend.

The backend should continue to own:

- conversation memory
- tool dispatch
- document ingestion
- retrieval
- Ollama calls

This preserves testability and keeps the UI migration from disturbing the assistant core.

### 3. Build the frontend as a true app shell

Recommended frontend shape:

- App shell with a persistent sidebar.
- Main conversation pane with message cards.
- Composer pinned to the bottom.
- Document and status panels that can expand or collapse.
- Clear loading, error, and success states.

Visual direction:

- Avoid generic admin-dashboard styling.
- Use a strong type scale, ample whitespace, and subtle surface contrast.
- Treat the empty state and first-run experience as first-class.
- Make tool use visible instead of hiding it in logs.

### 4. Add richer interaction states

Once parity is reached, add:

- streaming tokens or incremental assistant updates
- upload progress and indexing progress
- citations or source chips for document answers
- tool-call event cards
- conversation history browsing

These are second-wave enhancements after the basic API/UI replacement works.

## Migration phases

### Phase A: API extraction

- Add a backend server layer.
- Expose chat and upload endpoints.
- Reuse the current agent, memory, ingest, and vector store modules.
- Write tests around the API contract.

### Phase B: Frontend prototype

- Build a simple chat dashboard against the new API.
- Prove send, receive, upload, and reset flows.
- Match the current Streamlit capabilities first.

### Phase C: Visual refinement

- Replace the prototype styling with a polished design system.
- Add responsive layouts, motion, and better hierarchy.
- Improve empty states, status handling, and document affordances.

### Phase D: Behavior parity and cleanup

- Remove Streamlit-specific assumptions.
- Add integration tests for the new UI flow.
- Keep the old UI only until the new one fully matches functionality.

## Success criteria

The migration is done when:

- the assistant can be used entirely from the browser UI
- the backend still runs locally with Ollama and local files only
- document upload, chat, search, and PDF tools all work from the new frontend
- the interface looks and behaves like a deliberate product, not a quick wrapper

## Decisions (resolved 2026-07-12 — see plan.md Phases 7–12 for the build sequence)

- **Frontend stack: Vite + React + TypeScript + Tailwind**, in `web/`. Next.js
  rejected: single-user local app, no SSR/SEO/server-component needs, and Vite
  keeps the toolchain minimal. Plain HTML/JS rejected: the target experience
  (tool-event cards, document panels, skills editor, model picker) needs real
  component structure.
- **Backend server: FastAPI + uvicorn** (`server.py`), wrapping the existing
  modules unchanged. Pydantic models define the API contract; `TestClient`
  covers it with the same mocked-ollama seam the agent tests use.
- **Streaming: after parity, not in the first replacement.** Same reasoning as
  the original non-streaming-first decision; FastAPI SSE makes it a cheap
  follow-up.
- **Single active conversation, server-side**, exactly as today. Multiple
  conversations and persistence stay in the later-enhancements list.
- The plan also grew two product features that ride on the new API: a **model
  picker** (installed Ollama models, tool-capable badge) and a **skills
  system** (user-authored instruction/code skills the model calls as tools) —
  detailed in plan.md Phases 10 and 11.
