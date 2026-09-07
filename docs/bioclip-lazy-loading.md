# BioCLIP lazy loading

API import now constructs a lightweight `LazyMarineObservationService`, not BioCLIP. The real observation service, OpenCLIP runtime, reference embeddings, and model are imported and initialized only on the first identification inference call.

Initialization is guarded by a process-local lock. Concurrent first calls construct exactly one instance. Health checks, migrations, backups, taxonomy administration, corpus review, and non-inference tests therefore do not initialize BioCLIP.
