import { useEffect, useMemo, useState } from "react";
import {
  getImageUrl,
  getObservation,
  getReviewQueue,
  verifyObservation,
} from "../services/api";
import { useJurisdiction } from "../geography/JurisdictionContext";

const DECISION_LABELS = {
  KNOWN_INVASIVE_RECORD: "Known invasive report requiring verification",
  UNRESOLVED_IDENTIFICATION: "AI identification could not be resolved",
  SPECIES_LEVEL_ANOMALY: "Potential species-level anomaly",
  TAXONOMIC_ANOMALY: "Potential taxonomic anomaly",
  HIGH_PRIORITY_REVIEW: "High-priority report",
};

const ACTIONS = [
  ["CONFIRMED", "Confirm identification"],
  ["CORRECTED", "Correct identification"],
  ["NEEDS_MORE_REVIEW", "Needs more review"],
  ["REJECTED", "Reject report"],
];

export default function ReviewPage({ onObservationUpdated }) {
  const { activeRegion, activeJurisdiction, jurisdiction: metadata } = useJurisdiction();
  const scope = useMemo(() => ({ region: activeRegion, jurisdiction: activeJurisdiction }), [activeRegion, activeJurisdiction]);
  const [queue, setQueue] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [observation, setObservation] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [detailError, setDetailError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [status, setStatus] = useState("CONFIRMED");
  const [verifiedSpecies, setVerifiedSpecies] = useState("");
  const [notes, setNotes] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [reasonFilter, setReasonFilter] = useState("ALL");
  const [search, setSearch] = useState("");

  async function loadQueue() {
    try {
      setLoading(true);
      setError(null);
      const data = await getReviewQueue(scope);
      setQueue(data.queue || []);
    } catch (requestError) {
      setError(requestError.message || "Unable to load the review queue.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    getReviewQueue(scope)
      .then((data) => {
        if (active) setQueue(data.queue || []);
      })
      .catch((requestError) => {
        if (active)
          setError(requestError.message || "Unable to load the review queue.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [scope]);

  async function selectObservation(id, preserveSuccess = false) {
    try {
      setSelectedId(id);
      setDetailsLoading(true);
      setDetailError(null);
      if (!preserveSuccess) setSuccess(null);
      setObservation(null);
      const data = await getObservation(id);
      setObservation(data);
      const aiSpecies = data.identification?.species || "";
      setVerifiedSpecies(aiSpecies);
      setStatus(aiSpecies ? "CONFIRMED" : "CORRECTED");
      setNotes("");
    } catch {
      setDetailError(
        "Unable to load this observation. The queue remains available.",
      );
    } finally {
      setDetailsLoading(false);
    }
  }

  async function handleVerification(event) {
    event.preventDefault();
    if (!selectedId) return;
    if (
      ["CONFIRMED", "CORRECTED"].includes(status) &&
      !verifiedSpecies.trim()
    ) {
      setDetailError("A verified species is required for this decision.");
      return;
    }
    if (
      status === "REJECTED" &&
      !window.confirm("Reject this submitted report?")
    )
      return;
    try {
      setSubmitting(true);
      setDetailError(null);
      await verifyObservation(selectedId, {
        status,
        verified_species: verifiedSpecies.trim() || null,
        notes: notes.trim() || null,
      });
      onObservationUpdated?.();
      const remaining = queue.filter((item) => item.id !== selectedId);
      setQueue(remaining);
      setSuccess(actionSuccessLabel(status));
      setSelectedId(null);
      setObservation(null);
      setVerifiedSpecies("");
      setNotes("");
      if (remaining.length > 0) await selectObservation(remaining[0].id, true);
    } catch (requestError) {
      setDetailError(requestError.message || "Verification failed.");
    } finally {
      setSubmitting(false);
    }
  }

  const filteredQueue = useMemo(
    () =>
      queue.filter((item) => {
        const verification =
          item.verification_status || item.status || "PENDING";
        if (statusFilter !== "ALL" && verification !== statusFilter)
          return false;
        if (!matchesReason(item, reasonFilter)) return false;
        return (
          !search ||
          `${item.species || item.ai_species || ""} ${item.id}`
            .toLowerCase()
            .includes(search.toLowerCase())
        );
      }),
    [queue, reasonFilter, search, statusFilter],
  );

  const duplicates = queue.filter((item) => item.is_possible_duplicate).length;
  const highPriority = queue.filter((item) => item.priority === "HIGH").length;

  return (
    <div className="-m-4 h-[calc(100vh-137px)] min-h-[620px] overflow-hidden sm:-m-6 lg:-m-8 lg:h-[calc(100vh-64px)]">
      <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[minmax(280px,30%)_minmax(0,1fr)] xl:grid-cols-[minmax(300px,29%)_minmax(0,1fr)]">
        <aside
          className={`${selectedId ? "hidden lg:flex" : "flex"} min-h-0 min-w-0 w-full flex-col overflow-hidden border-r border-app-border bg-white`}
          aria-label="Reports awaiting expert review"
        >
          <div className="sticky top-0 z-10 space-y-3 border-b border-app-border bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h1 className="text-lg font-bold">Review queue</h1>
                <p className="mt-0.5 text-xs text-app-muted">
                  Reports requiring expert verification in {metadata?.name || "this jurisdiction"}.
                </p>
              </div>
              <span className="shrink-0 rounded-full bg-teal-100 px-2.5 py-1 text-xs font-bold text-teal-700">
                {queue.length} reports
              </span>
            </div>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              aria-label="Search review queue"
              placeholder="Search reports…"
              className="w-full rounded-lg border border-app-border px-3 py-2 text-sm"
            />
            <div className="grid grid-cols-2 gap-2">
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
                className="min-w-0 rounded-lg border border-app-border px-2 py-2 text-xs"
                aria-label="Filter by verification status"
              >
                <option value="ALL">All awaiting</option>
                <option value="PENDING">Pending</option>
                <option value="NEEDS_MORE_REVIEW">Needs more review</option>
              </select>
              <select
                value={reasonFilter}
                onChange={(event) => setReasonFilter(event.target.value)}
                className="min-w-0 rounded-lg border border-app-border px-2 py-2 text-xs"
                aria-label="Filter by review reason"
              >
                <option value="ALL">All reasons</option>
                <option value="INVASIVE">Invasive reports</option>
                <option value="UNRESOLVED">Unresolved</option>
                <option value="ANOMALY">Anomalies</option>
                <option value="HIGH">High priority</option>
                <option value="DUPLICATE">Possible duplicates</option>
              </select>
            </div>
            <div className="flex gap-2 text-[10px] text-app-muted">
              <span>{duplicates} possible duplicates</span>
              <span>·</span>
              <span>{highPriority} high priority</span>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {loading ? (
              <QueueMessage>Loading reports…</QueueMessage>
            ) : error ? (
              <QueueMessage>
                <span className="text-red-700">{error}</span>
                <button
                  onClick={loadQueue}
                  className="mt-3 block w-full rounded-lg border border-app-border px-3 py-2 font-bold text-teal-700"
                >
                  Retry
                </button>
              </QueueMessage>
            ) : filteredQueue.length === 0 ? (
              <QueueMessage>
                No reports currently require expert review.
              </QueueMessage>
            ) : (
              filteredQueue.map((item) => (
                <QueueItem
                  key={item.id}
                  item={item}
                  selected={selectedId === item.id}
                  onSelect={() => selectObservation(item.id)}
                />
              ))
            )}
          </div>
        </aside>
        <main
          className={`${selectedId ? "block" : "hidden lg:block"} min-h-0 min-w-0 overflow-y-auto bg-surface-subtle`}
          aria-label="Selected observation review workspace"
        >
          {selectedId && (
            <button
              onClick={() => {
                setSelectedId(null);
                setObservation(null);
              }}
              className="m-3 hidden rounded-lg border border-app-border bg-white px-3 py-2 text-sm font-bold text-teal-700 md:block lg:hidden"
            >
              ← Back to queue
            </button>
          )}
          {selectedId && (
            <button
              onClick={() => {
                setSelectedId(null);
                setObservation(null);
              }}
              className="m-3 rounded-lg border border-app-border bg-white px-3 py-2 text-sm font-bold text-teal-700 md:hidden"
            >
              ← Back to queue
            </button>
          )}
          {!selectedId && !detailsLoading && (
            <div className="grid h-full place-items-center p-8 text-center">
              <div>
                <span className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-teal-100 text-teal-700">
                  ✓
                </span>
                <h2 className="mt-4 text-lg font-bold">Expert verification</h2>
                <p className="mt-2 text-sm text-app-muted">
                  Select a report to inspect its image and supporting evidence.
                </p>
              </div>
            </div>
          )}
          {detailsLoading && (
            <div className="grid h-full place-items-center text-app-muted">
              Loading submitted observation…
            </div>
          )}
          {detailError && !observation && (
            <div className="m-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {detailError}
            </div>
          )}
          {observation && (
            <ReviewWorkspace
              observation={observation}
              status={status}
              setStatus={setStatus}
              verifiedSpecies={verifiedSpecies}
              setVerifiedSpecies={setVerifiedSpecies}
              notes={notes}
              setNotes={setNotes}
              submitting={submitting}
              error={detailError}
              success={success}
              onSubmit={handleVerification}
            />
          )}
        </main>
      </div>
    </div>
  );
}

function QueueItem({ item, selected, onSelect }) {
  const species = item.species || item.ai_species || "Unresolved observation";
  return (
    <button
      onClick={onSelect}
      className={`mb-1.5 grid w-full grid-cols-[52px_minmax(0,1fr)] gap-3 rounded-xl border p-2.5 text-left transition ${selected ? "border-teal-600 bg-teal-50 shadow-sm" : "border-transparent hover:border-app-border hover:bg-slate-50"}`}
    >
      <Thumbnail url={item.image_url} />
      <div className="min-w-0">
        <div className="flex items-start justify-between gap-2">
          <strong className="truncate text-sm">{species}</strong>
          {item.priority === "HIGH" && <Badge tone="danger">High</Badge>}
        </div>
        <span className="block text-xs text-app-muted">
          Observation #{item.id}
          {item.created_at ? ` · ${formatTimestamp(item.created_at)}` : ""}
        </span>
        <span className="mt-1 block truncate text-xs">
          {DECISION_LABELS[item.decision] ||
            readable(
              item.decision || item.verification_status || "Pending review",
            )}
        </span>
        <div className="mt-1.5 flex flex-wrap gap-1">
          <Badge>{readable(item.verification_status || "PENDING")}</Badge>
          {item.is_possible_duplicate && (
            <Badge tone="warning">Possible duplicate</Badge>
          )}
        </div>
      </div>
    </button>
  );
}

function ReviewWorkspace({
  observation,
  status,
  setStatus,
  verifiedSpecies,
  setVerifiedSpecies,
  notes,
  setNotes,
  submitting,
  error,
  success,
  onSubmit,
}) {
  const { jurisdiction: metadata } = useJurisdiction();
  const identification = observation.identification || {};
  const record = observation.observation || {};
  const verification = observation.verification || {};
  const regional = observation.regional_evidence;
  return (
    <div className="mx-auto max-w-[1500px] p-4 lg:p-5">
      <div className="mb-4 flex items-start justify-between gap-4 border-b border-app-border pb-4">
        <div>
          <span className="text-[11px] font-bold uppercase tracking-[.13em] text-teal-700">
            Observation #{record.id} · {metadata?.name || "Jurisdiction"}
          </span>
          <h2 className="mt-1 text-2xl font-bold tracking-tight">
            {identification.species || "Unresolved observation"}
          </h2>
        </div>
        <Badge tone={observation.priority === "HIGH" ? "danger" : "neutral"}>
          {readable(
            verification.status ||
              observation.verification_status ||
              "Pending expert review",
          )}
        </Badge>
      </div>
      <section className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(280px,.7fr)]">
        <LargeImage url={record.image_url} species={identification.species} />
        <div className="rounded-xl border border-teal-200 bg-teal-50/40 p-4 xl:sticky xl:top-4">
          <SectionLabel>AI identification</SectionLabel>
          <h3 className="mt-2 text-xl font-bold">
            {identification.species ||
              identification.nearest_candidate ||
              "Unresolved"}
          </h3>
          <Metric
            label="AI identification score"
            value={formatScore(identification.score)}
          />
          <Metric
            label="Candidate margin"
            value={formatScore(identification.margin)}
          />
          <div className="mt-5 border-t border-teal-200 pt-4">
            <SectionLabel>Assessment</SectionLabel>
            <Metric
              label="Ecological status"
              value={readable(observation.ecological_status)}
            />
            <Metric label="Decision" value={readable(observation.decision)} />
            <Metric
              label="Current verification status"
              value={readable(
                verification.status ||
                  observation.verification_status ||
                  "PENDING",
              )}
            />
            {verification.verified_at && (
              <Metric
                label="Last verification action"
                value={formatTimestamp(verification.verified_at)}
              />
            )}
          </div>
        </div>
      </section>
      <section className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(280px,.7fr)]">
        <div className="rounded-2xl border border-app-border bg-white p-5">
          <SectionLabel>Why this needs review</SectionLabel>
          <p className="mt-2 font-semibold">
            {DECISION_LABELS[observation.decision] ||
              observation.reason ||
              readable(observation.decision || "Expert attention required")}
          </p>
          {observation.reason && (
            <p className="mt-2 text-sm leading-6 text-app-muted">
              {observation.reason}
            </p>
          )}
          {observation.is_possible_duplicate && (
            <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4">
              <strong className="text-amber-900">Possible duplicate</strong>
              <p className="mt-1 text-sm text-amber-800">
                This report may duplicate{" "}
                {observation.duplicate_of_observation_id
                  ? `Observation #${observation.duplicate_of_observation_id}`
                  : "another submitted observation"}
                .
              </p>
            </div>
          )}
        </div>
        <div className="rounded-2xl border border-app-border bg-white p-5">
          <SectionLabel>Report context</SectionLabel>
          <Metric
            label="Coordinates"
            value={formatCoordinates(record.latitude, record.longitude)}
          />
          <Metric
            label="Submitted"
            value={formatTimestamp(record.created_at)}
          />
          <Metric label="Observation ID" value={`#${record.id}`} />
          {observation.duplicate_of_observation_id && (
            <Metric
              label="Possible duplicate source"
              value={`#${observation.duplicate_of_observation_id}`}
            />
          )}
        </div>
      </section>
      {(regional || identification.candidates?.length > 0) && (
        <section className="mt-4 rounded-xl border border-app-border bg-white p-4">
          <SectionLabel>Supporting evidence</SectionLabel>
          {regional && (
            <details className="mt-3 rounded-xl bg-slate-50 p-4">
              <summary className="cursor-pointer font-bold text-teal-700">
                Regional evidence
              </summary>
              <div className="mt-4 grid grid-cols-3 gap-3">
                <Evidence
                  label="Species"
                  value={regional.species?.records_100km}
                />
                <Evidence label="Genus" value={regional.genus?.records_100km} />
                <Evidence
                  label="Family"
                  value={regional.family?.records_100km}
                />
              </div>
            </details>
          )}
          {identification.candidates?.length > 0 && (
            <details className="mt-3 rounded-xl bg-slate-50 p-4">
              <summary className="cursor-pointer font-bold text-teal-700">
                Candidate identifications
              </summary>
              <div className="mt-3 divide-y divide-app-border">
                {identification.candidates.map((candidate) => (
                  <Metric
                    key={candidate.label}
                    label={candidate.scientific_name}
                    value={formatScore(candidate.score)}
                  />
                ))}
              </div>
            </details>
          )}
        </section>
      )}
      <form
        onSubmit={onSubmit}
        className="sticky bottom-0 z-10 mt-4 rounded-xl border border-teal-200 bg-white/95 p-4 shadow-[0_-8px_24px_rgba(15,23,42,.08)] backdrop-blur"
      >
        <SectionLabel>Expert verification</SectionLabel>
        <p className="mt-1 text-sm text-app-muted">
          Record an expert decision for this jurisdiction-level report.
        </p>
        <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {ACTIONS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              disabled={submitting}
              onClick={() => setStatus(value)}
              className={`rounded-lg border px-3 py-3 text-sm font-bold ${status === value ? (value === "REJECTED" ? "border-red-500 bg-red-50 text-red-700" : "border-teal-600 bg-teal-50 text-teal-700") : "border-app-border bg-white text-slate-600"}`}
            >
              {label}
            </button>
          ))}
        </div>
        {["CONFIRMED", "CORRECTED"].includes(status) && (
          <label className="mt-5 block text-sm font-semibold">
            {status === "CORRECTED"
              ? "Correct scientific name"
              : "Verified species"}
            <input
              value={verifiedSpecies}
              disabled={submitting}
              onChange={(event) => setVerifiedSpecies(event.target.value)}
              className="mt-2 w-full rounded-lg border border-app-border px-3 py-2.5 font-normal"
              placeholder="Scientific species name"
            />
          </label>
        )}
        <label className="mt-4 block text-sm font-semibold">
          Reviewer notes{" "}
          <span className="font-normal text-app-muted">(optional)</span>
          <textarea
            value={notes}
            disabled={submitting}
            onChange={(event) => setNotes(event.target.value)}
            rows="3"
            className="mt-2 w-full rounded-lg border border-app-border px-3 py-2.5 font-normal"
          />
        </label>
        {status === "NEEDS_MORE_REVIEW" && (
          <p className="mt-3 text-sm text-app-muted">
            The report will remain in the review queue.
          </p>
        )}
        {error && (
          <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">
            {error}
          </p>
        )}
        {success && (
          <p className="mt-3 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">
            {success}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting}
          className={`mt-5 rounded-lg px-5 py-3 text-sm font-bold text-white ${status === "REJECTED" ? "bg-red-600" : "bg-teal-700"}`}
        >
          {submitting ? "Saving expert decision…" : actionButtonLabel(status)}
        </button>
      </form>
    </div>
  );
}

function Thumbnail({ url }) {
  const [failed, setFailed] = useState(false);
  const source = getImageUrl(url);
  return source && !failed ? (
    <img
      src={source}
      onError={() => setFailed(true)}
      alt="Submitted observation"
      className="h-12 w-12 rounded-lg object-cover"
    />
  ) : (
    <span className="grid h-12 w-12 place-items-center rounded-lg bg-slate-100 text-app-muted">
      ◫
    </span>
  );
}
function LargeImage({ url, species }) {
  const [failed, setFailed] = useState(false);
  const source = getImageUrl(url);
  return (
    <div className="grid min-h-[420px] place-items-center overflow-hidden rounded-xl border border-app-border bg-slate-900 lg:min-h-[500px]">
      {source && !failed ? (
        <img
          src={source}
          onError={() => setFailed(true)}
          alt={species || "Submitted marine observation"}
          className="max-h-[640px] h-auto w-full object-contain"
        />
      ) : (
        <div className="text-center text-slate-300">
          <strong className="block">Image unavailable</strong>
          <span className="mt-1 block text-sm">
            The submitted image could not be loaded.
          </span>
        </div>
      )}
    </div>
  );
}
function QueueMessage({ children }) {
  return (
    <div className="p-6 text-center text-sm text-app-muted">{children}</div>
  );
}
function Badge({ children, tone = "neutral" }) {
  const colors =
    tone === "danger"
      ? "bg-red-100 text-red-700"
      : tone === "warning"
        ? "bg-amber-100 text-amber-800"
        : "bg-slate-100 text-slate-600";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${colors}`}
    >
      {children}
    </span>
  );
}
function SectionLabel({ children }) {
  return (
    <span className="text-[11px] font-bold uppercase tracking-[.12em] text-app-muted">
      {children}
    </span>
  );
}
function Metric({ label, value }) {
  return (
    <div className="mt-3 flex items-start justify-between gap-4 text-sm">
      <span className="text-app-muted">{label}</span>
      <strong className="text-right">{value || "Unavailable"}</strong>
    </div>
  );
}
function Evidence({ label, value }) {
  return (
    <div className="rounded-lg bg-white p-3 text-center">
      <strong className="block text-xl">{value ?? "—"}</strong>
      <span className="text-xs text-app-muted">{label} records / 100 km</span>
    </div>
  );
}
function readable(value) {
  return value
    ? String(value)
        .replaceAll("_", " ")
        .toLowerCase()
        .replace(/\b\w/g, (character) => character.toUpperCase())
    : "Unavailable";
}
function formatScore(value) {
  return value == null ? "Unavailable" : Number(value).toFixed(3);
}
function formatCoordinates(latitude, longitude) {
  return latitude == null || longitude == null
    ? "Unavailable"
    : `${Number(latitude).toFixed(5)}, ${Number(longitude).toFixed(5)}`;
}
function formatTimestamp(value) {
  if (!value) return "Unavailable";
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime())
    ? "Unavailable"
    : timestamp.toLocaleString();
}
function matchesReason(item, filter) {
  if (filter === "ALL") return true;
  if (filter === "DUPLICATE") return item.is_possible_duplicate === true;
  if (filter === "HIGH") return item.priority === "HIGH";
  if (filter === "INVASIVE") return item.ecological_status === "INVASIVE";
  if (filter === "UNRESOLVED")
    return (
      item.decision === "UNRESOLVED_IDENTIFICATION" ||
      (!item.species && !item.ai_species)
    );
  if (filter === "ANOMALY")
    return ["SPECIES_LEVEL_ANOMALY", "TAXONOMIC_ANOMALY"].includes(
      item.decision,
    );
  return true;
}
function actionButtonLabel(status) {
  return {
    CONFIRMED: "Confirm identification",
    CORRECTED: "Save correction",
    NEEDS_MORE_REVIEW: "Mark for further review",
    REJECTED: "Reject report",
  }[status];
}
function actionSuccessLabel(status) {
  return {
    CONFIRMED: "Identification confirmed.",
    CORRECTED: "Correction saved.",
    NEEDS_MORE_REVIEW: "Report retained for further review.",
    REJECTED: "Report rejected.",
  }[status];
}
