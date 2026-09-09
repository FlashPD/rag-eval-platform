# Retrieval evaluation `2d9f6192-1704-4b4a-908d-3508b1fa04bd`

- Dataset: `nfcorpus` (`test`)
- Variants: `bm25`, `dense_bge_small`, `hybrid_rrf`, `hybrid_rrf_rerank`
- Seed: `42`
- Results: `1292`
- Indexes: `bm25`=`e753dd39de1e9945bace0ab21356441c697d5bc2a160df4da0d55638f95f9d8b`, `dense_bge_small`=`e753dd39de1e9945bace0ab21356441c697d5bc2a160df4da0d55638f95f9d8b`, `hybrid_rrf`=`e753dd39de1e9945bace0ab21356441c697d5bc2a160df4da0d55638f95f9d8b`, `hybrid_rrf_rerank`=`e753dd39de1e9945bace0ab21356441c697d5bc2a160df4da0d55638f95f9d8b`

## Retrieval quality

| Variant | Metric | Mean | 95% CI | Queries |
|---|---|---:|---:|---:|
| bm25 | nDCG@10 | 0.3064 | [0.2720, 0.3419] | 323 |
| bm25 | Recall@10 | 0.1450 | [0.1205, 0.1703] | 323 |
| bm25 | Recall@100 | 0.2416 | [0.2128, 0.2704] | 323 |
| bm25 | MRR@10 | 0.5186 | [0.4665, 0.5665] | 323 |
| dense_bge_small | nDCG@10 | 0.3375 | [0.3044, 0.3725] | 323 |
| dense_bge_small | Recall@10 | 0.1580 | [0.1337, 0.1827] | 323 |
| dense_bge_small | Recall@100 | 0.3059 | [0.2771, 0.3365] | 323 |
| dense_bge_small | MRR@10 | 0.5299 | [0.4817, 0.5770] | 323 |
| hybrid_rrf | nDCG@10 | 0.3444 | [0.3090, 0.3781] | 323 |
| hybrid_rrf | Recall@10 | 0.1622 | [0.1363, 0.1888] | 323 |
| hybrid_rrf | Recall@100 | 0.3103 | [0.2797, 0.3409] | 323 |
| hybrid_rrf | MRR@10 | 0.5620 | [0.5154, 0.6094] | 323 |
| hybrid_rrf_rerank | nDCG@10 | 0.3591 | [0.3219, 0.3959] | 323 |
| hybrid_rrf_rerank | Recall@10 | 0.1679 | [0.1422, 0.1944] | 323 |
| hybrid_rrf_rerank | Recall@100 | 0.3103 | [0.2806, 0.3393] | 323 |
| hybrid_rrf_rerank | MRR@10 | 0.5859 | [0.5379, 0.6342] | 323 |

## Stage latency

| Variant | Stage | P50 (ms) | P95 (ms) | Samples |
|---|---|---:|---:|---:|
| bm25 | hydrate_results | 7.07 | 9.42 | 323 |
| bm25 | sparse_retrieve | 1.36 | 1.57 | 323 |
| dense_bge_small | dense_embed_query | 14.00 | 15.76 | 323 |
| dense_bge_small | dense_retrieve | 16.04 | 18.11 | 323 |
| dense_bge_small | hydrate_results | 6.34 | 7.44 | 323 |
| hybrid_rrf | dense_embed_query | 14.27 | 15.30 | 323 |
| hybrid_rrf | dense_retrieve | 15.48 | 17.28 | 323 |
| hybrid_rrf | fuse | 0.32 | 0.37 | 323 |
| hybrid_rrf | hydrate_results | 5.99 | 7.22 | 323 |
| hybrid_rrf | sparse_retrieve | 1.34 | 1.45 | 323 |
| hybrid_rrf_rerank | dense_embed_query | 13.34 | 14.76 | 323 |
| hybrid_rrf_rerank | dense_retrieve | 14.60 | 16.51 | 323 |
| hybrid_rrf_rerank | fuse | 0.31 | 0.35 | 323 |
| hybrid_rrf_rerank | hydrate_results | 10.51 | 12.11 | 323 |
| hybrid_rrf_rerank | rerank | 1982.38 | 2290.72 | 323 |
| hybrid_rrf_rerank | sparse_retrieve | 1.21 | 1.37 | 323 |

## Variant comparisons

Paired bootstrap over queries. A difference is significant only when its
95% interval excludes zero.

| Variant A | Variant B | Metric | A - B | 95% CI | Significant |
|---|---|---|---:|---:|---|
| bm25 | dense_bge_small | nDCG@10 | -0.0311 | [-0.0535, -0.0089] | yes |
| bm25 | dense_bge_small | Recall@10 | -0.0130 | [-0.0292, +0.0023] | no |
| bm25 | dense_bge_small | Recall@100 | -0.0643 | [-0.0874, -0.0423] | yes |
| bm25 | dense_bge_small | MRR@10 | -0.0113 | [-0.0509, +0.0331] | no |
| bm25 | hybrid_rrf | nDCG@10 | -0.0380 | [-0.0521, -0.0249] | yes |
| bm25 | hybrid_rrf | Recall@10 | -0.0171 | [-0.0289, -0.0073] | yes |
| bm25 | hybrid_rrf | Recall@100 | -0.0687 | [-0.0856, -0.0517] | yes |
| bm25 | hybrid_rrf | MRR@10 | -0.0434 | [-0.0693, -0.0184] | yes |
| bm25 | hybrid_rrf_rerank | nDCG@10 | -0.0527 | [-0.0707, -0.0366] | yes |
| bm25 | hybrid_rrf_rerank | Recall@10 | -0.0229 | [-0.0366, -0.0117] | yes |
| bm25 | hybrid_rrf_rerank | Recall@100 | -0.0687 | [-0.0863, -0.0502] | yes |
| bm25 | hybrid_rrf_rerank | MRR@10 | -0.0673 | [-0.0991, -0.0363] | yes |
| dense_bge_small | hybrid_rrf | nDCG@10 | -0.0069 | [-0.0223, +0.0086] | no |
| dense_bge_small | hybrid_rrf | Recall@10 | -0.0041 | [-0.0156, +0.0058] | no |
| dense_bge_small | hybrid_rrf | Recall@100 | -0.0043 | [-0.0150, +0.0084] | no |
| dense_bge_small | hybrid_rrf | MRR@10 | -0.0321 | [-0.0616, -0.0008] | yes |
| dense_bge_small | hybrid_rrf_rerank | nDCG@10 | -0.0216 | [-0.0392, -0.0044] | yes |
| dense_bge_small | hybrid_rrf_rerank | Recall@10 | -0.0099 | [-0.0234, +0.0037] | no |
| dense_bge_small | hybrid_rrf_rerank | Recall@100 | -0.0043 | [-0.0153, +0.0066] | no |
| dense_bge_small | hybrid_rrf_rerank | MRR@10 | -0.0560 | [-0.0879, -0.0227] | yes |
| hybrid_rrf | hybrid_rrf_rerank | nDCG@10 | -0.0147 | [-0.0291, -0.0004] | yes |
| hybrid_rrf | hybrid_rrf_rerank | Recall@10 | -0.0058 | [-0.0176, +0.0052] | no |
| hybrid_rrf | hybrid_rrf_rerank | Recall@100 | +0.0000 | [+0.0000, +0.0000] | no |
| hybrid_rrf | hybrid_rrf_rerank | MRR@10 | -0.0239 | [-0.0534, +0.0037] | no |
