# Retrieval evaluation `a0611a31-bd3a-4bb5-976c-c3a885230c93`

- Dataset: `fiqa` (`test`)
- Variants: `bm25`, `dense_bge_small`, `hybrid_rrf`, `hybrid_rrf_rerank`
- Seed: `42`
- Results: `2592`
- Indexes: `bm25`=`fc2bd6e33131fb8f56caaa441ab8b7b5f42c4fe370fa9ef6fcc46853c914c1b4`, `dense_bge_small`=`fc2bd6e33131fb8f56caaa441ab8b7b5f42c4fe370fa9ef6fcc46853c914c1b4`, `hybrid_rrf`=`fc2bd6e33131fb8f56caaa441ab8b7b5f42c4fe370fa9ef6fcc46853c914c1b4`, `hybrid_rrf_rerank`=`fc2bd6e33131fb8f56caaa441ab8b7b5f42c4fe370fa9ef6fcc46853c914c1b4`

## Retrieval quality

| Variant | Metric | Mean | 95% CI | Queries |
|---|---|---:|---:|---:|
| bm25 | nDCG@10 | 0.2326 | [0.2108, 0.2568] | 648 |
| bm25 | Recall@10 | 0.2955 | [0.2684, 0.3241] | 648 |
| bm25 | Recall@100 | 0.5150 | [0.4817, 0.5458] | 648 |
| bm25 | MRR@10 | 0.2875 | [0.2554, 0.3173] | 648 |
| dense_bge_small | nDCG@10 | 0.3848 | [0.3561, 0.4123] | 648 |
| dense_bge_small | Recall@10 | 0.4396 | [0.4084, 0.4714] | 648 |
| dense_bge_small | Recall@100 | 0.6866 | [0.6570, 0.7147] | 648 |
| dense_bge_small | MRR@10 | 0.4650 | [0.4319, 0.5003] | 648 |
| hybrid_rrf | nDCG@10 | 0.3436 | [0.3170, 0.3702] | 648 |
| hybrid_rrf | Recall@10 | 0.4170 | [0.3871, 0.4478] | 648 |
| hybrid_rrf | Recall@100 | 0.6805 | [0.6528, 0.7097] | 648 |
| hybrid_rrf | MRR@10 | 0.4164 | [0.3844, 0.4487] | 648 |
| hybrid_rrf_rerank | nDCG@10 | 0.3731 | [0.3440, 0.4013] | 648 |
| hybrid_rrf_rerank | Recall@10 | 0.4508 | [0.4216, 0.4836] | 648 |
| hybrid_rrf_rerank | Recall@100 | 0.6805 | [0.6504, 0.7081] | 648 |
| hybrid_rrf_rerank | MRR@10 | 0.4432 | [0.4103, 0.4771] | 648 |

## Stage latency

| Variant | Stage | P50 (ms) | P95 (ms) | Samples |
|---|---|---:|---:|---:|
| bm25 | hydrate_results | 7.38 | 10.70 | 648 |
| bm25 | sparse_retrieve | 2.19 | 3.84 | 648 |
| dense_bge_small | dense_embed_query | 14.62 | 25.79 | 648 |
| dense_bge_small | dense_retrieve | 44.46 | 67.26 | 648 |
| dense_bge_small | hydrate_results | 6.19 | 10.94 | 648 |
| hybrid_rrf | dense_embed_query | 13.83 | 23.79 | 648 |
| hybrid_rrf | dense_retrieve | 37.70 | 64.69 | 648 |
| hybrid_rrf | fuse | 0.32 | 0.52 | 648 |
| hybrid_rrf | hydrate_results | 5.71 | 10.58 | 648 |
| hybrid_rrf | sparse_retrieve | 2.02 | 3.20 | 648 |
| hybrid_rrf_rerank | dense_embed_query | 13.58 | 23.93 | 648 |
| hybrid_rrf_rerank | dense_retrieve | 37.17 | 64.04 | 648 |
| hybrid_rrf_rerank | fuse | 0.32 | 0.55 | 648 |
| hybrid_rrf_rerank | hydrate_results | 9.41 | 11.73 | 648 |
| hybrid_rrf_rerank | rerank | 1714.08 | 3112.42 | 648 |
| hybrid_rrf_rerank | sparse_retrieve | 1.97 | 3.22 | 648 |

## Variant comparisons

Paired bootstrap over queries. A difference is significant only when its
95% interval excludes zero.

| Variant A | Variant B | Metric | A - B | 95% CI | Significant |
|---|---|---|---:|---:|---|
| bm25 | dense_bge_small | nDCG@10 | -0.1522 | [-0.1777, -0.1300] | yes |
| bm25 | dense_bge_small | Recall@10 | -0.1441 | [-0.1735, -0.1158] | yes |
| bm25 | dense_bge_small | Recall@100 | -0.1716 | [-0.2009, -0.1399] | yes |
| bm25 | dense_bge_small | MRR@10 | -0.1776 | [-0.2105, -0.1468] | yes |
| bm25 | hybrid_rrf | nDCG@10 | -0.1110 | [-0.1275, -0.0953] | yes |
| bm25 | hybrid_rrf | Recall@10 | -0.1215 | [-0.1449, -0.0995] | yes |
| bm25 | hybrid_rrf | Recall@100 | -0.1655 | [-0.1914, -0.1408] | yes |
| bm25 | hybrid_rrf | MRR@10 | -0.1290 | [-0.1519, -0.1063] | yes |
| bm25 | hybrid_rrf_rerank | nDCG@10 | -0.1405 | [-0.1619, -0.1208] | yes |
| bm25 | hybrid_rrf_rerank | Recall@10 | -0.1552 | [-0.1806, -0.1309] | yes |
| bm25 | hybrid_rrf_rerank | Recall@100 | -0.1655 | [-0.1920, -0.1413] | yes |
| bm25 | hybrid_rrf_rerank | MRR@10 | -0.1557 | [-0.1841, -0.1280] | yes |
| dense_bge_small | hybrid_rrf | nDCG@10 | +0.0412 | [+0.0246, +0.0597] | yes |
| dense_bge_small | hybrid_rrf | Recall@10 | +0.0226 | [-0.0013, +0.0455] | no |
| dense_bge_small | hybrid_rrf | Recall@100 | +0.0060 | [-0.0109, +0.0250] | no |
| dense_bge_small | hybrid_rrf | MRR@10 | +0.0486 | [+0.0253, +0.0743] | yes |
| dense_bge_small | hybrid_rrf_rerank | nDCG@10 | +0.0117 | [-0.0064, +0.0304] | no |
| dense_bge_small | hybrid_rrf_rerank | Recall@10 | -0.0111 | [-0.0325, +0.0112] | no |
| dense_bge_small | hybrid_rrf_rerank | Recall@100 | +0.0060 | [-0.0122, +0.0227] | no |
| dense_bge_small | hybrid_rrf_rerank | MRR@10 | +0.0218 | [-0.0035, +0.0461] | no |
| hybrid_rrf | hybrid_rrf_rerank | nDCG@10 | -0.0295 | [-0.0459, -0.0129] | yes |
| hybrid_rrf | hybrid_rrf_rerank | Recall@10 | -0.0338 | [-0.0553, -0.0131] | yes |
| hybrid_rrf | hybrid_rrf_rerank | Recall@100 | +0.0000 | [+0.0000, +0.0000] | no |
| hybrid_rrf | hybrid_rrf_rerank | MRR@10 | -0.0268 | [-0.0513, -0.0027] | yes |
