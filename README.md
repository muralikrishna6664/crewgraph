# CrewGraph

CrewGraph is a multi-agent coordination prototype backed by FalkorDB. Agents share project work through a graph rather than calling one another directly.

## Run locally

1. Start FalkorDB: `docker compose up -d`
2. Create and activate a Python 3.11 virtual environment.
3. Install dependencies: `pip install -r requirements.txt`
4. Start the API: `uvicorn app.main:app --reload`
5. Check `http://localhost:8000/health`. FalkorDB's browser UI is available at `http://localhost:3000`.

Run the health endpoint test with `pytest`.

`.env.example` provides a sample project ID for future configuration; the starter does not load environment variables yet.

## Seed separate project graphs

With FalkorDB running, run `python -m scripts.seed` from the project root. The script selects the `tenant_a` and `tenant_b` graphs independently, creates the task, artifact, and bug ID indexes in each, and adds synthetic project/task nodes. Open the FalkorDB Browser at `http://localhost:3000` and inspect `tenant_a` and `tenant_b` separately.
