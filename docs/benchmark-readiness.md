# Pretrained benchmark readiness

A pretrained BioCLIP benchmark requires a frozen, reviewed corpus, documented event/specimen/duplicate grouping, and a scientifically meaningful evaluation design. No training or fine-tuning is permitted through this gate.

The current governed inventory has one target taxon and three human-approved assets. Seven additional assets contain provider evidence but still require human taxonomy confirmation. A one-taxon positive-only set cannot measure multiclass discrimination or open-set rejection. Therefore the current decisions are:

- `PRETRAINED_BENCHMARK_NOT_JUSTIFIED`
- `OPEN_SET_NOT_EVALUATED`
- `SPLIT_NOT_RECOMMENDED`

No accuracy or rejection threshold should be reported until independent governed taxa and negative/open-set controls exist.
