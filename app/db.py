from falkordb import FalkorDB
from falkordb.graph import Graph


def get_graph(project_id: str) -> Graph:
    """Return the FalkorDB graph selected for a project."""
    return FalkorDB().select_graph(project_id)
