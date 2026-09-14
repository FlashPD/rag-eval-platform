# Retrieval and answer evaluation `ebd3a2dc-e3db-4348-95a4-e38a10ee9d1d`

- Dataset: `scifact` (`test`)
- Variants: `bm25`, `dense_bge_small`, `hybrid_rrf`, `hybrid_rrf_rerank`
- Seed: `42`
- Results: `200`
- Indexes: `bm25`=`f07c16036aa305192aab16b3bc3eab2a7db625e9c5d3e7d621851ba4a3e79f11`, `dense_bge_small`=`f07c16036aa305192aab16b3bc3eab2a7db625e9c5d3e7d621851ba4a3e79f11`, `hybrid_rrf`=`f07c16036aa305192aab16b3bc3eab2a7db625e9c5d3e7d621851ba4a3e79f11`, `hybrid_rrf_rerank`=`f07c16036aa305192aab16b3bc3eab2a7db625e9c5d3e7d621851ba4a3e79f11`
- Generator: `default` using `scifact-v2`
- Generated variants: `dense_bge_small`
- Judges: `default`, `secondary`

## Quality metrics

| Variant | Metric | Mean | 95% CI | Queries |
|---|---|---:|---:|---:|
| bm25 | nDCG@10 | 0.5671 | [0.4436, 0.6911] | 50 |
| bm25 | Recall@10 | 0.6480 | [0.5160, 0.7700] | 50 |
| bm25 | Recall@100 | 0.7960 | [0.6760, 0.9000] | 50 |
| bm25 | MRR@10 | 0.5429 | [0.4190, 0.6662] | 50 |
| dense_bge_small | nDCG@10 | 0.6808 | [0.5715, 0.7816] | 50 |
| dense_bge_small | Recall@10 | 0.8260 | [0.7200, 0.9200] | 50 |
| dense_bge_small | Recall@100 | 0.9800 | [0.9400, 1.0000] | 50 |
| dense_bge_small | MRR@10 | 0.6387 | [0.5234, 0.7471] | 50 |
| dense_bge_small | Abstention correctness | 0.6800 | [0.5400, 0.8000] | 50 |
| dense_bge_small | Citation validity | 1.0000 | [1.0000, 1.0000] | 50 |
| dense_bge_small | Context precision | 0.1020 | [0.0820, 0.1280] | 50 |
| dense_bge_small | Incremental cost (USD/query) | 0.0030 | [0.0007, 0.0060] | 50 |
| dense_bge_small | Faithfulness | 0.9034 | [0.8302, 0.9634] | 50 |
| dense_bge_small | Answer relevance | 0.9908 | [0.9764, 0.9992] | 50 |
| dense_bge_small | SciFact label accuracy | 0.7800 | [0.6600, 0.8800] | 50 |
| dense_bge_small | SciFact rationale precision | 0.4526 | [0.3212, 0.5827] | 50 |
| dense_bge_small | Secondary judge faithfulness | 0.9600 | [0.9100, 1.0000] | 50 |
| dense_bge_small | Secondary judge relevance | 1.0000 | [1.0000, 1.0000] | 50 |
| dense_bge_small | SciFact macro-F1 | 0.8000 | [0.8000, 0.8000] | 50 |
| hybrid_rrf | nDCG@10 | 0.6248 | [0.5055, 0.7453] | 50 |
| hybrid_rrf | Recall@10 | 0.7460 | [0.6259, 0.8560] | 50 |
| hybrid_rrf | Recall@100 | 1.0000 | [1.0000, 1.0000] | 50 |
| hybrid_rrf | MRR@10 | 0.5914 | [0.4690, 0.7112] | 50 |
| hybrid_rrf_rerank | nDCG@10 | 0.6534 | [0.5428, 0.7577] | 50 |
| hybrid_rrf_rerank | Recall@10 | 0.8053 | [0.6933, 0.9081] | 50 |
| hybrid_rrf_rerank | Recall@100 | 1.0000 | [1.0000, 1.0000] | 50 |
| hybrid_rrf_rerank | MRR@10 | 0.6100 | [0.4941, 0.7195] | 50 |

## Stage latency

| Variant | Stage | P50 (ms) | P95 (ms) | Samples |
|---|---|---:|---:|---:|
| bm25 | hydrate_results | 11.37 | 17.25 | 50 |
| bm25 | sparse_retrieve | 3.17 | 6.37 | 50 |
| dense_bge_small | dense_embed_query | 18.95 | 26.54 | 50 |
| dense_bge_small | dense_retrieve | 26.54 | 38.14 | 50 |
| dense_bge_small | hydrate_results | 10.43 | 16.69 | 50 |
| hybrid_rrf | dense_embed_query | 16.46 | 21.21 | 50 |
| hybrid_rrf | dense_retrieve | 20.93 | 31.18 | 50 |
| hybrid_rrf | fuse | 0.38 | 0.91 | 50 |
| hybrid_rrf | hydrate_results | 9.68 | 16.75 | 50 |
| hybrid_rrf | sparse_retrieve | 2.16 | 2.85 | 50 |
| hybrid_rrf_rerank | dense_embed_query | 15.60 | 20.89 | 50 |
| hybrid_rrf_rerank | dense_retrieve | 19.81 | 41.92 | 50 |
| hybrid_rrf_rerank | fuse | 0.58 | 0.80 | 50 |
| hybrid_rrf_rerank | hydrate_results | 16.08 | 27.57 | 50 |
| hybrid_rrf_rerank | rerank | 1462.14 | 2207.02 | 50 |
| hybrid_rrf_rerank | sparse_retrieve | 1.92 | 2.96 | 50 |

## Variant comparisons

Paired bootstrap over queries. A difference is significant only when its
95% interval excludes zero.

| Variant A | Variant B | Metric | A - B | 95% CI | Significant |
|---|---|---|---:|---:|---|
| bm25 | dense_bge_small | nDCG@10 | -0.1137 | [-0.2146, -0.0021] | yes |
| bm25 | dense_bge_small | Recall@10 | -0.1780 | [-0.3080, -0.0480] | yes |
| bm25 | dense_bge_small | Recall@100 | -0.1840 | [-0.3040, -0.0759] | yes |
| bm25 | dense_bge_small | MRR@10 | -0.0959 | [-0.2097, +0.0138] | no |
| bm25 | hybrid_rrf | nDCG@10 | -0.0577 | [-0.1234, +0.0118] | no |
| bm25 | hybrid_rrf | Recall@10 | -0.0980 | [-0.1860, -0.0280] | yes |
| bm25 | hybrid_rrf | Recall@100 | -0.2040 | [-0.3240, -0.1000] | yes |
| bm25 | hybrid_rrf | MRR@10 | -0.0486 | [-0.1334, +0.0333] | no |
| bm25 | hybrid_rrf_rerank | nDCG@10 | -0.0862 | [-0.1676, -0.0057] | yes |
| bm25 | hybrid_rrf_rerank | Recall@10 | -0.1573 | [-0.2760, -0.0440] | yes |
| bm25 | hybrid_rrf_rerank | Recall@100 | -0.2040 | [-0.3200, -0.1000] | yes |
| bm25 | hybrid_rrf_rerank | MRR@10 | -0.0671 | [-0.1518, +0.0134] | no |
| dense_bge_small | hybrid_rrf | nDCG@10 | +0.0560 | [-0.0101, +0.1347] | no |
| dense_bge_small | hybrid_rrf | Recall@10 | +0.0800 | [-0.0600, +0.2200] | no |
| dense_bge_small | hybrid_rrf | Recall@100 | -0.0200 | [-0.0600, +0.0000] | no |
| dense_bge_small | hybrid_rrf | MRR@10 | +0.0473 | [-0.0086, +0.1144] | no |
| dense_bge_small | hybrid_rrf_rerank | nDCG@10 | +0.0274 | [-0.0608, +0.1194] | no |
| dense_bge_small | hybrid_rrf_rerank | Recall@10 | +0.0207 | [-0.0800, +0.1300] | no |
| dense_bge_small | hybrid_rrf_rerank | Recall@100 | -0.0200 | [-0.0600, +0.0000] | no |
| dense_bge_small | hybrid_rrf_rerank | MRR@10 | +0.0287 | [-0.0665, +0.1313] | no |
| hybrid_rrf | hybrid_rrf_rerank | nDCG@10 | -0.0285 | [-0.0936, +0.0319] | no |
| hybrid_rrf | hybrid_rrf_rerank | Recall@10 | -0.0593 | [-0.1533, +0.0280] | no |
| hybrid_rrf | hybrid_rrf_rerank | Recall@100 | +0.0000 | [+0.0000, +0.0000] | no |
| hybrid_rrf | hybrid_rrf_rerank | MRR@10 | -0.0186 | [-0.0868, +0.0480] | no |
