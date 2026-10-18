# Three-minute CrewGraph demo script

## Before recording

1. Start the local stack with `docker compose up -d --build`.
2. Open [http://localhost:8000](http://localhost:8000) and sign in as `acme` with the synthetic demo password `acme-demo-2026!`.
3. Confirm the **Mock LLM mode** badge. The default prompt is prefilled; mock planning and generated file contents are canned.
4. Use only the localhost demo. The graph, events, artifacts, and animations are real persisted project data.
5. The default `DEMO_STEP_DELAY_MS=1200` is demo pacing for viewing. The browser also spaces live visual steps by at least 900ms.

## Timed narration and clicks

| Time | Exact action | Say |
|---|---|---|
| 0:00–0:20 | Show the login screen, then sign in to Acme. Point to the tenant project picker and **Mock LLM mode** badge. | “This demo has two isolated tenants. Projects are stored in separate FalkorDB graphs, and the browser only receives its tenant's project list.” |
| 0:20–0:35 | Keep the default prompt and click **Run demo with flaw**. | “The prompt is sent to the planner. In mock mode the planner and generated content use a canned plan; this secondary button enables one deliberate synthetic backend defect.” |
| 0:35–1:05 | As real tasks become claimed, point out the fixed task columns, agent/file lanes, blue pulsing node, moving stage dot, progress bar, and latest-event caption. | “The dashboard reads persisted `/events` and graph status. A claim event drives the caption and stage transition; the claimed task is the one that pulses. Nothing in this animation is made-up demo data.” |
| 1:05–1:25 | Watch the bug appear, then become fixed; point to the event history. | “The tester makes real HTTP requests against localhost, records the defect against its source artifact, and the debugger writes a repair artifact. The bug shakes on the real finding event and turns green when fixed.” |
| 1:25–1:45 | Point to the output file list, artifact version and agent, then open `main.py` or `dashboard/index.html` in the read-only preview. | “These versions and producers come from graph-linked artifacts. The preview serves the corresponding registered workspace file with path checks and a size cap.” |
| 1:45–2:00 | Click **Replay · 2×** while the graph is still selected. | “Replay reads the project's persisted event history and runs the same event-driven caption, stage-dot, and graph-edge particles at twice the event timing.” |
| 2:00–2:15 | Wait for **Human approval is required**, then click **Approve** once. | “Approval is stored in FalkorDB. The orchestrator rechecks task completion, open bugs, and approval before creating the release task.” |
| 2:15–2:40 | Wait for **Released** and show the finished output panel. | “The output is released only after the graph-backed release gate passes. The output view, task progress, and event timeline all reflect persisted state.” |
| 2:40–3:00 | Optionally log out, then show the screenshots in `docs/img`. | “CrewGraph coordinates through its graph; agents never call each other directly. This is demo authentication, not production security.” |

If a stage changes before a screenshot, start another synthetic run and capture the actual claim window. Do not inject or fabricate events. The captures are [login](./img/login.png), [the run start](./img/start-run.png), [a mid-run pulsing task](./img/mid-run.png), and [finished output](./img/finished-output.png).

To verify the authenticated localhost flow from a shell, set `CREWGRAPH_USERNAME=acme` and `CREWGRAPH_PASSWORD=acme-demo-2026!`, then run `python -m scripts.check_dashboard_flow`. With `AUTH_ENABLED=false`, the script works without login credentials. For persistence, run the flow, use `docker compose down` (not `down -v`), then `docker compose up -d` and check that the same project remains listed and its generated file preview still loads from the workspace volume.
