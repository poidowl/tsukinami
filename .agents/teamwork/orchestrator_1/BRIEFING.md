# BRIEFING — 2026-11-19T02:56:30Z

## Mission
Plan, build, and verify an ASR (Automatic Speech Recognition) project ("ASRをつくって遊びたい") in `/home/antigravity/poidowl/tsukinami`, following the Project Pattern with Dual Track (Implementation + E2E Testing) and reporting back to Project Sentinel when complete.

## 🔒 My Identity
- Archetype: Project Orchestrator (`orchestrator_1`)
- Level: Top-level Project Orchestrator
- Roles: orchestrator, user_liaison, human_reporter, successor
- Working directory: /home/antigravity/poidowl/tsukinami
- State folder: /home/antigravity/poidowl/tsukinami/.agents/teamwork/orchestrator_1
- Original parent: Project Sentinel (`sentinel_1`)
- Original parent conversation ID: 80e2296c5c27c3154be60da7a8e18aa5

## 🔒 My Workflow
- **Pattern**: Project Pattern (Dual Track: Implementation Track + E2E Testing Track)
- **Scope document**: /home/antigravity/poidowl/tsukinami/PROJECT.md
- **Survey**: Spawn 3 Explorers in parallel to map workspace, environment, and ASR design scope.
1. **Decompose**: Break scope into 3-7 module-boundary milestones (or single cycle if small) + parallel E2E Testing Track.
2. **Dispatch & Execute**:
   - **Direct (iteration loop)** (if single cycle): Explorer (3) -> Worker (1) -> Parallel Verification Wave [Reviewer (2) + Challenger (2) + Forensic Auditor (1)] -> Gate
   - **Delegate (sub-orchestrator)** (if multi-milestone): Spawn sub-orchestrator per milestone + E2E Testing Orchestrator in parallel.
3. **On failure** (in this order):
   - Retry -> Replace -> Skip (never skip Auditor) -> Redistribute -> Redesign
4. **Succession**: Self-succeed at 20 spawns (once non-sub-orchestrator subagents complete).
- **Work items**:
  1. Step 0 Survey (3 Explorers) [in-progress]
  2. Assess & Decompose / PROJECT.md [pending]
  3. Implementation Track & E2E Testing Track [pending]
  4. Final verification & report to Sentinel [pending]
- **Current phase**: 0 (Survey)
- **Current focus**: Running 3 Survey Explorers in parallel

## 🔒 Key Constraints
- DISPATCH-ONLY orchestrator: never write source code, never run build/test commands, never explore code directly.
- Never reuse a subagent after it has delivered its handoff — always spawn fresh.
- Always include `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md` verbatim path in every subagent dispatch.
- Forensic Auditor INTEGRITY VIOLATION is a non-negotiable binary veto.

## Current Parent
- Conversation ID: 80e2296c5c27c3154be60da7a8e18aa5
- Updated: 2026-11-19T02:56:30Z

## Key Decisions Made
- Starting Step 0 Survey with 3 parallel Explorers (Codebase, Environment, ASR Design).

## Team Roster
| Agent | Type | Work Item | Status | Conv ID |
|-------|------|-----------|--------|---------|
| explorer_survey_1 | teamwork_preview_explorer | Codebase & Repo Structure Survey | in-progress | c89b90887377a3d6084a85cb49f24072 |
| explorer_survey_2 | teamwork_preview_explorer | Runtime Environment & Tooling Survey | in-progress | 024fb1857793c01000f2ba8e7e46d35a |
| explorer_survey_3 | teamwork_preview_explorer | ASR Architecture & Playability Survey | in-progress | a68f75f61e3e4b91356f24072 |

## Succession Status
- Succession required: no
- Spawn count: 3 / 20
- Pending subagents: c89b90887377a3d6084a85cb49f24072, 024fb1857793c01000f2ba8e7e46d35a, a68f75f61e3e4b91356f24072
- Predecessor: none
- Successor spawned: not yet spawned
- Successor generation: none
- Successor state folder: none

## Active Timers
- Heartbeat cron: dae8e1c02ad3da5e30ef373936de6d57/task-11
- Safety timer: none

## Artifact Index
- `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md` — Original user request
- `/home/antigravity/poidowl/tsukinami/.agents/teamwork/orchestrator_1/DISPATCH.md` — Dispatch log
- `/home/antigravity/poidowl/tsukinami/.agents/teamwork/orchestrator_1/progress.md` — Progress & heartbeat log
