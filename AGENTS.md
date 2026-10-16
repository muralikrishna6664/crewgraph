# CrewGraph: agent instructions

Hackathon project for the "Agent Memory and Coordination" track. FalkorDB must be central:
the product must stop working if FalkorDB is removed.

Stack: Python 3.11, FastAPI, FalkorDB (Docker, localhost:6379), falkordb Python client,
plain HTML + Cytoscape.js dashboard.

Concept: AI agents (planner, backend, frontend, tester, security, debugger, reviewer) build a
small web app together. They NEVER call each other. All coordination happens through the graph.
One graph per project (db.select_graph(project_id)) for tenant isolation.

Graph model:
Nodes: Project, Task{id,title,status,skill,claimed_by,lease_until,tokens,cost,ts}, Agent, Skill,
Artifact{id,path,kind,ts}, Bug, Vulnerability{type,severity,status}, Episode, Lesson, Approval, Review
Edges: DEPENDS_ON, PART_OF, NEEDS, HAS_SKILL, PRODUCED_BY, FOR_TASK, HANDED_OFF_TO{reason,ts},
FOUND_IN, FIXED_BY, BLOCKS, APPROVES, REVIEWS, DERIVED_FROM

Rules:
- Show a short plan first and wait for my OK. One task at a time.
- Every Cypher query lives in app/queries.py as a named function with a plain-English docstring.
- Use ro_query for reads and query for writes. Make setup and seed code idempotent (MERGE).
- Only use Cypher features FalkorDB supports. Tell me if unsure.
- Integration tests run against the real localhost FalkorDB using temporary graphs deleted afterwards.
- Synthetic data only. The security agent may only target the localhost sandbox.
- Keep code simple, with short comments. I must be able to explain every line.
- Never run destructive commands or touch files outside this repo.
