# Provider media adapter

`GBIFMediaAdapter` queries GBIF API v1 by governed taxon key and `StillImage`, paginates with a bounded page size, caps a run at 25 records, uses timeouts and exponential retry for transient errors, and delays between pages. It emits provider-neutral candidate dictionaries and a canonical run manifest.

Downloads are streamed with a 15 MB default ceiling. Content is subsequently decoded by Pillow; declared and decoded formats, dimensions, aspect ratio, and configurable minimum dimensions are validated. SHA-256 and dHash-64 are calculated before an asset is reviewable. Provider errors fail the item/run without broadening rights or labels.

GBIF media license strings are retained verbatim and normalized conservatively. Unknown values map to `LICENSE_UNRESOLVED`.
