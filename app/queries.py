"""Named Cypher query definitions used by the application."""

from falkordb.graph import Graph
from falkordb.node import Node


def record_artifact(
    graph: Graph,
    task_id: str,
    agent: str,
    path: str,
    kind: str,
    content: str = "",
    artifact_id: str | None = None,
) -> Node:
    """Create or update an artifact with its content and task and producer links."""
    artifact_id = artifact_id or f"{task_id}:{path}"
    result = graph.query(
        """
        MATCH (task:Task {id: $task_id})
        MERGE (agent:Agent {name: $agent})
        MERGE (artifact:Artifact {id: $artifact_id})
        ON CREATE SET artifact.ts = timestamp()
        SET artifact.path = $path,
            artifact.kind = $kind,
            artifact.content = $content,
            artifact.task_id = $task_id
        MERGE (artifact)-[:FOR_TASK]->(task)
        MERGE (artifact)-[:PRODUCED_BY]->(agent)
        RETURN artifact
        """,
        {
            "task_id": task_id,
            "agent": agent,
            "artifact_id": artifact_id,
            "path": path,
            "kind": kind,
            "content": content,
        },
    )
    if not result.result_set:
        raise ValueError(f"Task not found: {task_id}")
    return result.result_set[0][0]


def handoff(
    graph: Graph, task_id: str, from_agent: str, to_agent: str, reason: str
) -> None:
    """Record an idempotent handoff from one agent to another for a task."""
    result = graph.query(
        """
        MATCH (task:Task {id: $task_id})
        MERGE (recipient:Agent {name: $to_agent})
        MERGE (task)-[handoff:HANDED_OFF_TO {from_agent: $from_agent}]->(recipient)
        SET handoff.reason = $reason,
            handoff.ts = timestamp()
        RETURN task
        """,
        {
            "task_id": task_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "reason": reason,
        },
    )
    if not result.result_set:
        raise ValueError(f"Task not found: {task_id}")


def handoff_context(graph: Graph, task_id: str) -> dict[str, object] | None:
    """Read a task with its own and dependency artifacts, open issues, and lessons."""
    result = graph.ro_query(
        """
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
        """,
        {"task_id": task_id},
    )
    if not result.result_set:
        return None

    task, artifacts, issues, lessons = result.result_set[0]
    return {
        "task": task.properties,
        "artifacts": [artifact.properties for artifact in artifacts],
        "issues": [issue.properties for issue in issues],
        "lessons": [lesson.properties for lesson in lessons],
    }


def record_bug(
    graph: Graph,
    bug_id: str,
    title: str,
    severity: str,
    artifact_id: str,
    status: str = "open",
    kind: str = "functional",
    line: int | None = None,
    fix_suggestion: str = "",
) -> None:
    """Create or update a bug and link it to the artifact that caused it."""
    result = graph.query(
        """
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
        """,
        {
            "bug_id": bug_id,
            "title": title,
            "severity": severity,
            "artifact_id": artifact_id,
            "status": status,
            "kind": kind,
            "line": line,
            "fix_suggestion": fix_suggestion,
        },
    )
    if not result.result_set:
        raise ValueError(f"Artifact not found: {artifact_id}")


def link_artifact_fixes_bug(
    graph: Graph, artifact_id: str, bug_id: str
) -> None:
    """Link a repaired artifact to the bug it fixes."""
    result = graph.query(
        """
        MATCH (artifact:Artifact {id: $artifact_id})
        MATCH (bug:Bug {id: $bug_id})
        MERGE (artifact)-[:FIXES]->(bug)
        RETURN bug
        """,
        {"artifact_id": artifact_id, "bug_id": bug_id},
    )
    if not result.result_set:
        raise ValueError(f"Artifact or bug not found: {artifact_id}, {bug_id}")


def mark_bugs_fixed(graph: Graph, bug_ids: list[str]) -> None:
    """Mark the listed bugs fixed after their regression checks pass."""
    if not bug_ids:
        return
    graph.query(
        """
        UNWIND $bug_ids AS bug_id
        MATCH (bug:Bug {id: bug_id})
        SET bug.status = 'fixed'
        """,
        {"bug_ids": bug_ids},
    )


def get_task(graph: Graph, task_id: str) -> Node | None:
    """Return a task by ID or nothing if it does not exist."""
    result = graph.ro_query(
        "MATCH (task:Task {id: $task_id}) RETURN task",
        {"task_id": task_id},
    )
    return result.result_set[0][0] if result.result_set else None


def bugs(graph: Graph) -> list[dict[str, object]]:
    """Return every bug and its source artifact in the selected project graph."""
    result = graph.ro_query(
        """
        MATCH (bug:Bug)-[:FOUND_IN]->(artifact:Artifact)
        RETURN bug, artifact
        ORDER BY bug.id
        """
    )
    return [
        {"bug": row[0].properties, "artifact": row[1].properties}
        for row in result.result_set
    ]


def bug_fix_artifacts(graph: Graph, bug_id: str) -> list[Node]:
    """Return artifacts linked as fixes for the specified bug."""
    result = graph.ro_query(
        """
        MATCH (artifact:Artifact)-[:FIXES]->(bug:Bug {id: $bug_id})
        RETURN artifact
        """,
        {"bug_id": bug_id},
    )
    return [row[0] for row in result.result_set]


def prepare_task_retry(graph: Graph, task_id: str) -> Node:
    """Return a failed task to ready state for a bounded repair attempt."""
    result = graph.query(
        """
        MATCH (task:Task {id: $task_id})
        WHERE task.status = 'failed'
        SET task.status = 'ready'
        REMOVE task.failure_reason
        RETURN task
        """,
        {"task_id": task_id},
    )
    if not result.result_set:
        raise ValueError(f"Failed task not found: {task_id}")
    return result.result_set[0][0]


def open_bugs(graph: Graph) -> list[dict[str, object]]:
    """Return open bugs and the artifact each bug was found in."""
    result = graph.ro_query(
        """
        MATCH (bug:Bug {status: 'open'})-[:FOUND_IN]->(artifact:Artifact)
        RETURN bug, artifact
        ORDER BY bug.id
        """
    )
    return [
        {"bug": row[0].properties, "artifact": row[1].properties}
        for row in result.result_set
    ]


def count_bugs(graph: Graph) -> int:
    """Return the total number of Bug nodes in the selected project graph."""
    result = graph.ro_query("MATCH (bug:Bug) RETURN count(bug)")
    return int(result.result_set[0][0]) if result.result_set else 0


def fail_task(graph: Graph, task_id: str, reason: str) -> Node:
    """Mark a task failed and store the reason it could not pass."""
    result = graph.query(
        """
        MATCH (task:Task {id: $task_id})
        SET task.status = 'failed',
            task.failure_reason = $reason
        RETURN task
        """,
        {"task_id": task_id, "reason": reason},
    )
    if not result.result_set:
        raise ValueError(f"Task not found: {task_id}")
    return result.result_set[0][0]


def record_vulnerability(
    graph: Graph,
    vulnerability_id: str,
    artifact_id: str,
    vulnerability_type: str,
    severity: str,
    status: str,
) -> None:
    """Create or update a vulnerability and link it to its affected artifact."""
    graph.query(
        """
        MATCH (artifact:Artifact {id: $artifact_id})
        MERGE (vulnerability:Vulnerability {id: $vulnerability_id})
        SET vulnerability.type = $vulnerability_type,
            vulnerability.severity = $severity,
            vulnerability.status = $status
        MERGE (vulnerability)-[:FOUND_IN]->(artifact)
        """,
        {
            "vulnerability_id": vulnerability_id,
            "artifact_id": artifact_id,
            "vulnerability_type": vulnerability_type,
            "severity": severity,
            "status": status,
        },
    )


def record_lesson(graph: Graph, lesson_id: str, content: str) -> None:
    """Create or update a lesson in the selected project graph."""
    graph.query(
        """
        MERGE (lesson:Lesson {id: $lesson_id})
        SET lesson.content = $content
        """,
        {"lesson_id": lesson_id, "content": content},
    )


def create_task_id_index() -> str:
    """Create an index for looking up tasks by their ID."""
    return "CREATE INDEX FOR (task:Task) ON (task.id)"


def create_artifact_id_index() -> str:
    """Create an index for looking up artifacts by their ID."""
    return "CREATE INDEX FOR (artifact:Artifact) ON (artifact.id)"


def create_bug_id_index() -> str:
    """Create an index for looking up bugs by their ID."""
    return "CREATE INDEX FOR (bug:Bug) ON (bug.id)"


def create_project_with_tasks() -> str:
    """Create or update a project and its synthetic tasks in the selected graph."""
    return """
    MERGE (project:Project {id: $project_id})
    SET project.name = $project_name
    WITH project, $tasks AS tasks
    UNWIND tasks AS task
    MERGE (item:Task {id: task.id})
    SET item.title = task.title,
        item.status = task.status,
        item.skill = task.skill,
        item.ts = task.ts
    MERGE (item)-[:PART_OF]->(project)
    RETURN project.id AS project_id, count(item) AS task_count
    """


def create_task_dependencies() -> str:
    """Create or update dependency edges between project tasks."""
    return """
    UNWIND $dependencies AS dependency
    MATCH (dependent:Task {id: dependency.task_id})
    MATCH (prerequisite:Task {id: dependency.depends_on})
    MERGE (dependent)-[:DEPENDS_ON]->(prerequisite)
    RETURN count(*) AS dependency_count
    """


def create_project(graph: Graph, project_id: str) -> None:
    """Create the project's node or update its display name."""
    graph.query(
        """
        MERGE (project:Project {id: $project_id})
        SET project.name = $project_name
        """,
        {"project_id": project_id, "project_name": project_id},
    )


def link_tasks_to_project(
    graph: Graph, project_id: str, task_ids: list[str]
) -> None:
    """Connect each existing task to its project without duplicating relationships."""
    graph.query(
        """
        MATCH (project:Project {id: $project_id})
        UNWIND $task_ids AS task_id
        MATCH (task:Task {id: task_id})
        MERGE (task)-[:PART_OF]->(project)
        """,
        {"project_id": project_id, "task_ids": task_ids},
    )


def create_task_dag(
    graph: Graph, tasks: list[dict[str, str]], deps: list[dict[str, str]]
) -> None:
    """Create tasks and dependency edges, making tasks without prerequisites ready."""
    dependent_ids = {dependency["task_id"] for dependency in deps}
    task_data = [
        {
            **task,
            "status": "pending" if task["id"] in dependent_ids else "ready",
        }
        for task in tasks
    ]
    graph.query(
        """
        UNWIND $tasks AS data
        MERGE (task:Task {id: data.id})
        ON CREATE SET task += data
        """,
        {"tasks": task_data},
    )
    if deps:
        graph.query(
            """
            UNWIND $deps AS dependency
            MATCH (task:Task {id: dependency.task_id})
            MATCH (prerequisite:Task {id: dependency.depends_on})
            MERGE (task)-[:DEPENDS_ON]->(prerequisite)
            """,
            {"deps": deps},
        )


def ready_tasks(graph: Graph) -> list[Node]:
    """Return pending or ready tasks whose dependencies are all done."""
    result = graph.ro_query(
        """
        MATCH (task:Task)
        WHERE task.status IN ['pending', 'ready']
        OPTIONAL MATCH (task)-[:DEPENDS_ON]->(dependency:Task)
        WITH task,
             count(dependency) AS dependency_count,
             sum(CASE WHEN dependency.status = 'done' THEN 1 ELSE 0 END) AS done_count
        WHERE dependency_count = done_count
        RETURN task
        """
    )
    return [row[0] for row in result.result_set]


def claim_task(
    graph: Graph, task_id: str, agent: str, lease_seconds: int
) -> Node | None:
    """Claim a ready task for an agent, returning nothing if another claim won."""
    result = graph.query(
        """
        MATCH (task:Task {id: $task_id})
        WHERE task.status = 'ready'
        SET task.status = 'claimed',
            task.claimed_by = $agent,
            task.lease_until = timestamp() + ($lease_seconds * 1000)
        RETURN task
        """,
        {
            "task_id": task_id,
            "agent": agent,
            "lease_seconds": lease_seconds,
        },
    )
    return result.result_set[0][0] if result.result_set else None


def complete_task(graph: Graph, task_id: str) -> Node | None:
    """Mark a task done and promote pending tasks whose dependencies are complete."""
    result = graph.query(
        """
        MATCH (task:Task {id: $task_id})
        SET task.status = 'done'
        RETURN task
        """,
        {"task_id": task_id},
    )
    if not result.result_set:
        return None

    graph.query(
        """
        MATCH (task:Task {status: 'pending'})
        OPTIONAL MATCH (task)-[:DEPENDS_ON]->(dependency:Task)
        WITH task,
             count(dependency) AS dependency_count,
             sum(CASE WHEN dependency.status = 'done' THEN 1 ELSE 0 END) AS done_count
        WHERE dependency_count = done_count
        SET task.status = 'ready'
        """
    )
    return result.result_set[0][0]


def project_task_statuses(graph: Graph) -> list[Node]:
    """Return each task in the selected project graph with its current status."""
    result = graph.ro_query("MATCH (task:Task) RETURN task ORDER BY task.id")
    return [row[0] for row in result.result_set]


def task_artifacts(graph: Graph) -> list[dict[str, object]]:
    """Return task artifacts and the names of the agents that produced them."""
    result = graph.ro_query(
        """
        MATCH (artifact:Artifact)-[:FOR_TASK]->(task:Task)
        OPTIONAL MATCH (artifact)-[:PRODUCED_BY]->(agent:Agent)
        RETURN task, artifact, collect(DISTINCT agent) AS agents
        ORDER BY task.id, artifact.path
        """
    )
    return [
        {
            "task": row[0].properties,
            "artifact": row[1].properties,
            "agents": [agent.properties.get("name") for agent in row[2]],
        }
        for row in result.result_set
    ]
