# Visual corpus review

Platform administrators review each candidate in the Scientific Readiness visual-corpus workspace. The workspace exposes source, acquisition state, controlled thumbnail, creator, attribution, license, dimensions, context, taxonomy, quality, and duplicate state.

Approval requires an active governed source, an approved regional taxon, exact/supported taxonomic linkage, a technically valid image, an explicitly eligible license, and a distinct duplicate state. Reviewers may exclude a candidate but cannot expand provider license rights. Every decision creates an append-only review event containing the before/after state and concise reference.

Exact duplicates use SHA-256. Likely duplicates use dHash-64 distance with the configured review threshold (6); they are retained for inspection and cannot be approved until resolved. Provider event/specimen and perceptual groups remain together during splitting.
