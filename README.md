# CrewGraph

## Problem statement and track

CrewGraph is a prototype for the **Agent Memory and Coordination** track. It coordinates software-building agents through a shared FalkorDB graph, with a separate graph selected for each project. Agents do not call one another directly: scheduling, claims, handoffs, evidence, bugs, and release approval are shared through graph state.

## Architecture

```mermaid
flowchart LR
    Browser[Dashboard<br/>Cytoscape.js] --> API[FastAPI]
    API --> Graph[(FalkorDB<br/>one graph per project)]
    Planner[Planner] --> Graph
    Orchestrator[Orchestrator] --> Graph
    Orchestrator --> Workers[Backend / frontend / tester / security]
    Workers --> Graph
    Workers --> Workspace[workspace/project-id]
    Tester[HTTP tester] -->|real localhost requests| Workspace
    Task -- "DEPENDS_ON" --> Task
    Task -- "PART_OF" --> Project
    Skill[Skill (declared)]
    Artifact -- "FOR_TASK" --> Task
    Artifact -- "PRODUCED_BY" --> Agent
    Task -- "HANDED_OFF_TO" --> Agent
    Bug -- "FOUND_IN" --> Artifact
    Artifact -- "FIXES" --> Bug
    Project -- "APPROVES" --> Approval
    Vulnerability -- "FOUND_IN" --> Artifact
    Event[Timestamped Event] --> Graph
    Lesson --> Graph
    Episode[Episode (declared)]
    Review[Review (declared)]
```

The persisted model labels declared in [app/schema.py](./app/schema.py) are `Project`, `Task`, `Agent`, `Skill`, `Artifact`, `Bug`, `Vulnerability`, `Episode`, `Lesson`, `Approval`, and `Review`. `Event` is also created at runtime by [record_event](./app/queries.py), though it is not in the schema label tuple. The arrows above show relationships written by the current application; the schema also declares `NEEDS`, `HAS_SKILL`, `FIXED_BY`, `BLOCKS`, `REVIEWS`, and `DERIVED_FROM`, but current runtime queries do not create those edges. Repairs currently use the actual `Artifact-[:FIXES]->Bug` direction.

## Why a graph

FalkorDB is the system of record, not an optional cache. The application selects one graph per project ID. Removing FalkorDB breaks task scheduling, atomic claims, artifact and bug context, persisted events, and the release gate; there is no in-memory coordination fallback.

All application Cypher is kept in named functions in `app/queries.py`. These are the core statements copied from those functions.

### Scheduling and atomic claims

`ready_tasks(graph)` reads pending or ready tasks only when every dependency is done:

```cypher
MATCH (task:Task)
WHERE task.status IN ['pending', 'ready']
OPTIONAL MATCH (task)-[:DEPENDS_ON]->(dependency:Task)
WITH task,
     count(dependency) AS dependency_count,
     sum(CASE WHEN dependency.status = 'done' THEN 1 ELSE 0 END) AS done_count
WHERE dependency_count = done_count
RETURN task
```

`claim_task(...)` is one guarded write query. A worker changes a task to `claimed` only if the task is still `ready`; the concurrent integration test synchronizes 20 independent connections and asserts exactly one winner:

```cypher
MATCH (task:Task {id: $task_id})
WHERE task.status = 'ready'
SET task.status = 'claimed',
    task.claimed_by = $agent,
    task.lease_until = timestamp() + ($lease_seconds * 1000)
RETURN task
```

`complete_task(...)` marks a task done, then promotes pending tasks whose dependencies are all done:

```cypher
MATCH (task:Task {id: $task_id})
SET task.status = 'done'
RETURN task
```

```cypher
MATCH (task:Task {status: 'pending'})
OPTIONAL MATCH (task)-[:DEPENDS_ON]->(dependency:Task)
WITH task,
     count(dependency) AS dependency_count,
     sum(CASE WHEN dependency.status = 'done' THEN 1 ELSE 0 END) AS done_count
WHERE dependency_count = done_count
SET task.status = 'ready'
```

### Handoffs and evidence

`handoff(...)` stores the destination agent and reason on a task-to-agent relationship:

```cypher
MATCH (task:Task {id: $task_id})
MERGE (recipient:Agent {name: $to_agent})
MERGE (task)-[handoff:HANDED_OFF_TO {from_agent: $from_agent}]->(recipient)
SET handoff.reason = $reason,
    handoff.ts = timestamp()
RETURN task
```

`handoff_context(graph, task_id)` returns the task, artifacts from its dependencies and itself, open bugs or vulnerabilities linked to those artifacts, and lessons in one read query:

```cypher
MATCH (task:Task {id: $task_id})
OPTIONAL MATCH (task)-[:DEPENDS_ON]->(:Task)<-[:FOR_TASK]-(dependency_artifact:Artifact)
OPTIONAL MATCH (task)<-[:FOR_TASK]-(own_artifact:Artifact)
WITH task,
     collect(DISTINCT dependency_artifact)
         + collect(DISTINCT own_artifact) AS artifacts
OPTIONAL MATCH (issue)-[:FOUND_IN]->(artifact:Artifact)
WHERE artifact IN artifacts
  AND issue.status = 'open'
  AND (issue:Bug OR issue:Vulnerability)
WITH task, artifacts, collect(DISTINCT issue) AS issues
OPTIONAL MATCH (lesson:Lesson)
RETURN task, artifacts, issues, collect(DISTINCT lesson) AS lessons
```

`record_bug(...)` routes a finding to the artifact that caused it:

```cypher
MATCH (artifact:Artifact {id: $artifact_id})
MERGE (bug:Bug {id: $bug_id})
SET bug.title = $title,
    bug.severity = $severity,
    bug.status = $status,
    bug.kind = $kind,
    bug.fix_suggestion = $fix_suggestion
FOREACH (_ IN CASE WHEN $line IS NULL THEN [] ELSE [1] END |
    SET bug.line = $line)
MERGE (bug)-[:FOUND_IN]->(artifact)
RETURN bug
```

`open_bugs(graph)` retrieves open bugs together with their source artifact:

```cypher
MATCH (bug:Bug {status: 'open'})-[:FOUND_IN]->(artifact:Artifact)
RETURN bug, artifact
ORDER BY bug.id
```

### Lease recovery and release gate

At the start of each orchestrator iteration, `recover_expired_leases(...)` returns expired claims to ready state and records why:

```cypher
MATCH (task:Task)
WHERE task.status = 'claimed'
  AND task.lease_until <= $now
  AND task.status <> 'done'
SET task.status = 'ready',
    task.failure_reason = 'Recovered expired lease'
REMOVE task.claimed_by, task.lease_until
RETURN task
```

`release_status(...)` runs the following reads on the project graph:

```cypher
MATCH (project:Project {id: $project_id}) RETURN project
```

```cypher
MATCH (task:Task) RETURN task
```

```cypher
MATCH (bug:Bug {status: 'open'}) RETURN bug
```

```cypher
MATCH (:Project {id: $project_id})-[:APPROVES]->
      (approval:Approval {status: 'approved'})
RETURN approval
```

The function's Python checks require the project to exist, every task to be `done`, no open bugs, and an approved `Approval`. Only then can the orchestrator create and complete the release task. The release-status endpoint separately reports whether that release task is done.

### What breaks if FalkorDB is removed

| Feature | Without FalkorDB |
|---|---|
| Tenant/project selection | Project graphs cannot be selected or listed. |
| DAG scheduling | Dependency edges and ready-task filtering are unavailable. |
| Atomic claims and recovery | Workers cannot coordinate exclusive claims or recover persisted leases. |
| Handoffs and context | Workers lose shared artifacts, bug evidence, and lesson context. |
| Bug repair and events | Bug-to-artifact routing, fix links, and persisted event feed disappear. |
| Release gate | Approval, open-bug checks, and task completion have no shared source of truth. |
| Dashboard graph | There are no persisted nodes or relationships to display. |

## Track focus areas

| Focus area | Current coverage | Simplification |
|---|---|---|
| Episodic memory | Timestamped `Event` nodes record claims, artifacts, bugs, fixes, and task completion. | `Episode` is only a declared label; there is no summarization or episodic retrieval system. |
| Semantic memory | `Lesson` nodes can be stored and are included in handoff context. | Lessons are not automatically learned, ranked, or curated. |
| Procedural memory | Skill-tagged tasks are scheduled to agents by a fixed skill-to-agent mapping. | This is a small hard-coded worker set, not a general procedure/tool registry. |
| Shared state and handoffs | Tasks, dependencies, artifacts, bugs, and handoff context are persisted in each project's graph. | Agents do not communicate outside the graph; no distributed message broker is used. |
| High concurrency | A 20-thread barrier test proves one winner for one task. A 50-worker contention benchmark is recorded below. | Benchmark query actions are capped at eight in flight because an uncapped attempt exceeded FalkorDB's pending-query limit. |
| Tenant isolation | Each tenant's project IDs are prefixed with its slug and select distinct FalkorDB graphs. | Demo authentication is not production security; see the warning below. |

## LLM mode and synthetic agents

### Project video

[Watch the CrewGraph demo](https://youtu.be/sXJUd8g7dJc).

The default is `LLM_PROVIDER=mock`, so the demo runs without a key or model network request. The mock planner returns a canned DAG; mock workers and debugger return canned file contents. The following parts are real application behavior: graph scheduling and atomic claims, graph-backed handoffs, real HTTP checks against the generated app on localhost, static security scanning, bug/fix links, lease recovery, human approval, and the release gate.

The dashboard shows the active provider as **Mock LLM mode** or **Live LLM**. Its prompt is sent to the planner; mock mode intentionally keeps the canned DAG, while a configured live provider can produce a prompt-specific plan. The graph, recent-event caption, stage transitions, progress bar, and animations use persisted FalkorDB state and real `/events` results; replay does not synthesize events.

The dashboard defaults to **Simple view**, a symmetric prompt-to-output pipeline with Plan, Backend/Frontend, Test, Scan, Approve, and Release steps. Agent, artifact, and event nodes are hidden there; an open bug appears below Test and turns green with a **Fixed** label when resolved. Node positions are cached and fixed, and full titles remain available as tooltips. **Detailed view** preserves the full fixed-lane graph: dependency-ordered task columns, agents above their tasks, and versioned artifacts and findings below. The Project node and `PART_OF` edges remain in FalkorDB but are omitted from both canvases.

Event presentation is paced in the browser as a step-by-step tutorial, with at least 1500ms between live visual steps. The caption, highlighted node, traveling edge dot, and task progress advance from persisted `/events` records; after playback drains, the display reconciles to the authoritative graph state. Choose 0.5×, 1×, or 2× for animation speed; Replay uses the same queue at 2× by default. For demo pacing for viewing, `/demo/run` waits 1200ms between agent claims by default (`DEMO_STEP_DELAY_MS=1200`); set it to `0` to run without the server-side pauses. Tests and direct demo/load-test scripts use zero delay.

The dashboard and login use a white, light-theme background while retaining high-contrast graph status colors.

The page uses a full-height 58/42 graph/output split. Output tabs identify graph-recorded files and versions; a newly created artifact opens automatically with a typewriter preview, while clicking a tab shows it instantly. The output status reflects Building, Waiting approval, or Released. Recent events and selected-node details are tucked into a collapsed drawer. The read-only preview reads the selected registered file from that project's workspace; paths are confined to the project workspace and previews are limited to 256 KiB.

An OpenAI Chat Completions provider is wired in [agents/llm.py](./agents/llm.py), but live model output is not covered by the tests or a live API run here. To use it, supply your own model and key in the current shell; never put a real key in source control.

```powershell
$env:LLM_PROVIDER = "openai"
$env:LLM_MODEL = "your-model-name"
$env:LLM_API_KEY = "your-key"
```

POSIX shell:

```sh
export LLM_PROVIDER="openai"
export LLM_MODEL="your-model-name"
export LLM_API_KEY="your-key"
```

`LLM_PROVIDER` supports `mock` and `openai`; the latter requires `LLM_MODEL` and `LLM_API_KEY`. Automated tests stub the HTTP transport and use only a synthetic key.

### What each agent actually does

| Agent | Implemented behavior |
|---|---|
| Planner | Requests a task DAG, validates JSON, IDs, dependencies, and cycles, then stores it in the project graph. Mock mode returns a fixed four-task DAG. |
| Backend | Writes the FastAPI to-do API and its API contract as graph-linked artifacts. Mock mode supplies fixed file contents. |
| Frontend | Reads the API contract from its graph handoff context and writes the page; it never contacts the backend agent. Mock mode supplies fixed page contents. |
| Tester | Reads the contract, starts the generated API on a free `127.0.0.1` port, and checks real HTTP responses, including invalid input. HTTP results—not an LLM verdict—complete or fail the task. |
| Security | Scans generated files for the implemented patterns (secrets, wildcard CORS, debug mode, unsafe execution/pickle, and missing POST validation) and records linked findings. It does not call an LLM. |
| Debugger | Reads open bugs and their source artifacts from graph context, writes a repaired file artifact, and links it as a fix. In mock mode its repair content is canned. The orchestrator retries failed tester or security work at most twice. |

There is no standalone reviewer agent in this implementation; `Review` is only a declared model label.

## Setup and run

### Docker one-command setup

Requirements: Docker with Compose.

#### Persistence investigation (baseline before the fix)

In the original Compose configuration, a demo project disappeared after `docker compose down` and `docker compose up -d`. Inspection showed Redis `appendonly` was `no`, and its active data directory was `/var/lib/falkordb/data`, while the Compose named volume was mounted at `/data`. Thus Redis wrote outside the mounted volume, and the default snapshot policy did not guarantee a snapshot for the small demo before the container was removed. The Compose setup now aligns the image's `FALKORDB_DATA_PATH` with `/data` and enables AOF plus Redis snapshots through the image's documented `REDIS_ARGS` startup arguments. See the official image [`run.sh`](https://github.com/FalkorDB/FalkorDB/blob/master/build/runtime/run.sh) and [`Dockerfile`](https://github.com/FalkorDB/FalkorDB/blob/master/build/runtime/Dockerfile).

```powershell
docker compose up -d --build
```

The API waits for a healthy FalkorDB service, uses `FALKORDB_HOST=falkordb`, and has its own `/health` check. Open the dashboard at [http://localhost:8000](http://localhost:8000); FalkorDB Browser is at [http://localhost:3000](http://localhost:3000). Stop the stack without deleting its named database volume:

Compose enables demo login by default. Sign in using either synthetic tenant account:

| Tenant | Username | Demo password |
|---|---|---|
| Acme | `acme` | `acme-demo-2026!` |
| Globex | `globex` | `globex-demo-2026!` |

The API stores only PBKDF2 password hashes. The session token is HMAC-signed; Compose's default signing key is `crewgraph-demo-only-change-this-secret` and is **for local demo use only**. Set a private `SECRET_KEY` before sharing a demo. Tests explicitly default `AUTH_ENABLED=false`; Compose defaults it to `true`. To run the stack without login for the local flow checker, set `$env:AUTH_ENABLED = "false"` before `docker compose up -d --build`.

**This is demo authentication, not production security.** The published passwords and default signing key are intentionally synthetic and public. There is no password recovery, rate limiting, account provisioning, TLS enforcement, or production session management. Do not expose this demo service to an untrusted network.

For the authenticated flow checker, set its local demo credentials in the shell:

```powershell
$env:CREWGRAPH_USERNAME = "acme"
$env:CREWGRAPH_PASSWORD = "acme-demo-2026!"
python -m scripts.check_dashboard_flow
```

Without those variables, the flow checker works when `AUTH_ENABLED=false`.

```powershell
docker compose down
```

The database files live under `/data` in the container, backed by the explicitly named Docker volume **`crewgraph_falkordb_data`**. Generated project workspaces are backed by **`crewgraph_workspace_data`**, so registered artifact previews survive container recreation and `docker compose down` too. **Do not run `docker compose down -v` unless you intend to permanently delete the persisted database and workspace data**; `-v` removes both named volumes.

To verify the repair flow and persistence on a running local stack, run `python -m scripts.check_persistence`. It creates a synthetic flawed demo, restarts only the `falkordb` service, checks the project graph, and leaves that project in the database.

### Local Python alternative

Requirements: Python 3.11+ and Docker for FalkorDB. The repository targets Python 3.11; local tests in this checkout were run with Python 3.12.10.

```powershell
docker compose up -d falkordb
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q
python -m scripts.run_demo
uvicorn app.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000). Local Python runs leave auth off unless `AUTH_ENABLED=true` is set. To seed two synthetic tenant graphs for inspection, run `python -m scripts.seed`.

### Demo commands

Run a mock demo, which stops for human approval:

```powershell
python -m scripts.run_demo
```

Approve automatically and run the release task:

```powershell
python -m scripts.run_demo --auto-approve
```

The functional flaw makes the backend accept an empty title; the tester catches the actual HTTP response and the debugger repairs it:

```powershell
python -m scripts.run_demo --flaw --auto-approve
```

The security flaw adds a synthetic fake key and wildcard CORS; the static scanner files bugs, then the repair loop fixes them:

```powershell
$env:DEMO_FLAW = "security"
python -m scripts.run_demo --auto-approve
$env:DEMO_FLAW = "0"
```

All demo app HTTP requests target localhost. The security flaw key is fake; neither mode requires a real API key.

## Tests and measured results

The Python suite uses real local FalkorDB for graph integration tests; temporary test graphs are deleted. The fixed-lane placement logic also has a dependency-free Node test (`node --test tests/test_graph_layout.js`). `tests/conftest.py` disables auth and demo pacing by default, with explicit auth tests opting in. Mock/unit tests do not call a live model provider.

```powershell
python -m pytest -q
```

The 20-project mock load run completed 80 tasks in 11.04 seconds (7.25 tasks/second), with zero failures and no lease recovery. The single-project contention run used 50 worker threads over 500 tasks, with eight query actions in flight: 164.01 successful claims/second, 8.96 ms p95 claim-call latency, zero duplicate claims, 558 reads, and 4,500 writes. These are local measurements, not production capacity claims. Full command output and machine notes are in [docs/load_test_results.md](./docs/load_test_results.md).

## Limitations and future work

- This is a local hackathon prototype. Authentication is demo-only and must not be treated as a production security boundary.
- The mock plan and generated app files are canned. A live LLM provider is wired but not validated against external output in this project run.
- The app under test is a small in-memory to-do API and is not durable.
- The security scanner checks a narrow set of patterns; it is not a comprehensive audit.
- `Skill`, `Episode`, and `Review` are declared labels but are not populated by the current demo flow. Some relationship constants are also model-only and unused; see the graph model notes.
- Dashboard run status is process-local, and there is no distributed worker service or persistent job registry. After an API restart, an existing project may have no transient run status; the dashboard continues to show its persisted graph and release state.
- The dashboard loads pinned Cytoscape.js from a CDN and needs access to that CDN in the browser.
- Future work: persist richer agent episodes and lessons, broaden security checks, validate more model providers, and benchmark unthrottled concurrency against a suitably configured FalkorDB deployment.

Dashboard captures: [login](./docs/img/login.png), [run start](./docs/img/start-run.png), [mid-run pulse](./docs/img/mid-run.png), and [finished output](./docs/img/finished-output.png).
