| Model | Accuracy | False approvals | False rejections | Stable cases | Median latency | P95 latency | Tokens in / out | Cost per judgment |
|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite (Vertex) | 94% | 9/102 | 0/48 | 100% of 50 | 9.3 s | 28.4 s | 607 / 70 | $0.000356 |
| gemini-3.1-flash-lite (Vertex) | 92% | 6/102 | 6/48 | 100% of 50 | 9.8 s | 31.5 s | 607 / 69 | $0.000255 |
| gemini-3.8-flash (Vertex) | 98% | 3/102 | 0/48 | 100% of 50 | 14.7 s | 37.2 s | 607 / 409 | $0.001990 |
| gpt-oss-20b (Groq) | 97% | 0/102 | 5/48 | 98% of 50 | 4.0 s | 8.9 s | 617 / 377 | $0.000159 |
