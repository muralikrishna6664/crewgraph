# Three-minute CrewGraph demo script

## Before recording

1. Start the local stack with `docker compose up -d --build`.
2. Open `http://localhost:8000` in a browser and wait for the dashboard controls to appear.
3. Use the mock provider. No external LLM key is needed; the demo only uses synthetic data and localhost services.

## Timed narration and clicks

| Time | Exact action | Say |
|---|---|---|
| 0:00–0:20 | Point to the CrewGraph title, **Project** picker, graph, **Selected node**, and **Recent events** panels. | “CrewGraph demonstrates the Agent Memory and Coordination track. The graph is the shared project state: agents do not call one another directly.” |
| 0:20–0:35 | Click **Run demo with flaw** once. Wait for the newest project to appear selected in the **Project** picker. | “I’m starting the synthetic to-do app with one deliberate backend defect. The plan and generated files are canned in mock mode, so this needs no model key.” |
| 0:35–1:15 | Watch the graph and **Recent events** update. Point to the open red **Bug**, the debugger’s new amber **Artifact**, and the tester/security tasks as they run. | “The planner stores a dependency DAG in FalkorDB. The backend produces an API contract and code; the tester uses real HTTP requests against localhost. The empty-title response violates the contract, so the tester records a bug linked to its source artifact. The debugger writes a repaired artifact, and the security scan runs before release.” |
| 1:15–1:35 | Click the now-green fixed **Bug** node, then click its amber repair **Artifact** node. Read a couple of key/value rows in **Selected node**. | “The bug stays connected to the artifact that exposed it, and the repair is a separate artifact linked as its fix. These are graph facts, not a status invented by the dashboard.” |
| 1:35–1:55 | Point to the status-colored task chain and the release banner showing **Human approval is required**. | “The tester and security checks have passed, the bug is fixed, and every non-release task is done. The release gate is still blocked until a person approves.” |
| 1:55–2:10 | Click **Approve** once. | “Approval is stored in the project graph. The orchestrator rechecks the gate before it creates and completes the release task.” |
| 2:10–2:40 | Wait for the banner to show **Released.** and the release task to appear done; point to the persisted events. | “Now the release task is complete. The event feed records what happened, while the graph shows dependencies, artifacts, bugs, agents, and approval together.” |
| 2:40–3:00 | Point to the selected project name and graph. Do not start another demo. | “Each project uses its own FalkorDB graph. The demo’s orchestration, atomic claims, HTTP checks, static scanner, and release gate are real; mock planning and generated file contents are intentionally canned.” |

If the graph is still updating, wait for the next dashboard poll before clicking the bug or approval controls. Stop the local stack after recording with `docker compose down`.
