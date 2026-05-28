# Repository Guidelines: CustomAI Kazakhstan (Кеден Көмекшісі)

All agents operating in this repository must strictly adhere to the guidelines, architectural boundaries, and orchestration model defined below.

---

## 1. Orchestration Model: Write-Review Flow

Development follows a strict separation of **planning** and **execution**.

### 1.1 Main Agent (Orchestrator)
Responsible for:
- Plan development and architecture design
- Authoring and reviewing **flow documents** (via `flow-first` and `flow-review` skills)
- Task delegation to sub-agents via the `task` tool
- Final code and flow review before task closure
- Running `sync-flows` as the final quality gate

**Hard Rules:**
- The Main Agent must **never** perform direct codebase search, research, or direct code edits if the work can be delegated.
- The Main Agent is the **sole authority** for flow documents. Sub-agents must not modify `flows/` directly.

### 1.2 Sub-Agents (Executors via `task` tool)
Responsible for:
- Codebase searching and structural research
- File modifications, feature implementation, refactoring
- Writing and running targeted tests

**Hard Rules:**
- Sub-agents must skip formatting and linting passes — these are executed globally by the Main Agent at the end of the work batch.
- Sub-agents must **never** modify flow documents. If implementation diverges from the flow, the sub-agent must stop and escalate to the Main Agent.

---

## 2. Flow-Based Development Lifecycle (Flow-First)

Non-trivial tasks must adhere to the four-stage flow-first lifecycle. Trivial changes (copy fixes, style-only, isolated refactors with existing tests) are exempt.

### Mandatory Flow Triggers
A feature **must** start with a flow when it involves any of:
- Multiple states or transitions
- Async behavior, real-time messages, reconnects, stale state
- Session lifecycle or multi-user/multi-agent coordination
- Persistence, save/load, double-trigger risk, or side effects
- Hidden information, permissions, authorization, or role-specific views
- Cross-flow boundaries (events shared between flows)

### The Four Stages

| Stage | Skill | Owner | Gate |
|---|---|---|---|
| **1. Design** | `flow-first` | Main Agent | — |
| **2. Review** | `flow-review` | Main Agent | Must pass Approval Bar before coding starts |
| **3. Implement** | Sub-agents | Sub-agents | Code must match the approved flow |
| **4. Sync** | `sync-flows` | Main Agent | Must pass before task is marked done |

### Flow-Code Contract (Critical)
1. **No code is written** until `flow-review` approves the flow document.
2. **No flow is updated by sub-agents.** If a sub-agent discovers the flow is wrong during implementation, they must **stop coding**, leave a clear comment, and return the task to the Main Agent with the finding.
3. **No task is closed** until `sync-flows` passes on every affected flow.
4. **Drift is a blocker.** A flow that contradicts the code is worse than no flow — it actively misleads future agents.

---

## 3. Flow Artifacts Governance

### Directory Layout
```
flows/
├── ARCHITECTURE.md      # System-level cross-flow map (mandatory for multi-flow projects)
├── features/            # Feature-level behavior
├── sessions/            # Session lifecycle (if applicable)
├── api/                 # API contract and integration flows
├── auth/                # Authentication and authorization flows
├── realtime/            # WebSocket, reconnect, fanout
├── integrations/        # External service integrations
└── templates/           # Reusable templates
```

### Flow Document Ownership
| Action | Allowed Agent |
|---|---|
| Create a new flow | Main Agent (via `flow-first`) |
| Update an existing flow | Main Agent (via `flow-first`) |
| Review a flow | Main Agent (via `flow-review`) |
| Fill Implementation Trace (Section 12) | Sub-agent (during implementation) |
| Verify flow-code sync | Main Agent (via `sync-flows`) |

### Architecture Map Rules
- `flows/ARCHITECTURE.md` must exist if the project contains more than one flow document.
- Every arrow in the map must have matching incoming/outgoing events in both flow documents.
- Orphan events (declared but never received) are **blockers** in `flow-review`.

### Flow Lifecycle Management (Archiving)

To keep active folders clean and focused, the Main Agent (Orchestrator) manages the lifecycle of flow documents. Active directories (e.g., `flows/features/`) must only contain flows in active design, review, or implementation.

#### When to Archive a Flow
A flow document must be moved to the archive directory (`flows/archive/`) when:
1. ✅ **Implementation is complete** (all sub-agent code changes are done and merged).
2. ✅ **`sync-flows` passes** with no drift or unresolved implementation bugs.
3. ✅ **Feature is shipped** to production or marked as fully released.
4. ✅ **No active changes** or developments are planned for the next 30+ days.

#### Archive Procedure (Main Agent Only)
1. Verify that `sync-flows` returned an `IN SYNC` status on the target flow.
2. Move the flow document to the archive folder, organizing it by time-period/release (e.g., quarter/year):
   ```bash
   mv flows/features/feature-x.md flows/archive/2026-Q2/feature-x.md
   ```
3. Update `flows/ARCHITECTURE.md`:
   - Change the flow's subgraph style or append an `[archived]` style (e.g., grayed-out or dashed lines).
   - Add a comment/label next to the flow node, e.g., `[ARCHIVED 2026-05-29]`.
4. Commit the change with conventional message: `chore(flows): archive feature-x flow after production release`.

#### When NOT to Archive
- ❌ The flow has unresolved product questions or blockers.
- ❌ `sync-flows` reveals unresolved code-documentation drift.
- ❌ The feature is in active development (even if paused temporarily).
- ❌ The flow is referenced by other active flows (verify ARCHITECTURE.md connections).

#### Unarchive Procedure
If development resumes on an archived flow:
1. Move the file back to active directory: `mv flows/archive/2026-Q2/feature-x.md flows/features/feature-x.md`.
2. Update `flows/ARCHITECTURE.md` to restore its active visual styling.
3. Run `flow-review` on the unarchived flow before implementing any new changes (to ensure it has not rotted with respect to the rest of the ecosystem).
4. Commit: `chore(flows): unarchive feature-x for new development`.

#### Automated Archive Checks (Weekly)
On a regular basis (e.g., every Monday or session startup), the Main Agent should scan for active flows that:
- Have an `Implementation Trace` status of "Complete".
- Passed the latest `sync-flows` audit.
- Have not been modified for 30+ days.
- Are not referenced as active dependencies by other active flows.

**Action:** Present an archive recommendation to the user:
> "The following flows appear complete and inactive:
> - flows/features/feature-x.md (last modified: 2026-04-28)
> - flows/features/feature-y.md (last modified: 2026-05-01)
> 
> Move them to flows/archive/? (yes/no/defer)"
---

## 4. Project Structure Template

```
smartkeden/
├── backend/                 # Python 3.12 + FastAPI (e.g., Python FastAPI, Go, Node)
│   ├── app/core/                # Deterministic core logic (no LLMs, no IO)
│   │   ├── calculation/
│   │   ├── rag/
│   │   └── hs_classifier/
│   ├── app/services/            # External integrations, APIs, caches
│   ├── app/                 # HTTP/WS handlers, controllers
│   └── tests/               # Backend tests
├── frontend/                # Next.js 15 + React + TypeScript (e.g., Next.js, React Native, Swift)
│   ├── src/
│   └── tests/
├── flows/                           # Flow documents (see §3)
├── docs/                            # Non-flow documentation
└── scripts/                         # Build/deploy utilities
```

**Deterministic Core Rule:** All business-critical calculations, state machines, and rule engines MUST live inside `app/core/`. Never use LLMs or dynamic scripts for deterministic logic. Keep inputs and outputs fully typed.

---

## 5. Build, Test, and Development Commands

### 5.1 Environment Isolation (Mandatory)
All agents must execute runtime commands strictly within the project's isolated environment:
- **Environment path:** `.venv/` (e.g., `.venv/`, `node_modules/`, `.direnv/`)
- **Forbidden:** Global package installation, system-wide tooling, `--user` flags.

### 5.2 Command Matrix

| Action | Command |
|---|---|
| **Backend dev server** | `.venv/Scripts/uvicorn app.main:app --reload --app-dir backend` |
| **Backend tests** | `.venv/Scripts/pytest backend/tests/` |
| **Backend linter** | `.venv/Scripts/ruff check .` |
| **Backend formatter** | `.venv/Scripts/ruff format .` |
| **Frontend dev server** | `npm run dev --prefix frontend` |
| **Frontend build** | `npm run build --prefix frontend` |
| **Frontend linter** | `npm run lint --prefix frontend` |
| **Global format/lint** (Main Agent only) | `.venv/Scripts/ruff format . && npm run lint --prefix frontend && .venv/Scripts/ruff check . && npm run lint --prefix frontend` |

### 5.3 Sub-Agent Lint Exemption
Sub-agents must **skip** linting and formatting passes during implementation. These are run once by the Main Agent after all sub-tasks in the batch complete.

---

## 6. Coding Style & Conventions

| Area | Rule |
|---|---|
| **Type Safety** | Pydantic for all Python models, strict TypeScript for all frontend code (e.g., "Strict TypeScript", "Pydantic for all Python models", "Zod for all API boundaries") |
| **Naming** | snake_case for Python, camelCase for TypeScript, PascalCase for React components (e.g., "snake_case for Python, camelCase for TypeScript") |
| **Comments** | Code comments and symbol names must be in **English**. |
| **User-facing text** | Must be in **RU and KZ** (e.g., "RU and KZ", "EN only", "i18n via `react state / inline`") |
| **Styling** | Tailwind CSS v4 (e.g., "Tailwind CSS v4", "CSS Modules", "Styled Components") |

---

## 7. Commit & PR Guidelines

### Commit Message Format
Strict `prefix: message` pattern (Conventional Commits):

```
<type>(<scope>): <subject>

[optional body]
[optional footer]
```

### Valid Types
`feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `ci`

### Scope Convention
Scope must match the flow or module touched:
- `feat(calc): ...`
- `fix(hs-picker): ...`
- `chore(flow-review): ...`
- `docs(flows): add feature-X flow document`

### Flow-First Commit Pattern
When implementing a flow-first feature, the commit history must reflect the lifecycle:
1. `docs(flows): add flow document for feature-X`
2. `feat(calc): implement feature-X per flow`
3. `test(calc): add targeted tests for feature-X flow`
4. `chore(flows): sync feature-X flow with implementation`

### PR Requirements
A PR that touches non-trivial logic must include:
- [ ] Flow document created/updated in `flows/`
- [ ] `flow-review` approval recorded (linked in PR description)
- [ ] `sync-flows` passed on the final diff
- [ ] Implementation Trace (Section 12 of the flow) filled with actual file paths

---

## 8. Agent Boundaries & Escalation

### When Sub-Agents Must Escalate
A sub-agent must stop work and return the task to the Main Agent when:
1. The flow document is **ambiguous or incomplete** for the implementation task.
2. The implementation **diverges** from the approved flow (even for a "good reason").
3. A **new edge case** emerges during coding that is not in the flow's Section 7.
4. A **cross-flow boundary** is discovered that is not in `ARCHITECTURE.md`.

### When Main Agent Must Re-Invoke Flow Skills
1. After any sub-agent escalation about flow divergence → `flow-first` (update) → `flow-review` (re-approve) → re-delegate.
2. Before marking any task done → `sync-flows`.
3. When a new non-trivial feature is requested → `flow-first`.

### Forbidden Actions
- **Sub-agents:** Modifying `flows/` directly, closing tasks without `sync-flows` pass.
- **Main Agent:** Writing implementation code, bypassing `flow-review` for non-trivial features, merging PRs with failing `sync-flows`.

---

## 9. Project-Specific Configuration

> **Fill this section per-project.** The values below override the templates above.

```yaml
PROJECT_NAME: "CustomAI Kazakhstan (Кеден Көмекшісі)"
BACKEND_STACK: "Python 3.12 + FastAPI"
FRONTEND_STACK: "Next.js 15 + React + TypeScript"
VENV_PATH: ".venv/"

BACKEND_DEV_CMD: ".venv/Scripts/uvicorn app.main:app --reload --app-dir backend"
BACKEND_TEST_CMD: ".venv/Scripts/pytest backend/tests/"
BACKEND_LINT_CMD: ".venv/Scripts/ruff check ."
BACKEND_FMT_CMD: ".venv/Scripts/ruff format ."

FRONTEND_DEV_CMD: "npm run dev --prefix frontend"
FRONTEND_BUILD_CMD: "npm run build --prefix frontend"
FRONTEND_LINT_CMD: "npm run lint --prefix frontend"

GLOBAL_FMT_CMD: ".venv/Scripts/ruff format . && npm run lint --prefix frontend"
GLOBAL_LINT_CMD: ".venv/Scripts/ruff check . && npm run lint --prefix frontend"

TYPE_SAFETY_RULE: "Pydantic for all Python models, strict TypeScript for all frontend code"
NAMING_CONVENTION: "snake_case for Python, camelCase for TypeScript, PascalCase for React components"
LOCALE_LIST: "RU and KZ"
STYLING_RULE: "Tailwind CSS v4"
```