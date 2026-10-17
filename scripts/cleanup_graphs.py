"""List or explicitly delete FalkorDB graphs while preserving a keep-list."""

import argparse

from falkordb import FalkorDB


def cleanup_graphs(keep_graphs: set[str], yes: bool) -> list[str]:
    """List graphs outside the keep-list and delete them only when requested."""
    client = FalkorDB()
    try:
        graph_names = set(client.list_graphs())
        unknown = keep_graphs - graph_names
        if unknown:
            raise ValueError(
                "Keep-list contains unknown graphs: " + ", ".join(sorted(unknown))
            )

        targets = sorted(graph_names - keep_graphs)
        for graph_name in sorted(keep_graphs):
            print(f"Keeping: {graph_name}")
        for graph_name in targets:
            if yes:
                client.select_graph(graph_name).delete()
                print(f"Deleted: {graph_name}")
            else:
                print(f"Would delete: {graph_name}")
        if not yes:
            print("Dry run only; pass --yes to delete listed graphs.")
        return targets
    finally:
        client.close()


def main() -> None:
    """Parse the keep-list and default to a non-destructive dry run."""
    parser = argparse.ArgumentParser(
        description="List or delete local FalkorDB graphs outside a keep-list."
    )
    parser.add_argument(
        "--keep",
        nargs="*",
        default=[],
        metavar="GRAPH",
        help="graph names to preserve",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list deletion targets without deleting (the default)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="delete graphs outside the keep-list",
    )
    args = parser.parse_args()
    try:
        cleanup_graphs(set(args.keep), yes=args.yes)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
