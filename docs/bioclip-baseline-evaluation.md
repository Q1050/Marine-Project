# Pretrained BioCLIP baseline evaluation

The baseline is a closed candidate-label evaluation over governed benchmark taxa. It performs no training or fine-tuning. A run must bind model/checkpoint identity, runtime version, preprocessing, device, candidate taxonomy version, frozen corpus fingerprint, and inference configuration.

The quality gate requires a frozen corpus, human-approved licensed and technically valid assets, and deterministic source/duplicate grouping. Metrics may include top-1/3/5, macro and per-taxon/group results, confusion pairs, score/margin distributions, and genus/family correctness when governed lineage supports it. Similarity scores are not probabilities.

No benchmark is justified while approved assets and multi-taxon breadth are absent.
