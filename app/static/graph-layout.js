(function (root) {
  "use strict";

  const COLUMN_GAP = 190;
  const TASK_ROW_GAP = 76;
  const ARTIFACT_GAP = 90;
  const HIDDEN_EDGE_TYPES = new Set([
    "PART_OF", "FOR_TASK", "PRODUCED_BY", "FOUND_IN"
  ]);

  function properties(node) {
    return node.properties || node;
  }

  function labelFor(node) {
    const values = properties(node);
    if (node.label === "Task") return values.title || "Task";
    if (node.label === "Artifact") return values.path || "Artifact";
    if (node.label === "Agent") return values.name || "Agent";
    if (node.label === "Bug") return values.title || "Bug";
    if (node.label === "Prompt") return "Prompt";
    if (node.label === "Output") return "Output";
    if (node.label === "Approval") return `Approval (${values.status || "pending"})`;
    return node.label || node.id;
  }

  function makeEdge(source, target, type) {
    return {
      data: {
        id: `${source}:${type}:${target}`,
        source,
        target,
        type
      }
    };
  }

  function buildLaneGraph(rawNodes, rawEdges, positionCache) {
    const project = rawNodes.find(node => node.label === "Project");
    const projectId = project ? properties(project).id : "project";
    const nodesById = new Map(
      rawNodes.filter(node => node.label !== "Project").map(node => [node.id, node])
    );
    const tasks = [...nodesById.values()]
      .filter(node => node.label === "Task")
      .sort((left, right) => left.id.localeCompare(right.id));
    const taskIds = new Set(tasks.map(task => task.id));
    const requirements = new Map(tasks.map(task => [task.id, []]));

    for (const edge of rawEdges) {
      if (edge.type === "DEPENDS_ON" && taskIds.has(edge.source) && taskIds.has(edge.target)) {
        requirements.get(edge.source).push(edge.target);
      }
    }

    const columns = new Map();
    const levels = new Map();
    function taskLevel(id, visiting) {
      if (levels.has(id)) return levels.get(id);
      if (visiting.has(id)) return 0;
      const next = new Set(visiting);
      next.add(id);
      const dependencies = requirements.get(id) || [];
      const level = dependencies.length
        ? 1 + Math.max(...dependencies.map(dependency => taskLevel(dependency, next)))
        : 0;
      levels.set(id, level);
      return level;
    }

    for (const task of tasks) {
      const level = taskLevel(task.id, new Set());
      if (!columns.has(level)) columns.set(level, []);
      columns.get(level).push(task);
    }

    const desired = new Map();
    const displayNodes = new Map();
    function addNode(node) {
      if (displayNodes.has(node.id)) return;
      displayNodes.set(node.id, node);
    }

    const prompt = [...nodesById.values()].find(node => node.label === "Prompt");
    const output = [...nodesById.values()].find(node => node.label === "Output");
    const existingApproval = [...nodesById.values()].find(node => node.label === "Approval");
    const approval = existingApproval || (project || prompt || output || tasks.length
      ? {
        id: `${projectId}:approval`,
        label: "Approval",
        status: "pending",
        properties: { status: "pending" }
      }
      : null);
    if (prompt) {
      addNode({ ...prompt, title: labelFor(prompt) });
      desired.set(prompt.id, { x: 0, y: 0 });
    }
    if (output) {
      addNode({ ...output, title: labelFor(output) });
    }
    if (approval) addNode({ ...approval, title: labelFor(approval) });

    const maxLevel = Math.max(0, ...levels.values());
    const taskStartX = 0;
    const approvalX = (maxLevel + 1) * COLUMN_GAP;
    if (prompt) desired.set(prompt.id, { x: -COLUMN_GAP, y: 0 });
    if (output) desired.set(output.id, { x: approvalX + COLUMN_GAP, y: 0 });
    if (approval) desired.set(approval.id, { x: approvalX, y: 0 });

    const taskY = new Map();
    for (const [level, items] of columns) {
      items.forEach((task, index) => {
        const y = (index - (items.length - 1) / 2) * TASK_ROW_GAP;
        taskY.set(task.id, y);
        desired.set(task.id, { x: taskStartX + level * COLUMN_GAP, y });
        addNode({ ...task, title: labelFor(task) });
      });
    }

    const artifactTask = new Map();
    for (const edge of rawEdges) {
      if (edge.type === "FOR_TASK" && nodesById.get(edge.source)?.label === "Artifact"
        && taskIds.has(edge.target)) {
        artifactTask.set(edge.source, edge.target);
      }
    }

    const artifactIdsByTask = new Map(tasks.map(task => [task.id, []]));
    for (const [artifactId, taskId] of artifactTask) {
      artifactIdsByTask.get(taskId).push(artifactId);
    }

    const agentNamesByTask = new Map(tasks.map(task => [
      task.id,
      new Set(properties(task).claimed_by ? [properties(task).claimed_by] : [])
    ]));
    for (const edge of rawEdges) {
      if (edge.type !== "PRODUCED_BY") continue;
      const taskId = artifactTask.get(edge.source);
      const agent = nodesById.get(edge.target);
      if (taskId && agent?.label === "Agent") {
        agentNamesByTask.get(taskId).add(properties(agent).name || agent.id);
      }
    }

    const laneAgentId = new Map();
    for (const task of tasks) {
      const names = [...agentNamesByTask.get(task.id)].sort();
      if (!names.length) continue;
      const id = `agent-lane:${task.id}`;
      laneAgentId.set(task.id, id);
      addNode({
        id,
        label: "Agent",
        title: names.join(" + "),
        properties: { name: names.join(" + "), agents: names, task_id: task.id }
      });
      desired.set(id, {
        x: taskStartX + levels.get(task.id) * COLUMN_GAP,
        y: (taskY.get(task.id) || 0) - 170
      });
    }

    for (const [taskId, artifactIds] of artifactIdsByTask) {
      artifactIds.sort((left, right) => {
        const a = properties(nodesById.get(left));
        const b = properties(nodesById.get(right));
        return (Number(a.version) || 0) - (Number(b.version) || 0)
          || String(a.ts || "").localeCompare(String(b.ts || ""))
          || left.localeCompare(right);
      });
      const taskPositionY = taskY.get(taskId) || 0;
      const visibleIds = artifactIds.slice(0, 3);
      visibleIds.forEach((id, index) => {
        const artifact = nodesById.get(id);
        addNode({ ...artifact, title: labelFor(artifact) });
        desired.set(id, {
          x: taskStartX + levels.get(taskId) * COLUMN_GAP,
          y: taskPositionY + 170 + index * ARTIFACT_GAP
        });
      });
      const hiddenCount = artifactIds.length - visibleIds.length;
      if (hiddenCount > 0) {
        const id = `artifact-more:${taskId}`;
        addNode({
          id,
          label: "Artifact",
          title: `+${hiddenCount} more`,
          properties: { task_id: taskId, hidden_count: hiddenCount }
        });
        desired.set(id, {
          x: taskStartX + levels.get(taskId) * COLUMN_GAP,
          y: taskPositionY + 170 + visibleIds.length * ARTIFACT_GAP
        });
      }
    }

    const bugsByArtifact = new Map();
    for (const edge of rawEdges) {
      if (edge.type !== "FOUND_IN") continue;
      const bug = nodesById.get(edge.source);
      if (bug?.label !== "Bug" || !displayNodes.has(edge.target)) continue;
      if (!bugsByArtifact.has(edge.target)) bugsByArtifact.set(edge.target, []);
      bugsByArtifact.get(edge.target).push(bug);
    }
    for (const [artifactId, bugs] of bugsByArtifact) {
      const artifactPosition = desired.get(artifactId);
      bugs.sort((left, right) => left.id.localeCompare(right.id));
      bugs.forEach((bug, index) => {
        addNode({ ...bug, title: labelFor(bug) });
        desired.set(bug.id, {
          x: artifactPosition.x + 70 + index * 58,
          y: artifactPosition.y
        });
      });
    }

    let extraIndex = 0;
    for (const node of nodesById.values()) {
      if (displayNodes.has(node.id) || node.label === "Agent") continue;
      addNode({ ...node, title: labelFor(node) });
      desired.set(node.id, {
        x: taskStartX + extraIndex * 70,
        y: -270
      });
      extraIndex += 1;
    }

    const roots = tasks.filter(task => (requirements.get(task.id) || []).length === 0);
    const dependedOn = new Set([...requirements.values()].flat());
    const leaves = tasks.filter(task => !dependedOn.has(task.id));
    const visualEdges = [];
    function connect(source, target, type) {
      if (displayNodes.has(source) && displayNodes.has(target)) {
        visualEdges.push(makeEdge(source, target, type));
      }
    }

    for (const edge of rawEdges) {
      if (edge.type === "DEPENDS_ON") {
        connect(edge.target, edge.source, "DEPENDS_ON");
      } else if (edge.type === "FOR_TASK") {
        const taskId = artifactTask.get(edge.source);
        if (taskId && displayNodes.has(edge.source)) connect(taskId, edge.source, "FOR_TASK");
      } else if (edge.type === "FOUND_IN") {
        connect(edge.target, edge.source, "FOUND_IN");
      } else if (!HIDDEN_EDGE_TYPES.has(edge.type)) {
        connect(edge.source, edge.target, edge.type);
      }
    }
    for (const [taskId, artifactIds] of artifactIdsByTask) {
      if (artifactIds.length > 3) {
        connect(taskId, `artifact-more:${taskId}`, "FOR_TASK");
      }
    }
    for (const task of tasks) {
      const agentId = laneAgentId.get(task.id);
      if (agentId) connect(agentId, task.id, "AGENT_TASK");
    }
    if (prompt) {
      for (const task of roots) connect(prompt.id, task.id, "SPINE");
      if (!tasks.length && output) connect(prompt.id, output.id, "SPINE");
    }
    if (approval) {
      for (const task of leaves) connect(task.id, approval.id, "SPINE");
      if (output) connect(approval.id, output.id, "SPINE");
    }

    const positions = positionCache || new Map();
    const occupied = new Map();
    for (const [id, point] of positions) {
      occupied.set(`${point.x},${point.y}`, id);
    }
    for (const [id, point] of desired) {
      if (positions.has(id)) continue;
      let candidate = { ...point };
      let key = `${candidate.x},${candidate.y}`;
      while (occupied.has(key)) {
        console.warn(`Graph layout collision for ${id}; nudging from ${key}`);
        candidate = { x: candidate.x, y: candidate.y + 52 };
        key = `${candidate.x},${candidate.y}`;
      }
      positions.set(id, candidate);
      occupied.set(key, id);
    }

    return {
      nodes: [...displayNodes.values()].map(node => ({
        ...node,
        position: positions.get(node.id) || { x: 0, y: 0 }
      })),
      edges: visualEdges,
      positions
    };
  }

  const api = { buildLaneGraph };
  if (root) root.CrewGraphLayout = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window === "undefined" ? null : window);
