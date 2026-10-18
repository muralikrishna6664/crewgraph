    const TIMINGS = {
      nodeAppearMs: 700,
      edgeDrawMs: 900,
      particleTravelMs: 1600,
      pulsePeriodMs: 2200,
      cameraMs: 800,
      minStepGapMs: 900,
      nodePulseInMs: 480,
      edgeStaggerMs: 24,
      bugShakeStepMs: 100,
      fixedBugFlashMs: 700
    };
    const picker = document.getElementById("project-picker");
    const banner = document.getElementById("release-banner");
    const message = document.getElementById("message");
    const promptInput = document.getElementById("build-prompt");
    const speedControl = document.getElementById("speed-control");
    const colors = {
      Project: "#b98aff", Prompt: "#b98aff", Output: "#b98aff",
      Agent: "#5b9dff", Artifact: "#4de3ef", Vulnerability: "#ff527f",
      Approval: "#b98aff"
    };
    const stageNames = ["Planner", "Backend / Frontend", "Tester", "Debugger", "Security", "Approval", "Release"];
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let positionCache = new Map();
    let selectedNodeId = null;
    let hoveredNodeId = null;
    let activeRunId = null;
    let projectsRefreshVersion = 0;
    let activeRunStartedAt = 0;
    let consecutiveRefreshFailures = 0;
    let knownEventIds = new Set();
    let eventProjectId = null;
    let selectedArtifactId = null;
    let manualPreviewSelection = false;
    let previewProjectId = null;
    let replayActive = false;
    let visualEventQueue = [];
    let visualEventTimer = null;
    let lastVisualStepAt = 0;
    let particleSequence = 0;

    function playbackMultiplier(replay = false) {
      return Number(speedControl.value) * (replay ? 2 : 1);
    }

    function initializeStages() {
      const strip = document.getElementById("stage-strip");
      stageNames.forEach((name, index) => {
        const step = document.createElement("div");
        step.className = "stage-step";
        step.dataset.stage = String(index);
        step.style.setProperty(
          "--pulse-period",
          `${TIMINGS.pulsePeriodMs / playbackMultiplier()}ms`
        );
        const label = document.createElement("span");
        label.className = "stage-label";
        label.textContent = name;
        step.append(label);
        strip.append(step);
        if (index < stageNames.length - 1) {
          const link = document.createElement("span");
          link.className = "stage-link";
          link.dataset.link = String(index);
          strip.append(link);
        }
      });
    }

    function updateStages(nodes, events, release) {
      const tasks = nodes.filter(node => node.label === "Task");
      const tasksFor = skill => tasks.filter(node => node.properties.skill === skill);
      const allDone = skill => {
        const matching = tasksFor(skill);
        return matching.length > 0 && matching.every(task => task.status === "done");
      };
      const testerDone = allDone("tester");
      const securityDone = allDone("security");
      const bugEvents = events.filter(event => event.type === "bug found");
      const bugs = nodes.filter(node => node.label === "Bug");
      const debuggerDone = bugEvents.length
        ? bugs.length > 0 && bugs.every(bug => bug.status === "fixed")
        : testerDone;
      const approved = nodes.some(
        node => node.label === "Approval" && node.status === "approved"
      );
      const completed = [
        tasks.length > 0,
        ["backend", "frontend"].some(skill => tasksFor(skill).length > 0)
          && ["backend", "frontend"].filter(skill => tasksFor(skill).length > 0).every(allDone),
        testerDone,
        debuggerDone,
        securityDone,
        approved,
        Boolean(release.released)
      ];
      const activeIndex = completed.findIndex(done => !done);
      document.querySelectorAll(".stage-step").forEach((step, index) => {
        step.classList.toggle("complete", completed[index]);
        step.classList.toggle("active", index === activeIndex);
      });
    }

    function animateStageTravel(stageIndex, replay = false) {
      if (stageIndex === null || stageIndex <= 0) return;
      const link = document.querySelector(`.stage-link[data-link="${stageIndex - 1}"]`);
      if (!link) return;
      const dot = document.createElement("i");
      dot.className = "travel-dot";
      dot.style.animationDuration =
        `${TIMINGS.particleTravelMs / playbackMultiplier(replay)}ms`;
      link.append(dot);
      dot.addEventListener("animationend", () => dot.remove(), { once: true });
    }

    function stageForEvent(event, tasksById) {
      if (event.type === "bug found" || event.type === "bug fixed") return 3;
      const task = tasksById.get(event.task_id);
      const skill = task && task.properties ? task.properties.skill : "";
      if (skill === "backend" || skill === "frontend") return 1;
      if (skill === "tester") return 2;
      if (skill === "debugger" || String(event.detail || "").startsWith("debugger")) return 3;
      if (skill === "security") return 4;
      if (skill === "release") return 6;
      return null;
    }

    async function showArtifactPreview(projectId, artifact) {
      selectedArtifactId = artifact.id;
      const preview = document.getElementById("artifact-preview");
      document.getElementById("preview-path").textContent = artifact.path;
      preview.textContent = "Loading preview…";
      try {
        const file = await request(
          `/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifact.id)}`
        );
        preview.textContent = file.content;
      } catch (error) {
        preview.textContent = `Preview unavailable: ${error.message}`;
      }
    }

    function renderOutput(projectId, artifacts, release, run) {
      const list = document.getElementById("artifact-list");
      list.replaceChildren();
      const status = document.getElementById("output-status");
      status.textContent = release.released
        ? "Released"
        : release.can_release ? "Awaiting approval"
        : run && run.status === "failed" ? "Run failed"
          : run && run.status === "finished" ? "Awaiting approval" : "Building";
      for (const artifact of artifacts) {
        const button = document.createElement("button");
        button.className = "artifact-entry";
        const agents = Array.isArray(artifact.agents) ? artifact.agents.join(", ") : "";
        button.textContent = `${artifact.path} · v${artifact.version}${agents ? ` · ${agents}` : ""}`;
        button.addEventListener("click", () => {
          manualPreviewSelection = true;
          showArtifactPreview(projectId, artifact);
        });
        list.append(button);
      }
      const selectedStillExists = artifacts.some(item => item.id === selectedArtifactId);
      if (!selectedStillExists) selectedArtifactId = null;
      const completed = release.released || (run && run.status === "finished");
      if (!manualPreviewSelection && completed) {
        const preferred = ["main.py", "dashboard/index.html"].map(path =>
          artifacts.filter(item => item.path === path)
            .sort((left, right) => right.version - left.version)[0]
        ).find(Boolean);
        if (preferred && preferred.id !== selectedArtifactId) {
          showArtifactPreview(projectId, preferred);
        } else if (!preferred && !selectedArtifactId && artifacts.length) {
          showArtifactPreview(projectId, artifacts[artifacts.length - 1]);
        }
      }
      if (!selectedArtifactId) {
        document.getElementById("preview-path").textContent = "No file selected";
        document.getElementById("artifact-preview").textContent =
          "Generated files will appear here as agents record artifacts.";
      }
    }

    function findEventEdge(event) {
      if (event.type === "task claimed") {
        return cy.edges().filter(edge =>
          edge.data("type") === "AGENT_TASK" && edge.data("target") === event.task_id
        ).first();
      }
      if (event.type === "artifact created") {
        return cy.edges().filter(edge =>
          edge.data("type") === "FOR_TASK"
          && edge.data("source") === event.task_id
          && edge.data("target") === event.artifact_id
        ).first();
      }
      if (event.type === "bug found" || event.type === "bug fixed") {
        return cy.edges().filter(edge =>
          (event.type === "bug found"
            ? edge.data("type") === "FOUND_IN"
            : ["FIXES", "FIXED_BY"].includes(edge.data("type")))
          && (edge.data("target") === event.bug_id || edge.data("source") === event.bug_id)
        ).first();
      }
      if (event.type === "task done") {
        return cy.edges().filter(edge =>
          edge.data("source") === event.task_id
          && ["DEPENDS_ON", "SPINE"].includes(edge.data("type"))
        ).first();
      }
      return cy.collection();
    }

    function animateEventEdge(event, replay = false) {
      if (reducedMotion) return;
      const edge = findEventEdge(event);
      if (!edge || !edge.length) return;
      const source = edge.source().position();
      const target = edge.target().position();
      const particle = cy.add({
        data: { id: `event-particle-${++particleSequence}` },
        position: source,
        classes: "particle"
      });
      particle.animate({ position: target }, {
        duration: TIMINGS.particleTravelMs / playbackMultiplier(replay),
        complete: () => particle.remove()
      });
    }

    function applyVisualEvent(item) {
      document.getElementById("latest-event").textContent =
        describeEvent(item.event, item.tasksById);
      animateStageTravel(stageForEvent(item.event, item.tasksById), item.replay);
      if (item.event.type === "bug found") {
        animateFoundBug(item.event.bug_id, item.replay);
      }
      if (item.event.type === "bug fixed") {
        animateFixedBug(item.event.bug_id, item.replay);
      }
      animateEventEdge(item.event, item.replay);
      const targetId = item.event.task_id || item.event.artifact_id || item.event.bug_id;
      const node = targetId && cy.$id(targetId);
      if (node && node.length && !reducedMotion) {
        node.animate({ style: { "underlay-padding": 16, "underlay-opacity": 0.95 } }, {
          duration: TIMINGS.nodePulseInMs / playbackMultiplier(item.replay),
          complete: () => node.animate({
            style: { "underlay-padding": 9, "underlay-opacity": 0.34 }
          }, { duration: TIMINGS.nodePulseInMs / playbackMultiplier(item.replay) })
        });
      }
    }

    function scheduleVisualEvent() {
      if (visualEventTimer !== null || !visualEventQueue.length) {
        if (!visualEventQueue.length && replayActive) {
          replayActive = false;
          document.getElementById("replay-events").disabled = false;
        }
        return;
      }
      const next = visualEventQueue[0];
      const multiplier = playbackMultiplier(next.replay);
      const gap = next.gapMs === undefined
        ? TIMINGS.minStepGapMs
        : Math.max(TIMINGS.minStepGapMs, next.gapMs);
      const wait = lastVisualStepAt
        ? Math.max(0, lastVisualStepAt + gap / multiplier - Date.now())
        : 0;
      visualEventTimer = window.setTimeout(() => {
        visualEventTimer = null;
        const item = visualEventQueue.shift();
        if (item) {
          applyVisualEvent(item);
          lastVisualStepAt = Date.now();
        }
        scheduleVisualEvent();
      }, wait);
    }

    function enqueueVisualEvent(event, tasksById, replay = false, gapMs) {
      visualEventQueue.push({ event, tasksById, replay, gapMs });
      scheduleVisualEvent();
    }

    function stopReplay() {
      if (visualEventTimer !== null) window.clearTimeout(visualEventTimer);
      visualEventTimer = null;
      visualEventQueue = [];
      replayActive = false;
      document.getElementById("replay-events").disabled = false;
    }

    function replayEvents(events, tasksById) {
      stopReplay();
      if (!events.length) {
        document.getElementById("replay-events").disabled = true;
        return;
      }
      replayActive = true;
      document.getElementById("replay-events").disabled = true;
      let previousTimestamp = null;
      for (const event of events) {
        const timestamp = Number(event.ts);
        let gapMs;
        if (Number.isFinite(timestamp) && previousTimestamp !== null) {
          gapMs = Math.max(0, timestamp - previousTimestamp);
        }
        if (Number.isFinite(timestamp)) previousTimestamp = timestamp;
        visualEventQueue.push({ event, tasksById, replay: true, gapMs });
      }
      lastVisualStepAt = 0;
      scheduleVisualEvent();
    }

    initializeStages();
    request("/config").then(config => {
      document.getElementById("llm-badge").textContent = config.llm_mode;
      document.getElementById("logout").hidden = !config.auth_enabled;
    }).catch(error => {
      document.getElementById("llm-badge").textContent = `Config error: ${error.message}`;
    });
    const cy = cytoscape({
      container: document.getElementById("graph"),
      elements: [],
      layout: { name: "preset", padding: 28 },
      style: [
        {
          selector: "node",
          style: {
            "background-color": element => {
              const data = element.data();
              if (data.label === "Bug") {
                return data.status === "fixed" ? "#55e69a" : "#ff527f";
              }
              if (colors[data.label]) return colors[data.label];
              if (data.label === "Task") {
                return {
                  done: "#55e69a", ready: "#f5bd4f", claimed: "#5b9dff",
                  pending: "#758398", failed: "#ff527f"
                }[data.status] || "#758398";
              }
              return "#b98aff";
            },
            label: "data(title)",
            color: "#102033", "text-valign": "bottom", "text-halign": "center",
            "text-wrap": "wrap", "text-max-width": 120, "font-size": 12,
            "font-family": "Cascadia Code, Consolas, monospace",
            "text-margin-y": 7,
            width: 40, height: 40, "border-width": 1, "border-color": "#c7d4e6",
            "underlay-color": element => {
              const data = element.data();
              if (data.label === "Bug") return data.status === "fixed" ? "#55e69a" : "#ff527f";
              if (data.label === "Task") {
                return {done: "#55e69a", ready: "#f5bd4f", claimed: "#5b9dff"}[data.status] || "#758398";
              }
              return colors[data.label] || "#b98aff";
            },
            "underlay-padding": 9, "underlay-opacity": 0.34,
            "transition-property": "opacity, width, height, underlay-padding",
            "transition-duration": `${TIMINGS.nodeAppearMs}ms`
          }
        },
        {
          selector: "node.entering",
          style: { opacity: 0, width: 20, height: 20 }
        },
        {
          selector: "node.working",
          style: { "border-width": 3, "border-color": "#9bc3ff", "underlay-padding": 14, "underlay-opacity": 0.85 }
        },
        {
          selector: "node.shaking",
          style: { "border-color": "#fff0a8", "underlay-color": "#ff527f", "underlay-padding": 16, "underlay-opacity": 1 }
        },
        {
          selector: "node.fixed-flash",
          style: { "underlay-color": "#55e69a", "underlay-padding": 18, "underlay-opacity": 1 }
        },
        {
          selector: "node.particle",
          style: {
            width: 8, height: 8, label: "", "background-color": "#087d8a",
            "border-width": 0, "underlay-color": "#4de3ef",
            "underlay-padding": 8, "underlay-opacity": 0.9,
            "z-index": 1000
          }
        },
        {
          selector: "edge",
          style: {
            width: 1.5, "line-color": "#9eacbd", "target-arrow-color": "#70829a",
            "target-arrow-shape": "triangle", "curve-style": "bezier",
            label: "", "font-size": 9, color: "#526277",
            "text-background-color": "#fff", "text-background-opacity": 0.9,
            opacity: 0.88, "transition-property": "opacity",
            "transition-duration": `${TIMINGS.edgeDrawMs}ms`
          }
        },
        {
          selector: 'edge[type = "SPINE"], edge[type = "DEPENDS_ON"], edge[type = "AGENT_TASK"], edge[type = "FOR_TASK"], edge[type = "FOUND_IN"]',
          style: { "curve-style": "straight" }
        },
        {
          selector: "edge.drawing",
          style: { opacity: 0 }
        },
        {
          selector: "edge.edge-visible",
          style: { label: "data(type)", "line-color": "#7450bd", "target-arrow-color": "#7450bd" }
        },
        {
          selector: "node:selected",
          style: { "border-color": "#ffffff", "border-width": 3 }
        },
        {
          selector: "edge.edge-visible",
          style: { label: "data(type)" }
        }
      ]
    });

    window.addEventListener("resize", () => {
      cy.resize();
      if (cy.elements().length) cy.fit(cy.elements(), 40);
    });

    cy.on("tap", "node", event => {
      const node = event.target;
      if (selectedNodeId) cy.$id(selectedNodeId).unselect();
      node.select();
      selectedNodeId = node.id();
      showNodeDetails(node.data());
      showNodeEdges(hoveredNodeId || selectedNodeId);
    });

    cy.on("mouseover", "node", event => {
      hoveredNodeId = event.target.id();
      cy.container().title = event.target.data("fullTitle") || event.target.data("title") || "";
      showNodeEdges(hoveredNodeId);
    });

    cy.on("mouseout", "node", () => {
      hoveredNodeId = null;
      cy.container().removeAttribute("title");
      showNodeEdges(selectedNodeId);
    });

    function showNodeDetails(data) {
      const details = document.getElementById("details");
      details.replaceChildren();
      for (const [key, value] of Object.entries(data.properties || {})) {
        const name = document.createElement("dt");
        name.textContent = key;
        const content = document.createElement("dd");
        if (key === "ts" && value !== null) {
          const timestamp = typeof value === "number"
            ? value
            : Date.parse(String(value));
          if (Number.isFinite(timestamp)) {
            content.textContent = new Date(timestamp).toLocaleTimeString();
            content.title = String(value);
          } else {
            content.textContent = String(value);
          }
        } else {
          content.textContent = typeof value === "object"
            ? JSON.stringify(value, null, 2)
            : String(value);
        }
        details.append(name, content);
      }
    }

    function nodeDisplayLabel(node) {
      const properties = node.properties || {};
      switch (node.label) {
        case "Task": return properties.title || "Task";
        case "Artifact": return properties.path || "Artifact";
        case "Agent": return properties.name || "Agent";
        case "Bug": return properties.title || "Bug";
        case "Project": return properties.name || "Project";
        case "Prompt": return "Prompt";
        case "Output": return "Output";
        case "Approval": return `Approval (${properties.status || "pending"})`;
        case "Lesson": return properties.title || properties.content || "Lesson";
        case "Review":
          return properties.title
            || (properties.status ? `Review (${properties.status})` : "Review");
        default: return node.label || node.id;
      }
    }

    function showEmptyDetails() {
      const details = document.getElementById("details");
      details.replaceChildren();
      const name = document.createElement("dt");
      const content = document.createElement("dd");
      name.textContent = "Node";
      content.textContent = "Click a graph node to inspect it.";
      details.append(name, content);
    }

    function showNodeEdges(nodeId) {
      cy.edges().removeClass("edge-visible");
      if (nodeId) cy.$id(nodeId).connectedEdges().addClass("edge-visible");
    }

    function pulseWorkingNode(node) {
      if (reducedMotion || !node.hasClass("working")) return;
      const halfPeriod = TIMINGS.pulsePeriodMs / (2 * playbackMultiplier(replayActive));
      node.animate({ style: { "underlay-padding": 16 } }, {
        duration: halfPeriod,
        complete: () => {
          if (!node.hasClass("working")) return;
          node.animate({ style: { "underlay-padding": 7 } }, {
            duration: halfPeriod,
            complete: () => pulseWorkingNode(node)
          });
        }
      });
    }

    function syncWorkingNodes() {
      cy.nodes().forEach(node => {
        const isWorking = node.data("label") === "Task" && node.data("status") === "claimed";
        if (isWorking && !node.hasClass("working")) {
          node.addClass("working");
          pulseWorkingNode(node);
        } else if (!isWorking && node.hasClass("working")) {
          node.removeClass("working");
          node.stop(true, false);
        }
      });
    }

    function revealEdges(edgeIds) {
      edgeIds.forEach((id, index) => {
        const edge = cy.$id(id);
        if (reducedMotion) {
          edge.removeClass("drawing");
          return;
        }
        window.setTimeout(() => {
          if (!edge.length) return;
          edge.animate({ style: { opacity: 0.88 } }, {
            duration: TIMINGS.edgeDrawMs / playbackMultiplier(),
            complete: () => edge.removeClass("drawing")
          });
        }, index * TIMINGS.edgeStaggerMs / playbackMultiplier());
      });
    }

    function animateFoundBug(bugId, replay = false) {
      const bug = cy.$id(bugId);
      if (!bug.length) return;
      if (reducedMotion) return;
      bug.addClass("shaking");
      const origin = bug.position();
      bug.animate({ position: { x: origin.x + 5, y: origin.y } }, {
        duration: TIMINGS.bugShakeStepMs / playbackMultiplier(replay),
        complete: () => bug.animate({ position: origin }, {
          duration: TIMINGS.bugShakeStepMs / playbackMultiplier(replay),
          complete: () => bug.removeClass("shaking")
        })
      });
    }

    function animateFixedBug(bugId, replay = false) {
      const bug = cy.$id(bugId);
      if (!bug.length || reducedMotion) return;
      bug.addClass("fixed-flash");
      window.setTimeout(
        () => bug.removeClass("fixed-flash"),
        TIMINGS.fixedBugFlashMs / playbackMultiplier(replay)
      );
    }

    function describeEvent(event, tasksById) {
      const task = tasksById.get(event.task_id);
      const taskName = task ? nodeDisplayLabel(task) : event.task_id;
      if (event.type === "task claimed") {
        const agent = String(event.detail || "").replace(/^Claimed by /, "");
        return `${agent} agent claimed ${taskName}`;
      }
      if (event.type === "task done") return `${taskName} completed`;
      if (event.type === "bug found") return `Bug found: ${event.detail || event.bug_id}`;
      if (event.type === "bug fixed") return `Bug fixed: ${event.bug_id}`;
      if (event.type === "artifact created") return event.detail || "Artifact created";
      return `${event.type}${event.detail ? `: ${event.detail}` : ""}`;
    }

    async function request(path, options) {
      const response = await fetch(path, options);
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return response.json();
    }

    function reportRefreshFailure(error) {
      consecutiveRefreshFailures += 1;
      if (
        error.message.startsWith("404")
        && activeRunId
        && Date.now() - activeRunStartedAt < 5000
      ) {
        banner.className = "starting";
        banner.textContent = "Starting...";
        message.textContent = "";
      } else if (consecutiveRefreshFailures >= 3) {
        message.textContent = `Dashboard refresh failed: ${error.message}`;
      }
    }

    async function refreshProjects(preferred) {
      const projectRefreshVersion = ++projectsRefreshVersion;
      const names = await request("/projects");
      if (projectRefreshVersion !== projectsRefreshVersion) return picker.value;
      const current = preferred || picker.value || activeRunId;
      const projectNames = [...names];
      if (current === activeRunId && !projectNames.includes(activeRunId)) {
        projectNames.push(activeRunId);
      }
      picker.replaceChildren();
      for (const name of projectNames) {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        picker.append(option);
      }
      if (projectNames.includes(current)) picker.value = current;
      else if (projectNames.length) picker.value = projectNames[0];
      return picker.value;
    }

    async function refreshProject() {
      const projectId = picker.value;
      document.getElementById("approve").disabled = !projectId;
      if (!projectId) {
        cy.elements().remove();
        positionCache = new Map();
        selectedNodeId = null;
        stopReplay();
        knownEventIds = new Set();
        eventProjectId = null;
        previewProjectId = null;
        selectedArtifactId = null;
        manualPreviewSelection = false;
        showEmptyDetails();
        banner.textContent = "No projects yet. Click Run demo.";
        banner.className = "";
        document.getElementById("events").replaceChildren();
        document.getElementById("latest-event").textContent = "Waiting for project events.";
        document.getElementById("project-name").textContent = "No project selected";
        document.getElementById("progress-label").textContent = "0 / 0 done";
        document.getElementById("progress-fill").style.width = "0%";
        document.getElementById("artifact-list").replaceChildren();
        document.getElementById("replay-events").disabled = true;
        document.getElementById("artifact-preview").textContent =
          "Generated files will appear here as agents record artifacts.";
        return;
      }
      if (previewProjectId !== projectId) {
        previewProjectId = projectId;
        selectedArtifactId = null;
        manualPreviewSelection = false;
      }
      const [graph, events, release, run, artifacts] = await Promise.all([
        request(`/projects/${encodeURIComponent(projectId)}/graph`),
        request(`/projects/${encodeURIComponent(projectId)}/events`),
        request(`/projects/${encodeURIComponent(projectId)}/release-status`),
        projectId === activeRunId
          ? request(`/demo/runs/${encodeURIComponent(projectId)}`)
          : Promise.resolve(null),
        request(`/projects/${encodeURIComponent(projectId)}/artifacts`)
      ]);
      if (eventProjectId !== projectId) {
        stopReplay();
        eventProjectId = projectId;
        positionCache = new Map();
        cy.elements().remove();
        knownEventIds = activeRunId === projectId
          ? new Set()
          : new Set(events.map(event => event.id).filter(Boolean));
      }
      const projectNode = graph.nodes.find(node => node.label === "Project");
      document.getElementById("project-name").textContent =
        projectNode && projectNode.properties && projectNode.properties.name
          ? projectNode.properties.name
          : projectId;
      document.getElementById("project-name").title =
        projectNode && projectNode.properties && projectNode.properties.name
          ? projectNode.properties.name
          : projectId;
      const laneGraph = window.CrewGraphLayout.buildLaneGraph(
        graph.nodes, graph.edges, positionCache
      );
      const nodes = laneGraph.nodes.map(node => {
        const fullTitle = String(node.title || nodeDisplayLabel(node));
        return {
          ...node,
          fullTitle,
          title: fullTitle.length > 16 ? `${fullTitle.slice(0, 15)}…` : fullTitle
        };
      });
      const tasksById = new Map(
        graph.nodes.filter(node => node.label === "Task").map(node => [node.id, node])
      );
      const tasks = graph.nodes.filter(node => node.label === "Task");
      const completedTasks = tasks.filter(node => node.status === "done").length;
      document.getElementById("progress-label").textContent =
        `${completedTasks} / ${tasks.length} done`;
      document.getElementById("progress-fill").style.width =
        `${tasks.length ? completedTasks / tasks.length * 100 : 0}%`;
      document.getElementById("progress-track").setAttribute("aria-valuenow", completedTasks);
      document.getElementById("progress-track").setAttribute("aria-valuemax", tasks.length);
      const edgeElements = laneGraph.edges;
      const nodeIds = new Set(nodes.map(node => node.id));
      cy.nodes().filter(node => !nodeIds.has(node.id()) && !node.hasClass("particle")).remove();
      const knownNodeIds = new Set(cy.nodes().map(node => node.id()));
      const addedNodes = nodes.filter(node => !knownNodeIds.has(node.id));
      for (const node of nodes) {
        if (knownNodeIds.has(node.id)) {
          const { position, ...data } = node;
          cy.$id(node.id).data(data);
        }
      }
      cy.add(addedNodes.map(node => {
        const { position, ...data } = node;
        return {
          data,
          position,
          classes: reducedMotion ? "" : "entering"
        };
      }));
      const edgeIds = new Set(edgeElements.map(edge => edge.data.id));
      cy.edges().filter(edge => !edgeIds.has(edge.id())).remove();
      const knownEdgeIds = new Set(cy.edges().map(edge => edge.id()));
      const addedEdges = edgeElements.filter(edge => !knownEdgeIds.has(edge.data.id));
      cy.add(addedEdges.map(edge => ({
        ...edge,
        classes: reducedMotion ? "" : "drawing"
      })));
      revealEdges(addedEdges.map(edge => edge.data.id));
      if (addedNodes.length) {
        const preset = cy.layout({ name: "preset", fit: false });
        preset.one("layoutstop", () => {
          if (reducedMotion) {
            cy.fit(cy.elements(), 40);
          } else {
            cy.nodes(".entering").forEach(node => {
              node.animate({ style: { opacity: 1, width: 40, height: 40 } }, {
                duration: TIMINGS.nodeAppearMs / playbackMultiplier(),
                complete: () => node.removeClass("entering")
              });
            });
            cy.animate(
              { fit: { eles: cy.elements(), padding: 40 } },
              { duration: TIMINGS.cameraMs / playbackMultiplier() }
            );
          }
        });
        preset.run();
      }
      syncWorkingNodes();
      showNodeEdges(hoveredNodeId || selectedNodeId);
      for (const item of events) {
        if (item.id && !knownEventIds.has(item.id)) {
          knownEventIds.add(item.id);
          enqueueVisualEvent(item, tasksById);
        }
        if (!replayActive) {
          document.getElementById("replay-events").disabled = events.length === 0;
        }
      }
      const latestEvent = events[events.length - 1];
      if (!visualEventQueue.length && !replayActive) {
        document.getElementById("latest-event").textContent = latestEvent
          ? describeEvent(latestEvent, tasksById)
          : "Waiting for project events.";
      }
      updateStages(graph.nodes, events, release);
      renderOutput(projectId, artifacts, release, run);

      banner.className = release.released
        ? "allowed"
        : release.can_release ? "allowed" : "blocked";
      if (run && run.status === "failed") {
        banner.textContent = `Run failed: ${run.message}`;
      } else if (run && run.status === "running") {
        banner.textContent = "Running...";
      } else if (release.released) {
        banner.textContent = "Released.";
      } else if (
        release.reasons.length === 1
        && release.reasons[0] === "Human approval is required"
      ) {
        banner.textContent = "Human approval is required";
      } else {
        banner.textContent = release.can_release
          ? "Ready for release."
          : `Release blocked: ${release.reasons.join("; ")}`;
      }
      const eventList = document.getElementById("events");
      eventList.replaceChildren();
      for (const item of events) {
        const row = document.createElement("li");
        const when = new Date(item.ts).toLocaleTimeString();
        row.textContent = `${when} — ${item.type}${item.task_id ? `: ${item.task_id}` : ""}${item.detail ? ` (${item.detail})` : ""}`;
        eventList.append(row);
      }
    }

    async function startDemo(flaw) {
      message.textContent = "";
      banner.className = "starting";
      banner.textContent = "Starting...";
      try {
        const started = await request("/demo/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt: promptInput.value, flaw })
        });
        activeRunId = started.project_id;
        activeRunStartedAt = Date.now();
        consecutiveRefreshFailures = 0;
        await refreshProjects(started.project_id);
        picker.value = started.project_id;
        await refreshProject();
        consecutiveRefreshFailures = 0;
        message.textContent = "";
      } catch (error) {
        reportRefreshFailure(error);
      }
    }

    document.getElementById("approve").addEventListener("click", async () => {
      if (!picker.value) return;
      try {
        await request(`/projects/${encodeURIComponent(picker.value)}/approve`, { method: "POST" });
        await refreshProject();
      } catch (error) {
        reportRefreshFailure(error);
      }
    });
    document.getElementById("logout").addEventListener("click", async () => {
      try {
        await request("/auth/logout", { method: "POST" });
        window.location.assign("/login");
      } catch (error) {
        reportRefreshFailure(error);
      }
    });
    document.getElementById("run-prompt").addEventListener("click", () => startDemo(false));
    document.getElementById("run-flaw").addEventListener("click", () => startDemo(true));
    picker.addEventListener("change", () => {
      stopReplay();
      refreshProject().catch(reportRefreshFailure);
    });
    speedControl.addEventListener("change", () => {
      document.querySelectorAll(".stage-step").forEach(step => {
        step.style.setProperty(
          "--pulse-period",
          `${TIMINGS.pulsePeriodMs / playbackMultiplier()}ms`
        );
      });
      syncWorkingNodes();
    });
    document.getElementById("replay-events").addEventListener("click", async () => {
      if (!picker.value) return;
      try {
        const [events, graph] = await Promise.all([
          request(`/projects/${encodeURIComponent(picker.value)}/events`),
          request(`/projects/${encodeURIComponent(picker.value)}/graph`)
        ]);
        const tasksById = new Map(
          graph.nodes.filter(node => node.label === "Task").map(node => [node.id, node])
        );
        replayEvents(events, tasksById);
      } catch (error) {
        reportRefreshFailure(error);
      }
    });

    async function poll() {
      try {
        const previous = activeRunId || picker.value;
        await refreshProjects(previous);
        await refreshProject();
        consecutiveRefreshFailures = 0;
        message.textContent = "";
      } catch (error) {
        reportRefreshFailure(error);
      }
    }
    poll();
    setInterval(poll, 500);
