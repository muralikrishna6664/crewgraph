const assert = require("node:assert/strict");
const test = require("node:test");

const { buildLaneGraph } = require("../app/static/graph-layout.js");

test("lane layout uses unique positions, equal columns, and task-aligned agents", () => {
  const nodes = [
    { id: "project", label: "Project", properties: { name: "sample" } },
    { id: "prompt", label: "Prompt", properties: {} },
    { id: "api", label: "Task", properties: { title: "API", claimed_by: "backend" } },
    { id: "web", label: "Task", properties: { title: "Web", claimed_by: "frontend" } },
    { id: "test", label: "Task", properties: { title: "Tests", claimed_by: "tester" } },
    { id: "release", label: "Task", properties: { title: "Release" } },
    { id: "backend", label: "Agent", properties: { name: "backend" } },
    { id: "frontend", label: "Agent", properties: { name: "frontend" } },
    { id: "tester", label: "Agent", properties: { name: "tester" } },
    { id: "api-v1", label: "Artifact", properties: { path: "api.py", version: 1 } },
    { id: "api-v2", label: "Artifact", properties: { path: "api.py", version: 2 } },
    { id: "api-v3", label: "Artifact", properties: { path: "api.py", version: 3 } },
    { id: "api-v4", label: "Artifact", properties: { path: "api.py", version: 4 } },
    { id: "bug", label: "Bug", properties: { title: "Open bug", status: "open" } },
    { id: "approval", label: "Approval", properties: { status: "pending" } },
    { id: "output", label: "Output", properties: {} }
  ];
  const edges = [
    { source: "project", target: "api", type: "PART_OF" },
    { source: "project", target: "web", type: "PART_OF" },
    { source: "project", target: "test", type: "PART_OF" },
    { source: "project", target: "release", type: "PART_OF" },
    { source: "test", target: "api", type: "DEPENDS_ON" },
    { source: "test", target: "web", type: "DEPENDS_ON" },
    { source: "release", target: "test", type: "DEPENDS_ON" },
    { source: "api-v1", target: "api", type: "FOR_TASK" },
    { source: "api-v2", target: "api", type: "FOR_TASK" },
    { source: "api-v3", target: "api", type: "FOR_TASK" },
    { source: "api-v4", target: "api", type: "FOR_TASK" },
    { source: "api-v1", target: "backend", type: "PRODUCED_BY" },
    { source: "api-v2", target: "debugger", type: "PRODUCED_BY" },
    { source: "api-v3", target: "backend", type: "PRODUCED_BY" },
    { source: "api-v4", target: "debugger", type: "PRODUCED_BY" },
    { source: "bug", target: "api-v1", type: "FOUND_IN" }
  ];
  nodes.push({ id: "debugger", label: "Agent", properties: { name: "debugger" } });

  const graph = buildLaneGraph(nodes, edges, new Map());
  const points = graph.nodes.map(node => `${node.position.x},${node.position.y}`);
  assert.equal(new Set(points).size, points.length);
  assert.equal(graph.nodes.some(node => node.id === "project"), false);
  assert.equal(graph.edges.some(edge => edge.data.type === "PART_OF"), false);

  const byId = new Map(graph.nodes.map(node => [node.id, node]));
  assert.equal(byId.get("api").position.x, byId.get("web").position.x);
  assert.equal(byId.get("test").position.x - byId.get("api").position.x, 190);
  assert.equal(byId.get("release").position.x - byId.get("test").position.x, 190);
  assert.equal(byId.get("agent-lane:api").position.x, byId.get("api").position.x);
  assert.deepEqual(byId.get("agent-lane:api").properties.agents, ["backend", "debugger"]);
  assert.equal(byId.get("artifact-more:api").title, "+1 more");
  assert.equal(graph.nodes.filter(node => node.label === "Agent").length, 3);
});

test("cached positions remain fixed when new graph nodes arrive", () => {
  const cache = new Map();
  const initial = buildLaneGraph([
    { id: "prompt", label: "Prompt" },
    { id: "task", label: "Task", properties: { title: "Build" } },
    { id: "output", label: "Output" }
  ], [], cache);
  const taskPosition = { ...initial.positions.get("task") };
  const updated = buildLaneGraph([
    { id: "prompt", label: "Prompt" },
    { id: "task", label: "Task", properties: { title: "Build" } },
    { id: "next", label: "Task", properties: { title: "Next" } },
    { id: "output", label: "Output" }
  ], [{ source: "next", target: "task", type: "DEPENDS_ON" }], cache);

  assert.deepEqual(updated.positions.get("task"), taskPosition);
  assert.notDeepEqual(updated.positions.get("next"), taskPosition);
  assert.equal(updated.positions.get("next").x - taskPosition.x, 190);
});
