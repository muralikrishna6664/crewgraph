"""CrewGraph node labels, relationship types, and project initialization."""

from falkordb.graph import Graph
from redis.exceptions import ResponseError

from app import queries
from app.db import get_graph

PROJECT = "Project"
TASK = "Task"
AGENT = "Agent"
SKILL = "Skill"
ARTIFACT = "Artifact"
BUG = "Bug"
VULNERABILITY = "Vulnerability"
EPISODE = "Episode"
LESSON = "Lesson"
APPROVAL = "Approval"
REVIEW = "Review"

NODE_LABELS = (
    PROJECT,
    TASK,
    AGENT,
    SKILL,
    ARTIFACT,
    BUG,
    VULNERABILITY,
    EPISODE,
    LESSON,
    APPROVAL,
    REVIEW,
)

DEPENDS_ON = "DEPENDS_ON"
NEEDS = "NEEDS"
HAS_SKILL = "HAS_SKILL"
PRODUCED_BY = "PRODUCED_BY"
FOR_TASK = "FOR_TASK"
HANDED_OFF_TO = "HANDED_OFF_TO"
FOUND_IN = "FOUND_IN"
FIXED_BY = "FIXED_BY"
BLOCKS = "BLOCKS"
APPROVES = "APPROVES"
REVIEWS = "REVIEWS"
DERIVED_FROM = "DERIVED_FROM"
PART_OF = "PART_OF"

EDGE_TYPES = (
    DEPENDS_ON,
    NEEDS,
    HAS_SKILL,
    PRODUCED_BY,
    FOR_TASK,
    HANDED_OFF_TO,
    FOUND_IN,
    FIXED_BY,
    BLOCKS,
    APPROVES,
    REVIEWS,
    DERIVED_FROM,
    PART_OF,
)


def init_project(project_id: str) -> Graph:
    """Select a project's graph and create indexes used by common lookups."""
    graph = get_graph(project_id)
    for index_query in (
        queries.create_task_id_index(),
        queries.create_artifact_id_index(),
        queries.create_bug_id_index(),
    ):
        try:
            graph.query(index_query)
        except ResponseError as error:
            if "already indexed" not in str(error):
                raise
    return graph
