# Buildathon demo walkthrough

## Three-to-five-minute path

1. **Regional overview (30 seconds).** Open `/region/caribbean`. Explain that the map is a regional operational view, while scientific deployments remain jurisdiction scoped. Point to the governed workflow: Report → Identify → Verify → Govern → Map → Assess → Review.
2. **Jamaica monitoring (45 seconds).** Enter Jamaica, open the map, and show verified sightings, observation hotspots, relative habitat suitability, and monitoring-priority layers. State that suitability is neither occurrence probability nor spread probability.
3. **Observation review (45 seconds).** Open the review queue. Show submitted evidence, AI-supported identification, human verification controls, duplicate handling, jurisdiction authorization, and the append-only audit history.
4. **Governed visual corpus (60 seconds).** Sign in as a platform administrator, open Scientific Readiness → Visual Corpus, then Taxonomy review. Show source attribution, licensing, provider evidence, the original provider link, and the mandatory-reason human resolution actions. Do not resolve production assets during a rehearsed demo.
5. **Multi-taxon scaling (45 seconds).** Open Regional Taxonomy → Manifests and explain the prepared six-group, 25-taxon WoRMS candidate set. Emphasize that preparation is not approval and regional taxonomy is not jurisdiction presence or invasive status.
6. **Close (30 seconds).** Return to the public jurisdiction directory. Point out transparent empty states: the product does not fill scientific gaps with inferred claims.

## Safe demo language

- Say “AI-supported identification,” not “AI-confirmed species.”
- Say “relative habitat suitability,” not probability.
- Say “monitoring priority,” not ecological severity.
- Say “candidate taxon awaiting human review,” not onboarded species.
- Say “no governed assertion is available,” not absence from the ecosystem.

## Recovery

If a network-backed map or API is unavailable, use the visible empty/error state and explain the firewall. Do not edit production data to make a screen look populated. Use `bootstrap_demo.py` only against an explicitly isolated DEMO database.

