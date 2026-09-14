# Retrieval evaluation `447d6235-3773-44a3-bc4d-bbf96df2c159`

- Dataset: `scifact` (`test`)
- Variants: `bm25`, `dense_bge_small`, `hybrid_rrf`, `hybrid_rrf_rerank`
- Seed: `42`
- Results: `1200`

## Retrieval quality

| Variant | Metric | Mean | 95% CI | Queries |
|---|---|---:|---:|---:|
| bm25 | nDCG@10 | 0.6617 | [0.6154, 0.7065] | 300 |
| bm25 | Recall@10 | 0.7739 | [0.7272, 0.8177] | 300 |
| bm25 | Recall@100 | 0.8759 | [0.8393, 0.9110] | 300 |
| bm25 | MRR@10 | 0.6312 | [0.5832, 0.6776] | 300 |
| dense_bge_small | nDCG@10 | 0.7200 | [0.6792, 0.7613] | 300 |
| dense_bge_small | Recall@10 | 0.8452 | [0.8032, 0.8826] | 300 |
| dense_bge_small | Recall@100 | 0.9533 | [0.9300, 0.9767] | 300 |
| dense_bge_small | MRR@10 | 0.6845 | [0.6400, 0.7294] | 300 |
| hybrid_rrf | nDCG@10 | 0.7085 | [0.6647, 0.7529] | 300 |
| hybrid_rrf | Recall@10 | 0.8319 | [0.7889, 0.8736] | 300 |
| hybrid_rrf | Recall@100 | 0.9650 | [0.9433, 0.9833] | 300 |
| hybrid_rrf | MRR@10 | 0.6736 | [0.6281, 0.7194] | 300 |
| hybrid_rrf_rerank | nDCG@10 | 0.6934 | [0.6480, 0.7369] | 300 |
| hybrid_rrf_rerank | Recall@10 | 0.8222 | [0.7781, 0.8647] | 300 |
| hybrid_rrf_rerank | Recall@100 | 0.9650 | [0.9417, 0.9833] | 300 |
| hybrid_rrf_rerank | MRR@10 | 0.6619 | [0.6157, 0.7087] | 300 |

## Stage latency

| Variant | Stage | P50 (ms) | P95 (ms) | Samples |
|---|---|---:|---:|---:|
| bm25 | hydrate_results | 7.42 | 8.17 | 300 |
| bm25 | sparse_retrieve | 2.16 | 2.81 | 300 |
| dense_bge_small | dense_embed_query | 16.37 | 20.04 | 300 |
| dense_bge_small | dense_retrieve | 23.22 | 24.98 | 300 |
| dense_bge_small | hydrate_results | 5.93 | 7.01 | 300 |
| hybrid_rrf | dense_embed_query | 15.84 | 19.32 | 300 |
| hybrid_rrf | dense_retrieve | 22.42 | 24.83 | 300 |
| hybrid_rrf | fuse | 0.42 | 0.49 | 300 |
| hybrid_rrf | hydrate_results | 6.04 | 6.86 | 300 |
| hybrid_rrf | sparse_retrieve | 1.77 | 2.06 | 300 |
| hybrid_rrf_rerank | dense_embed_query | 16.16 | 18.73 | 300 |
| hybrid_rrf_rerank | dense_retrieve | 20.63 | 24.10 | 300 |
| hybrid_rrf_rerank | fuse | 0.39 | 0.48 | 300 |
| hybrid_rrf_rerank | hydrate_results | 8.73 | 10.01 | 300 |
| hybrid_rrf_rerank | rerank | 1140.64 | 1296.60 | 300 |
| hybrid_rrf_rerank | sparse_retrieve | 1.67 | 1.92 | 300 |

## Variant comparisons

Paired bootstrap over queries. A difference is significant only when its
95% interval excludes zero.

| Variant A | Variant B | Metric | A - B | 95% CI | Significant |
|---|---|---|---:|---:|---|
| bm25 | dense_bge_small | nDCG@10 | -0.0583 | [-0.0980, -0.0171] | yes |
| bm25 | dense_bge_small | Recall@10 | -0.0713 | [-0.1158, -0.0291] | yes |
| bm25 | dense_bge_small | Recall@100 | -0.0774 | [-0.1193, -0.0388] | yes |
| bm25 | dense_bge_small | MRR@10 | -0.0532 | [-0.0969, -0.0100] | yes |
| bm25 | hybrid_rrf | nDCG@10 | -0.0468 | [-0.0696, -0.0245] | yes |
| bm25 | hybrid_rrf | Recall@10 | -0.0579 | [-0.0899, -0.0282] | yes |
| bm25 | hybrid_rrf | Recall@100 | -0.0891 | [-0.1222, -0.0591] | yes |
| bm25 | hybrid_rrf | MRR@10 | -0.0423 | [-0.0697, -0.0146] | yes |
| bm25 | hybrid_rrf_rerank | nDCG@10 | -0.0317 | [-0.0649, +0.0013] | no |
| bm25 | hybrid_rrf_rerank | Recall@10 | -0.0483 | [-0.0877, -0.0100] | yes |
| bm25 | hybrid_rrf_rerank | Recall@100 | -0.0891 | [-0.1226, -0.0587] | yes |
| bm25 | hybrid_rrf_rerank | MRR@10 | -0.0307 | [-0.0691, +0.0065] | no |
| dense_bge_small | hybrid_rrf | nDCG@10 | +0.0115 | [-0.0167, +0.0391] | no |
| dense_bge_small | hybrid_rrf | Recall@10 | +0.0133 | [-0.0267, +0.0533] | no |
| dense_bge_small | hybrid_rrf | Recall@100 | -0.0117 | [-0.0367, +0.0100] | no |
| dense_bge_small | hybrid_rrf | MRR@10 | +0.0109 | [-0.0184, +0.0406] | no |
| dense_bge_small | hybrid_rrf_rerank | nDCG@10 | +0.0266 | [-0.0024, +0.0578] | no |
| dense_bge_small | hybrid_rrf_rerank | Recall@10 | +0.0230 | [-0.0127, +0.0568] | no |
| dense_bge_small | hybrid_rrf_rerank | Recall@100 | -0.0117 | [-0.0367, +0.0100] | no |
| dense_bge_small | hybrid_rrf_rerank | MRR@10 | +0.0225 | [-0.0145, +0.0572] | no |
| hybrid_rrf | hybrid_rrf_rerank | nDCG@10 | +0.0151 | [-0.0142, +0.0422] | no |
| hybrid_rrf | hybrid_rrf_rerank | Recall@10 | +0.0097 | [-0.0256, +0.0439] | no |
| hybrid_rrf | hybrid_rrf_rerank | Recall@100 | +0.0000 | [+0.0000, +0.0000] | no |
| hybrid_rrf | hybrid_rrf_rerank | MRR@10 | +0.0116 | [-0.0236, +0.0461] | no |
