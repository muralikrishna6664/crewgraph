    const picker = document.getElementById("project-picker");
    const banner = document.getElementById("release-banner");
    const message = document.getElementById("message");
    const promptInput = document.getElementById("build-prompt");
    const colors = {
      Project: "#b98aff", Prompt: "#b98aff", Output: "#b98aff",
      Agent: "#5b9dff", Artifact: "#4de3ef", Vulnerability: "#ff527f",
      Approval: "#b98aff"
    };
    const stageNames = ["Planner", "Backend / Frontend", "Tester", "Debugger", "Security", "Approval", "Release"];
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let lastNodeIds = null;
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
    let replayTimeouts = [];
    let replayVersion = 0;
    let replayActive = false;

    function initializeStages() {
      const strip = document.getElementById("stage-strip");
      stageNames.forEach((name, index) => {
        const step = document.createElement("div");
        step.className = "stage-step";
        step.dataset.stage = String(index);
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

    function animateStageTravel(stageIndex) {
      if (stageIndex === null || stageIndex <= 0) return;
      const link = document.querySelector(`.stage-link[data-link="${stageIndex - 1}"]`);
      if (!link) return;
      const dot = document.createElement("i");
      dot.className = "travel-dot";
      link.append(dot);
      dot.addEventListener("animationend", () => dot.remove(), { once: true });
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

    function stopReplay() {
      replayVersion += 1;
      replayTimeouts.forEach(timer => window.clearTimeout(timer));
      replayTimeouts = [];
      replayActive = false;
      document.getElementById("replay-events").disabled = false;
    }

    function animateReplayEvent(event, tasksById) {
      document.getElementById("latest-event").textContent =
        describeEvent(event, tasksById);
      animateStageTravel(stageForEvent(event, tasksById));
      if (event.type === "bug found") animateFoundBug(event.bug_id);
      if (reducedMotion) return;
      const targetId = event.task_id || event.artifact_id || event.bug_id;
      if (!targetId) return;
      const node = cy.$id(targetId);
      if (!node.length) return;
      node.animate({ style: { "shadow-blur": 29, "shadow-opacity": 1 } }, {
        duration: 180,
        complete: () => node.animate({
          style: { "shadow-blur": 15, "shadow-opacity": 0.62 }
        }, { duration: 100 })
      });
    }

    function replayEvents(events, tasksById) {
      stopReplay();
      const version = replayVersion;
      const button = document.getElementById("replay-events");
      button.disabled = true;
      replayActive = events.length > 0;
      let elapsed = 0;
      let previousTimestamp = null;
      events.forEach((event, index) => {
        const timestamp = Number(event.ts);
        if (Number.isFinite(timestamp)) {
          if (previousTimestamp !== null && timestamp >= previousTimestamp) {
            elapsed += (timestamp - previousTimestamp) / 4;
          }
          previousTimestamp = timestamp;
        }
        const timer = window.setTimeout(() => {
          if (version !== replayVersion) return;
          animateReplayEvent(event, tasksById);
          if (index === events.length - 1) {
            replayActive = false;
            button.disabled = false;
          }
        }, elapsed);
        replayTimeouts.push(timer);
      });
      if (!events.length) button.disabled = true;
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
      layout: {
        name: "breadthfirst", directed: true, direction: "TB",
        padding: 28, spacingFactor: 1.1
      },
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
            color: "#e4eaf4", "text-valign": "bottom", "text-halign": "center",
            "text-wrap": "wrap", "text-max-width": 120, "font-size": 12,
            "font-family": "Cascadia Code, Consolas, monospace",
            "text-margin-y": 7,
            width: 40, height: 40, "border-width": 1, "border-color": "#c7d4e6",
            "shadow-color": element => {
              const data = element.data();
              if (data.label === "Bug") return data.status === "fixed" ? "#55e69a" : "#ff527f";
              if (data.label === "Task") {
                return {done: "#55e69a", ready: "#f5bd4f", claimed: "#5b9dff"}[data.status] || "#758398";
              }
              return colors[data.label] || "#b98aff";
            },
            "shadow-blur": 15, "shadow-opacity": 0.62, "shadow-offset-x": 0, "shadow-offset-y": 0,
            "transition-property": "opacity, width, height, shadow-blur",
            "transition-duration": "220ms"
          }
        },
        {
          selector: "node.entering",
          style: { opacity: 0, width: 20, height: 20 }
        },
        {
          selector: "node.working",
          style: { "border-width": 3, "border-color": "#9bc3ff", "shadow-blur": 22, "shadow-opacity": 0.9 }
        },
        {
          selector: "node.shaking",
          style: { "border-color": "#fff0a8", "shadow-color": "#ff527f", "shadow-blur": 25, "shadow-opacity": 1 }
        },
        {
          selector: "edge",
          style: {
            width: 1.5, "line-color": "#344357", "target-arrow-color": "#526783",
            "target-arrow-shape": "triangle", "curve-style": "bezier",
            label: "", "font-size": 9, color: "#91a2b9",
            "text-background-color": "#0e131c", "text-background-opacity": 1,
            opacity: 0.8, "transition-property": "opacity", "transition-duration": "220ms"
          }
        },
        {
          selector: "edge.drawing",
          style: { opacity: 0 }
        },
        {
          selector: "edge.edge-visible",
          style: { label: "data(type)", "line-color": "#9b7ad9", "target-arrow-color": "#b98aff" }
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
      showNodeEdges(hoveredNodeId);
    });

    cy.on("mouseout", "node", () => {
      hoveredNodeId = null;
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
        case "Prompt": return properties.prompt || "Prompt";
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
      node.animate({ style: { "shadow-blur": 25 } }, {
        duration: 650,
        complete: () => {
          if (!node.hasClass("working")) return;
          node.animate({ style: { "shadow-blur": 12 } }, {
            duration: 650,
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
        window.setTimeout(
          () => cy.$id(id).removeClass("drawing"),
          reducedMotion ? 0 : index * 55
        );
      });
    }

    function animateFoundBug(bugId) {
      const bug = cy.$id(bugId);
      if (!bug.length || reducedMotion) return;
      bug.addClass("shaking");
      const origin = bug.position();
      bug.animate({ position: { x: origin.x + 5, y: origin.y } }, {
        duration: 55,
        complete: () => bug.animate({ position: origin }, {
          duration: 65,
          complete: () => bug.removeClass("shaking")
        })
      });
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
        lastNodeIds = null;
        selectedNodeId = null;
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
      const nodes = graph.nodes.map(node => {
        const label = nodeDisplayLabel(node);
        return { ...node, title: String(label).slice(0, 24) };
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
      const edges = graph.edges.map(edge => ({
        data: {
          id: `${edge.source}:${edge.type}:${edge.target}`,
          source: edge.source, target: edge.target, type: edge.type
        }
      }));
      if (eventProjectId !== projectId) {
        eventProjectId = projectId;
        knownEventIds = new Set();
      }
      const nodeIds = nodes.map(node => node.id).sort();
      const nodeIdsKey = JSON.stringify(nodeIds);
      if (nodeIdsKey !== lastNodeIds) {
        cy.elements().remove();
        cy.add([
          ...nodes.map(node => ({
            data: node,
            classes: reducedMotion ? "" : "entering"
          })),
          ...edges.map(edge => ({
            ...edge,
            classes: reducedMotion ? "" : "drawing"
          }))
        ]);
        const layout = cy.layout({
          name: "breadthfirst", directed: true, direction: "TB",
          padding: 28, spacingFactor: 1.1
        });
        layout.one("layoutstop", () => {
          cy.fit(cy.elements(), 28);
          if (!reducedMotion) {
            cy.nodes(".entering").forEach(node => {
              node.animate({ style: { opacity: 1, width: 40, height: 40 } }, {
                duration: 280,
                complete: () => node.removeClass("entering")
              });
            });
          }
          revealEdges(edges.map(edge => edge.data.id));
          syncWorkingNodes();
        });
        layout.run();
        lastNodeIds = nodeIdsKey;
        selectedNodeId = null;
      } else {
        for (const nodeData of nodes) {
          cy.$id(nodeData.id).data(nodeData);
        }
        const newEdgeIds = new Set(edges.map(edge => edge.data.id));
        cy.edges().filter(edge => !newEdgeIds.has(edge.id())).remove();
        const existingEdgeIds = new Set(cy.edges().map(edge => edge.id()));
        const addedEdges = edges.filter(edge => !existingEdgeIds.has(edge.data.id));
        cy.add(addedEdges.map(edge => ({
          ...edge,
          classes: reducedMotion ? "" : "drawing"
        })));
        revealEdges(addedEdges.map(edge => edge.data.id));
        syncWorkingNodes();
      }
      showNodeEdges(hoveredNodeId || selectedNodeId);
      for (const item of events) {
        if (item.id && !knownEventIds.has(item.id)) {
          knownEventIds.add(item.id);
          if (item.type === "bug found") animateFoundBug(item.bug_id);
          animateStageTravel(stageForEvent(item, tasksById));
        }
        if (!replayActive) {
          document.getElementById("replay-events").disabled = events.length === 0;
        }
      }
      const latestEvent = events[events.length - 1];
      document.getElementById("latest-event").textContent = latestEvent
        ? describeEvent(latestEvent, tasksById)
        : "Waiting for project events.";
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
    setInterval(poll, 2000);
