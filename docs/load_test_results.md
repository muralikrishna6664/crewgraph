# Load test results

Measured with `python -m scripts.load_test` against the local FalkorDB instance in mock mode.
The run used 20 isolated project graphs and removed them after completion.

| Projects | Tasks | Total time | Tasks/second | Failures | Lease recovery |
|---:|---:|---:|---:|---:|:---|
| 20 | 80 | 11.53 s | 6.94 | 0 | No |

Exact command output:

```text
Projects: 20
Tasks: 80
Total time: 11.53 seconds
Tasks per second: 6.94
Failures: 0
Lease recovery happened: no
```

This measures local mock-mode throughput on the current machine; it is not a production capacity benchmark.
