# Retrieval evaluation `da4163b7-5636-4b53-b440-c239b60e95a5`

- Dataset: `scifact` (`test`)
- Variants: `bm25`, `dense_bge_small`, `hybrid_rrf`, `hybrid_rrf_rerank`
- Seed: `42`
- Results: `200`
- Indexes: `bm25`=`92de8e2a9b6b7accfe22109760961888d2c704ba7f9e2e83b27a415abcb1f315`, `dense_bge_small`=`92de8e2a9b6b7accfe22109760961888d2c704ba7f9e2e83b27a415abcb1f315`, `hybrid_rrf`=`92de8e2a9b6b7accfe22109760961888d2c704ba7f9e2e83b27a415abcb1f315`, `hybrid_rrf_rerank`=`92de8e2a9b6b7accfe22109760961888d2c704ba7f9e2e83b27a415abcb1f315`

## Retrieval quality

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
| bm25 | hydrate_results | 7.03 | 8.06 | 50 |
| bm25 | sparse_retrieve | 2.27 | 3.51 | 50 |
| dense_bge_small | dense_embed_query | 15.76 | 21.47 | 50 |
| dense_bge_small | dense_retrieve | 17.89 | 19.83 | 50 |
| dense_bge_small | hydrate_results | 5.71 | 6.90 | 50 |
| hybrid_rrf | dense_embed_query | 15.36 | 17.26 | 50 |
| hybrid_rrf | dense_retrieve | 18.41 | 20.31 | 50 |
| hybrid_rrf | fuse | 0.37 | 0.44 | 50 |
| hybrid_rrf | hydrate_results | 5.68 | 7.26 | 50 |
| hybrid_rrf | sparse_retrieve | 1.70 | 1.96 | 50 |
| hybrid_rrf_rerank | dense_embed_query | 16.35 | 17.82 | 50 |
| hybrid_rrf_rerank | dense_retrieve | 18.54 | 20.03 | 50 |
| hybrid_rrf_rerank | fuse | 0.35 | 0.42 | 50 |
| hybrid_rrf_rerank | hydrate_results | 8.13 | 9.67 | 50 |
| hybrid_rrf_rerank | rerank | 1242.19 | 1412.51 | 50 |
| hybrid_rrf_rerank | sparse_retrieve | 1.58 | 1.78 | 50 |

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
