# Agency pilot runbook

## Start the prototype

From the repository root, activate the existing virtual environment and run the backend with `uvicorn api:app --reload`. From `marine-monitoring-frontend`, run `npm install` when needed and then `npm run dev`.

Configure only the normal non-secret database/frontend environment required by the repository. Never place passwords, session tokens, or reporter response tokens in documentation or source control.

## Provision a tester

1. Sign in as a platform administrator.
2. Open **Users** and create or select the real tester account. Temporary passwords must be transferred through an approved secure channel.
3. Open **Reviewer access**.
4. Select the user and Jamaica, record the institutional pilot reference, and grant access.
5. Ask the tester to sign in and open **Monitoring home**. They will not receive the taxonomy, model, ecological-status, or other platform-administration interfaces.
6. After the pilot, revoke the jurisdiction grant. Deactivate the account when it is no longer needed.

Do not create fictitious agency accounts in the production database.

## Pilot workflow

1. Open the Jamaica public monitoring pages and select **Submit sighting**.
2. Upload a supported image, select the actual sighting location, and submit.
3. Retain the opaque submission reference/status link shown by the submission response. AI assistance is preliminary.
4. Sign in as the Jamaica reviewer and open **Observation Review**.
5. Use **Unassigned** and claim the case, or select an authorized reviewer from the assignment control.
6. Inspect the submitted image, coordinates, reporter suggestion, AI suggestion, duplicate context, and operational history.
7. Confirm, correct, reject, or leave the identification unresolved. Operational priority is not ecological severity.
8. When more evidence is needed, request additional information. The returned reporter response link is private and expires.
9. Close only a case with an authorized final disposition.
10. Submit pilot feedback from **Monitoring home**.

## Scientific limitations

- AI suggestions are not expert verification.
- Occurrence does not establish native, non-native, invasive, or established status.
- Suitability does not confirm presence and is not spread probability.
- Verification does not automatically create governed occurrence evidence.
- Unusual reports are not automatically ecological anomalies.
- The public invasive directory contains only current approved governed assertions; legacy-unverified values remain excluded.

## Troubleshooting

- **Invalid login:** confirm the user is active and use the current temporary/password credential.
- **No reviewer workspace:** confirm an active jurisdiction reviewer grant exists.
- **403 on a case:** the case belongs to a jurisdiction not granted to that reviewer.
- **Empty queue:** confirm jurisdiction scope and filters; no cases is a valid state.
- **Image unavailable:** confirm authorization and that the retained observation file exists.
- **Expired reporter link:** issue a new additional-information request; never copy tokens into logs.
- **Notification retryable:** external delivery is deliberately disabled until a provider is configured; inspect the admin notification outbox.
- **Empty invasive directory:** this is valid when no authoritative governed ecological assertion exists.

## 10–15 minute pre-handoff browser rehearsal

1. Open `/regions`, Caribbean, Jamaica, the marine-species directory, and a species detail/map page. Confirm private observation images show a neutral fallback publicly.
2. Submit one clearly labelled disposable Jamaica test sighting. Record its opaque reference and private status link.
3. Sign in as the purpose-created Jamaica reviewer and open `/reviewer`. Confirm no scientific/admin navigation appears.
4. Open `/admin/observations`, choose **Unassigned**, and claim the test case.
5. Confirm the protected image, coordinates, reporter suggestion, and AI assistance load.
6. Request additional information. Copy the displayed private link/message and open it in a separate private browser window.
7. Submit reporter follow-up information and verify reusing the link is refused.
8. Refresh the reviewer case, confirm the response appears, then confirm or correct the identification.
9. Close the case with a reason and verify the ordered audit history. Reopen once, verify the event, then close it again.
10. Submit pilot feedback from `/reviewer`.
11. As platform admin, inspect Reviewer Access, pilot feedback/activity/readiness, and notification state.
12. Confirm a Barbados-only or revoked reviewer receives an understandable access refusal for the Jamaica case and image.

## Pilot cleanup

- Revoke the tester's jurisdiction reviewer grant; deactivate the user account if the relationship has ended.
- Revoke or allow expiry of reporter tokens. Issuing a replacement response link revokes older active response links.
- Preserve operational audit events and feedback. Do not delete them to make the pilot look clean.
- Delete only disposable test observations through an explicitly approved test-data process; never use bulk reset against production.
- Do not delete or modify historical occurrences, governed evidence, ecological assertions, taxonomy, datasets, deployments, training runs, or anomaly records during cleanup.
- Keep a written list of disposable pilot observation references so test activity remains distinguishable from production reports.
