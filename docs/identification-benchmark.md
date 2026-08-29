# Identification benchmark contract

A benchmark is prepared only against a frozen identification corpus. Its immutable dependency fingerprint covers model identity, model hash/version, corpus identity, split, and inference configuration.

The result contract can preserve top-1, top-k, per-taxon results, confusion data, unknown/rejection behavior, timestamp, and reproducibility metadata. Preparation does not execute BioCLIP, fine-tune a model, or infer ecological facts. `NOT_READY`, `BENCHMARK_READY`, `TRAINING_REVIEW_REQUIRED`, and `TRAINING_READY` are readiness states with reasons, not claims of model quality.
