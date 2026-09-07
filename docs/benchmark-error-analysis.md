# Benchmark error-analysis contract

For each error, preserve true/predicted governed taxon, taxonomic group, genus/family relationship when available, provider, source-event group, specimen/in-situ context, reviewed life stage/orientation, image quality, similarity score, and score margin.

Reports summarize confusion pairs, source bias, same-genus/family errors, context differences, weak taxa, and missing diversity. Missing biological metadata remains `UNKNOWN`; it is not inferred from filenames or pixels. Open-set evaluation remains a separate cohort and does not establish a production rejection threshold automatically.
