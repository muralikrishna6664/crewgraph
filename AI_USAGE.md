# AI usage verification template

Fill in the final column with what you personally checked, changed, or independently tested.

| Component | What the AI generated | What I verified or changed |
|---|---|---|
| Schema | FalkorDB node-label and edge-type constants, project graph initialization, and ID indexes. | |
| Scheduler | DAG creation, ready-task selection, guarded task claims, completion promotion, and lease recovery queries. | |
| Planner | LLM wrapper, mock DAG, JSON validation, dependency validation, and cycle rejection. | |
| Agents | Generic runner and backend, frontend, tester, and security agent behaviors, including mock-generated app files. | |
| Debugger | Bug-context lookup, canned mock repair output, repaired artifact recording, and fix links. | |
| Security scanner | Static checks for the configured security patterns and graph-linked findings. | |
| Dashboard | FastAPI graph/event/release APIs, background demo status, and the single-file Cytoscape interface. | |
| Load tests | Multi-project mock load runner and shared-graph contention benchmark with temporary graph cleanup. | |
