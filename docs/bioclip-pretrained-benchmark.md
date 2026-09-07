# Pretrained BioCLIP benchmark contract

Benchmark preparation accepts only a frozen, reviewed corpus. Runs bind the exact model identity/version/hash when available, corpus fingerprint, split, preprocessing, and candidate-label configuration. Completion stores descriptive top-k, per-taxon/group, confusion, score/margin, provider, and reviewed-context results where available. Similarity scores are not calibrated probabilities, and no production threshold is invented.

Completed benchmark rows are immutable. Benchmarking never trains, fine-tunes, promotes a model, or creates occurrence/ecological/anomaly evidence. The present reviewed corpus is empty, so the current decision is `PRETRAINED_BENCHMARK_NOT_JUSTIFIED`.
