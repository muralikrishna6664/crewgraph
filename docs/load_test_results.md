# Load test results

Measured on 2026-10-17 with `python -m scripts.load_test --projects 20` against the local FalkorDB instance in mock mode. The run used 20 isolated project graphs and removed them after completion.

| Projects | Tasks | Total time | Tasks/second | Failures | Lease recovery |
|---:|---:|---:|---:|---:|:---|
| 20 | 80 | 11.04 s | 7.25 | 0 | No |

Exact command output:

```text
Projects: 20
Tasks: 80
Total time: 11.04 seconds
Tasks per second: 7.25
Failures: 0
Lease recovery happened: no
```

Machine: Windows 11 (build 26200), Python 3.12.10, 13th Gen Intel Core i5-1335U; local FalkorDB service. This measures local mock-mode throughput and is not a production capacity benchmark.

## Shared-graph contention test

Measured on 2026-10-17 with `python -m scripts.contention_test`. Fifty worker threads, each with its own FalkorDB client, competed for 500 ready tasks in one temporary project graph. Query actions were capped at 8 in flight after an uncapped initial attempt hit FalkorDB's pending-query limit. The cap preserves concurrent worker threads while avoiding overload; this is not a 50-simultaneous-query measurement.

| Workers | Tasks | Max in-flight query actions | Elapsed | Claims/second | p95 claim-call latency | Duplicate claims | Reads | Writes |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50 | 500 | 8 | 3.05 s | 164.01 | 8.96 ms | 0 | 558 | 4500 |

Exact command output:

```text
Workers: 50
Tasks: 500
Max in-flight query actions: 8
Elapsed: 3.05 seconds
Claims per second: 164.01
p95 claim-call latency: 8.96 ms
Duplicate claims: 0
Reads: 558
Writes: 4500
Counts include ready/context reads and claim plus claim-event writes; setup excluded.
```

Reads count `ready_tasks` and `handoff_context` calls. Writes count claim attempts (including losses) and one persisted claim event per winning claim; benchmark setup is excluded. Machine: Windows 11 (build 26200), Python 3.12.10, 13th Gen Intel Core i5-1335U; local FalkorDB service. The temporary graph is deleted after each run.
