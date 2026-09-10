# Run comparison

| run | split | n | exact_match | invalid_rate | queue_acc | queue_f1 | priority_acc | priority_f1 | type_acc | type_f1 | lat_p50_ms | lat_p95_ms | total_cost_usd | cost_per_1000_usd |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| random-baseline | test | 1633 | 2.20% | 0.00% | 17.82% | 0.1110 | 36.56% | 0.3427 | 30.80% | 0.2577 | 0.00 | 0.00 | 0.0000 | 0.0000 |
| api-gpt4o-mini-50 | test | 50 | 12.00% | 0.00% | 48.00% | 0.6486 | 42.00% | 0.3111 | 78.00% | 0.6757 | 677.92 | 1841.18 | 0.0000 | 0.0000 |
| api-gpt4o-mini-full-test | test | 1633 | 10.90% | 0.00% | 33.37% | 0.2554 | 43.54% | 0.3214 | 64.18% | 0.5209 | 698.54 | 1092.26 | 0.0000 | 0.0000 |
