# Retrieval dataset card

The application downloads the upstream BEIR archives at ingestion time and does not redistribute
their corpus content. `config/datasets.yaml` pins the archive URL and checksum used for each run;
the ingestion report records the resulting content hash and index fingerprint.

| Dataset | Domain | Test queries | Corpus documents | Upstream terms recorded by `ragops` |
|---|---|---:|---:|---|
| SciFact | Scientific claim verification | 300 | 5,183 | Corpus: ODC-By 1.0; claims and annotations: CC BY 4.0 |
| NFCorpus | Nutrition and medicine | 323 | 3,633 | CC BY-SA 4.0 |
| FiQA-2018 | Financial opinion question answering | 648 | 57,638 | Non-commercial research use |

Counts are for the checksum-pinned BEIR snapshots and are confirmed by ingestion rather than used
as loader assumptions. FiQA contains 38 empty corpus records in the upstream archive, including one
referenced by the test qrels. They are retained unchanged so document identifiers, corpus size, and
relevance judgments remain faithful to the benchmark.

These labels summarize upstream terms for experiment provenance and are not legal advice. Review
the original dataset terms before redistributing data or using it outside this evaluation project.
