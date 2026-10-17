import os

from falkordb import FalkorDB
from falkordb.graph import Graph


def get_client() -> FalkorDB:
    """Create a FalkorDB client using the configured service host."""
    return FalkorDB(host=os.getenv("FALKORDB_HOST", "localhost"))


def get_graph(project_id: str) -> Graph:
    """Return the FalkorDB graph selected for a project."""
    return get_client().select_graph(project_id)
