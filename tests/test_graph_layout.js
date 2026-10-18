const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildLaneGraph,
  buildSimpleGraph
} = require("../app/static/graph-layout.js");

test("simple view has unique symmetric positions and equally spaced columns", () => {
  const nodes = [
    { id: "project", label: "Project", properties: { name: "sample" } },
    { id: "prompt", label: "Prompt", properties: {} },
    { id: "api", label: "Task", properties: { title: "Build API", skill: "backend", status: "claimed", claimed_by: "backend" } },
    { id: "web", label: "Task", properties: { title: "Build page", skill: "frontend", status: "ready" } },
    { id: "test", label: "Task", properties: { title: "Test app", skill: "tester", status: "pending" } },
    { id: "scan", label: "Task", properties: { title: "Security scan", skill: "security", status: "pending" } },
    { id: "release", label: "Task", properties: { title: "Release project", skill: "release", status: "pending" } },
    { id: "api-agent", label: "Agent", properties: { name: "backend" } },
    { id: "api-file", label: "Artifact", properties: { path: "main.py" } },
    { id: "bug", label: "Bug", properties: { title: "Open issue", status: "open" } },
    { id: "approval", label: "Approval", properties: { status: "pending" } },
    { id: "output", label: "Output", properties: { status: "pending" } }
  ];
  const graph = buildSimpleGraph(nodes, new Map(), 812);
  const points = graph.nodes.map(node => `${node.position.x},${node.position.y}`);
  assert.equal(new Set(points).size, points.length);
  assert.equal(graph.nodes.some(node => ["Agent", "Artifact", "Event"].includes(node.label)), false);
  assert.equal(graph.nodes.some(node => node.id === "project"), false);
  assert.equal(graph.nodes.some(node => node.id === "simple:plan" && node.title === "Plan"), true);
  assert.equal(graph.nodes.find(node => node.id === "simple:backend").agentName, "backend");

  const byId = new Map(graph.nodes.map(node => [node.id, node]));
  assert.equal(byId.get("simple:backend").position.x, byId.get("simple:frontend").position.x);
  assert.equal(byId.get("simple:backend").position.y, -byId.get("simple:frontend").position.y);
  const spine = [
    "simple:prompt", "simple:plan", "simple:backend", "simple:test",
    "simple:scan", "simple:approve", "simple:release", "simple:output"
  ].map(id => byId.get(id).position.x);
  const gaps = spine.slice(1).map((x, index) => x - spine[index]);
  assert.ok(gaps.every(gap => Math.abs(gap - gaps[0]) < 1e-9));
  assert.equal(byId.get("simple:bug").position.y - byId.get("simple:test").position.y, 110);
  assert.equal(byId.get("simple:bug").title, "Bug");
  assert.ok(graph.edges.every(edge => edge.data.type === "SIMPLE_SPINE"));

  nodes.find(node => node.label === "Bug").properties.status = "fixed";
  const fixed = buildSimpleGraph(nodes, new Map(), 812);
  assert.equal(fixed.nodes.find(node => node.id === "simple:bug").title, "Fixed");
  assert.equal(fixed.nodes.find(node => node.id === "simple:bug").simpleStatus, "done");
});

test("detailed view retains its task, agent, artifact, and bug lanes", () => {
  const nodes = [
    { id: "project", label: "Project", properties: { id: "project" } },
    { id: "prompt", label: "Prompt", properties: {} },
    { id: "api", label: "Task", properties: { title: "API", claimed_by: "backend" } },
    { id: "tests", label: "Task", properties: { title: "Tests" } },
    { id: "backend", label: "Agent", properties: { name: "backend" } },
    { id: "file", label: "Artifact", properties: { path: "main.py" } },
    { id: "bug", label: "Bug", properties: { title: "Open bug", status: "open" } },
    { id: "output", label: "Output", properties: {} }
  ];
  const edges = [
    { source: "api", target: "project", type: "PART_OF" },
    { source: "tests", target: "project", type: "PART_OF" },
    { source: "tests", target: "api", type: "DEPENDS_ON" },
    { source: "file", target: "api", type: "FOR_TASK" },
    { source: "file", target: "backend", type: "PRODUCED_BY" },
    { source: "bug", target: "file", type: "FOUND_IN" }
  ];
  const graph = buildLaneGraph(nodes, edges, new Map());
  const byId = new Map(graph.nodes.map(node => [node.id, node]));

  assert.equal(byId.has("project"), false);
  assert.equal(graph.edges.some(edge => edge.data.type === "PART_OF"), false);
  assert.equal(byId.get("agent-lane:api").position.x, byId.get("api").position.x);
  assert.equal(byId.get("agent-lane:api").position.y, byId.get("api").position.y - 170);
  assert.equal(byId.get("file").position.y, byId.get("api").position.y + 170);
  assert.equal(byId.get("bug").position.y, byId.get("file").position.y);
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
