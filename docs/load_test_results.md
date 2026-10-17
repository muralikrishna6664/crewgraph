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
