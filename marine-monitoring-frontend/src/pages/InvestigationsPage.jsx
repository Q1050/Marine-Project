import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { jurisdictionRoles, useAuth } from "../auth/AuthContext";
import {
  createFieldObservation,
  createFieldVisit,
  createInvestigation,
  getFieldVisits,
  getInvestigations,
  getJurisdictionOrganizations,
  submitFieldVisit,
  updateInvestigationStatus,
} from "../services/api";
import { useJurisdiction } from "../geography/JurisdictionContext";

const readable = (value) =>
  value
    ? String(value)
        .replaceAll("_", " ")
        .toLowerCase()
        .replace(/\b\w/g, (letter) => letter.toUpperCase())
    : "Unavailable";
const date = (value) => (value ? new Date(value).toLocaleString() : "—");

export default function InvestigationsPage() {
  const { user } = useAuth();
  const { activeRegion, activeJurisdiction, jurisdiction } = useJurisdiction();
  const scope = useMemo(
    () => ({ region: activeRegion, jurisdiction: activeJurisdiction }),
    [activeRegion, activeJurisdiction],
  );
  const [searchParams, setSearchParams] = useSearchParams();
  const canManage =
    user?.is_platform_admin ||
    jurisdictionRoles(user, activeRegion, activeJurisdiction).includes(
      "MANAGER",
    );
  const [items, setItems] = useState([]);
  const [organizations, setOrganizations] = useState([]);
  const [state, setState] = useState("loading");
  const [selectedId, setSelectedId] = useState(null);
  const [filters, setFilters] = useState({
    status: "",
    priority: "",
    source_type: "",
    organization_id: "",
  });
  const [creating, setCreating] = useState(
    canManage && searchParams.has("source_type"),
  );
  const [error, setError] = useState(null);

  async function load() {
    setState("loading");
    try {
      const [investigations, orgs] = await Promise.all([
        getInvestigations(scope, filters),
        getJurisdictionOrganizations(activeRegion, activeJurisdiction),
      ]);
      setItems(investigations.investigations || []);
      setOrganizations(
        (orgs.organizations || []).filter((item) => item.status === "ACTIVE"),
      );
      setSelectedId(
        (current) => current || investigations.investigations?.[0]?.id || null,
      );
      setState("ready");
    } catch (loadError) {
      setError(loadError.message);
      setState("error");
    }
  }
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    const pendingLoad = window.setTimeout(load, 0);
    return () => window.clearTimeout(pendingLoad);
  }, [
    filters.status,
    filters.priority,
    filters.source_type,
    filters.organization_id,
  ]);
  /* eslint-enable react-hooks/exhaustive-deps */

  const selected = items.find((item) => item.id === selectedId) || null;
  const summary = useMemo(
    () => ({
      planned: items.filter((item) => item.status === "PLANNED").length,
      progress: items.filter((item) => item.status === "IN_PROGRESS").length,
      urgent: items.filter((item) => ["HIGH", "URGENT"].includes(item.priority))
        .length,
      completed: items.filter((item) => item.status === "COMPLETED").length,
    }),
    [items],
  );

  async function transition(status, outcome) {
    try {
      const updated = await updateInvestigationStatus(
        selected.id,
        status,
        outcome,
      );
      setItems((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (actionError) {
      setError(actionError.message);
    }
  }

  return (
    <div className="mx-auto max-w-[1500px]">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[.15em] text-teal-700">
            {jurisdiction?.name} operational response
          </p>
          <h1 className="mt-1 text-3xl font-bold">Investigations</h1>
          <p className="mt-2 text-sm text-app-muted">
            Coordinate field follow-up from verified observations, monitoring
            priorities, and operational decisions.
          </p>
        </div>
        {canManage && (
          <button
            onClick={() => setCreating(true)}
            className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-bold text-white"
          >
            New investigation
          </button>
        )}
      </header>
      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          ["Planned", summary.planned],
          ["In progress", summary.progress],
          ["High / urgent", summary.urgent],
          ["Completed", summary.completed],
        ].map(([label, value]) => (
          <div
            key={label}
            className="rounded-xl border border-app-border bg-white p-4"
          >
            <span className="text-xs text-app-muted">{label}</span>
            <strong className="mt-1 block text-2xl">{value}</strong>
          </div>
        ))}
      </div>
      <div className="mt-5 flex flex-wrap gap-2 rounded-xl border border-app-border bg-white p-3">
        {[
          ["status", ["PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]],
          ["priority", ["LOW", "MODERATE", "HIGH", "URGENT"]],
          ["source_type", ["MANUAL", "OBSERVATION", "MONITORING_PRIORITY"]],
        ].map(([key, options]) => (
          <select
            key={key}
            value={filters[key]}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                [key]: event.target.value,
              }))
            }
            className="rounded-lg border border-app-border px-3 py-2 text-sm"
          >
            <option value="">All {readable(key)}</option>
            {options.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        ))}
        <select
          value={filters.organization_id}
          onChange={(event) =>
            setFilters((current) => ({
              ...current,
              organization_id: event.target.value,
            }))
          }
          className="rounded-lg border border-app-border px-3 py-2 text-sm"
        >
          <option value="">All organizations</option>
          {organizations.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </div>
      {error && (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}
      {state === "loading" && (
        <div className="mt-5 rounded-xl border border-app-border bg-white p-10 text-center text-app-muted">
          Loading investigations…
        </div>
      )}
      {state === "error" && (
        <button
          onClick={load}
          className="mt-3 rounded-lg border border-app-border px-4 py-2 text-sm font-bold"
        >
          Try again
        </button>
      )}
      {state === "ready" && (
        <div className="mt-5 grid min-h-[540px] overflow-hidden rounded-xl border border-app-border bg-white lg:grid-cols-[minmax(300px,38%)_minmax(0,1fr)]">
          <div
            className={`${selected ? "hidden lg:block" : "block"} border-r border-app-border`}
          >
            <div className="border-b border-app-border px-4 py-3 text-xs font-bold uppercase tracking-wide text-app-muted">
              {items.length} investigations
            </div>
            {items.map((item) => (
              <button
                key={item.id}
                onClick={() => setSelectedId(item.id)}
                className={`block w-full border-b border-app-border p-4 text-left hover:bg-slate-50 ${selectedId === item.id ? "border-l-4 border-l-teal-600 bg-teal-50" : ""}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <strong className="text-sm">{item.title}</strong>
                  <Badge value={item.priority} />
                </div>
                <p className="mt-1 text-xs text-app-muted">
                  Investigation #{item.id} · {readable(item.source.type)}
                </p>
                <div className="mt-3 flex items-center justify-between">
                  <Badge value={item.status} />
                  <span className="text-xs text-app-muted">
                    {item.assigned_organization.name}
                  </span>
                </div>
              </button>
            ))}
            {items.length === 0 && (
              <div className="p-10 text-center text-sm text-app-muted">
                No investigations match the selected filters. Investigations are
                created from verified observations, monitoring priorities, or
                authorized operational follow-up.
              </div>
            )}
          </div>
          <div className={`${selected ? "block" : "hidden lg:block"}`}>
            {selected ? (
              <InvestigationDetail
                item={selected}
                organizations={organizations}
                canManage={canManage}
                onBack={() => setSelectedId(null)}
                onTransition={transition}
              />
            ) : (
              <div className="grid h-full place-items-center p-10 text-center text-app-muted">
                Select an investigation to review its operational context.
              </div>
            )}
          </div>
        </div>
      )}
      {creating && (
        <CreationDialog
          organizations={organizations}
          searchParams={searchParams}
          onClose={() => {
            setCreating(false);
            setSearchParams({});
          }}
          onCreated={(item) => {
            setItems((current) => [item, ...current]);
            setSelectedId(item.id);
            setCreating(false);
            setSearchParams({});
          }}
        />
      )}
    </div>
  );
}

function InvestigationDetail({
  item,
  organizations,
  canManage,
  onBack,
  onTransition,
}) {
  const [outcome, setOutcome] = useState(item.outcome_summary || "");
  const [visits, setVisits] = useState([]);
  const [visitState, setVisitState] = useState("loading");
  const [visitError, setVisitError] = useState(null);
  const [selectedVisitId, setSelectedVisitId] = useState(null);
  const [recording, setRecording] = useState(false);
  const loadVisits = async () => {
    try {
      const result = await getFieldVisits(item.id);
      setVisits(result.field_visits || []);
      setVisitState("ready");
      setVisitError(null);
    } catch (error) {
      setVisitError(error.message);
      setVisitState("error");
    }
  };
  useEffect(() => {
    const pendingLoad = window.setTimeout(loadVisits, 0);
    return () => window.clearTimeout(pendingLoad);
  }, [item.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const selectedVisit = visits.find((visit) => visit.id === selectedVisitId);
  return (
    <article className="p-5 sm:p-7">
      <button
        onClick={onBack}
        className="mb-4 text-sm font-bold text-teal-700 lg:hidden"
      >
        ← Back to investigations
      </button>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-teal-700">
            Investigation #{item.id}
          </p>
          <h2 className="mt-1 text-2xl font-bold">{item.title}</h2>
        </div>
        <div className="flex gap-2">
          <Badge value={item.status} />
          <Badge value={item.priority} />
        </div>
      </div>
      <p className="mt-5 text-sm leading-6 text-slate-700">{item.objective}</p>
      <section className="mt-6 grid gap-4 border-t border-app-border pt-5 sm:grid-cols-2">
        <Field label="Jurisdiction" value={item.jurisdiction.name} />
        <Field
          label="Assigned organization"
          value={item.assigned_organization.name}
        />
        <Field
          label="Target"
          value={`${Number(item.latitude).toFixed(4)}, ${Number(item.longitude).toFixed(4)}`}
        />
        <Field label="Created by" value={item.created_by.display_name} />
        <Field label="Created" value={date(item.created_at)} />
        <Field label="Started" value={date(item.started_at)} />
        <Field label="Completed" value={date(item.completed_at)} />
        <Field label="Cancelled" value={date(item.cancelled_at)} />
      </section>
      <section className="mt-6 rounded-xl border border-app-border bg-slate-50 p-4">
        <h3 className="text-sm font-bold">Source intelligence</h3>
        <p className="mt-1 text-sm">{readable(item.source.type)}</p>
        {item.source.type === "MONITORING_PRIORITY" && (
          <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            <Field label="Generation" value={item.source.generation_id} />
            <Field label="Cell" value={item.source.cell_id} />
            <Field
              label="Priority at creation"
              value={`${readable(item.source.priority_band)} · ${Number(item.source.priority_score).toFixed(3)}`}
            />
            <Field label="Generated" value={date(item.source.generated_at)} />
          </div>
        )}
        {item.source.type === "OBSERVATION" && (
          <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            <Field
              label="Observation"
              value={`#${item.source.observation_id}`}
            />
            <Field
              label="Species at creation"
              value={item.source.observation_at_creation?.species}
            />
            <Field
              label="Verification at creation"
              value={readable(
                item.source.observation_at_creation?.verification_status,
              )}
            />
            <Field
              label="Submitted"
              value={date(item.source.observation_at_creation?.submitted_at)}
            />
            {item.source.observation && (
              <Field
                label="Current verification"
                value={readable(item.source.observation.verification_status)}
              />
            )}
          </div>
        )}
        {item.source.type === "MONITORING_PRIORITY" && (
          <p className="mt-3 text-xs text-app-muted">
            Monitoring prioritization; not a spread, invasion, or occurrence
            probability.
          </p>
        )}
      </section>
      {item.outcome_summary && (
        <section className="mt-5">
          <h3 className="text-sm font-bold">Outcome summary</h3>
          <p className="mt-2 text-sm text-slate-700">{item.outcome_summary}</p>
        </section>
      )}
      <FieldActivity
        visits={visits}
        state={visitState}
        error={visitError}
        selectedVisit={selectedVisit}
        onSelect={setSelectedVisitId}
        onRetry={loadVisits}
        canRecord={
          canManage && ["PLANNED", "IN_PROGRESS"].includes(item.status)
        }
        onRecord={() => setRecording(true)}
      />
      {canManage && !["COMPLETED", "CANCELLED"].includes(item.status) && (
        <section className="mt-6 border-t border-app-border pt-5">
          <h3 className="text-sm font-bold">Operational actions</h3>
          {item.status === "IN_PROGRESS" && (
            <textarea
              value={outcome}
              onChange={(event) => setOutcome(event.target.value)}
              placeholder="Optional completion summary"
              className="mt-3 min-h-24 w-full rounded-lg border border-app-border p-3 text-sm"
            />
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {item.status === "PLANNED" && (
              <button
                onClick={() => onTransition("IN_PROGRESS")}
                className="rounded-lg bg-teal-700 px-4 py-2 text-sm font-bold text-white"
              >
                Start investigation
              </button>
            )}
            {item.status === "IN_PROGRESS" && (
              <button
                onClick={() => onTransition("COMPLETED", outcome)}
                className="rounded-lg bg-teal-700 px-4 py-2 text-sm font-bold text-white"
              >
                Complete
              </button>
            )}
            <button
              onClick={() => onTransition("CANCELLED")}
              className="rounded-lg border border-red-200 px-4 py-2 text-sm font-bold text-red-700"
            >
              Cancel
            </button>
          </div>
        </section>
      )}
      {recording && (
        <FieldVisitDialog
          investigation={item}
          organizations={organizations}
          onClose={() => setRecording(false)}
          onSaved={(visit) => {
            setVisits((current) => [visit, ...current]);
            setSelectedVisitId(visit.id);
            setRecording(false);
          }}
        />
      )}
    </article>
  );
}

function FieldActivity({
  visits,
  state,
  error,
  selectedVisit,
  onSelect,
  onRetry,
  canRecord,
  onRecord,
}) {
  return (
    <section className="mt-6 border-t border-app-border pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-bold">Field activity</h3>
          <p className="text-sm text-app-muted">
            {visits.length} field {visits.length === 1 ? "visit" : "visits"}{" "}
            recorded
          </p>
        </div>
        {canRecord && (
          <button
            type="button"
            onClick={onRecord}
            className="rounded-lg border border-teal-200 px-4 py-2 text-sm font-bold text-teal-700"
          >
            Record field visit
          </button>
        )}
      </div>
      {state === "loading" && (
        <p className="mt-4 text-sm text-app-muted">Loading field activityâ€¦</p>
      )}
      {state === "error" && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}{" "}
          <button onClick={onRetry} className="font-bold underline">
            Try again
          </button>
        </div>
      )}
      {state === "ready" && visits.length === 0 && (
        <div className="mt-4 rounded-xl border border-dashed border-app-border p-6 text-center text-sm text-app-muted">
          No field visits have been recorded for this investigation.
        </div>
      )}
      <div className="mt-4 space-y-2">
        {visits.map((visit) => (
          <button
            key={visit.id}
            type="button"
            onClick={() => onSelect(visit.id)}
            className={`w-full rounded-xl border p-4 text-left ${selectedVisit?.id === visit.id ? "border-teal-400 bg-teal-50" : "border-app-border"}`}
          >
            <div className="flex flex-wrap justify-between gap-2">
              <strong>
                Visit {visit.id} · {readable(visit.survey_method)}
              </strong>
              <div className="flex gap-2">
                <Badge value={visit.status} />
                <Badge value={visit.target_detection_status} />
              </div>
            </div>
            <p className="mt-2 text-xs text-app-muted">
              {date(visit.visited_at)} · {visit.organization.name} ·{" "}
              {visit.observation_count} field observations
            </p>
            {visit.target_detection_status === "NOT_DETECTED" && (
              <p className="mt-2 text-xs text-amber-800">
                Target not detected during this field visit. This does not
                establish species absence.
              </p>
            )}
          </button>
        ))}
      </div>
      {selectedVisit && (
        <FieldVisitDetail
          visit={selectedVisit}
          onClose={() => onSelect(null)}
        />
      )}
    </section>
  );
}

function FieldVisitDetail({ visit, onClose }) {
  return (
    <div className="mt-4 rounded-xl border border-teal-200 bg-white p-4">
      <div className="flex justify-between">
        <h4 className="font-bold">Visit {visit.id} details</h4>
        <button onClick={onClose} aria-label="Close visit details">
          Ã—
        </button>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Field label="Visited" value={date(visit.visited_at)} />
        <Field label="Recorded by" value={visit.recorded_by.display_name} />
        <Field label="Organization" value={visit.organization.name} />
        <Field
          label="Location"
          value={`${Number(visit.latitude).toFixed(4)}, ${Number(visit.longitude).toFixed(4)}`}
        />
        <Field label="Survey method" value={readable(visit.survey_method)} />
        <Field
          label="Effort"
          value={`${visit.effort_duration_minutes} minutes`}
        />
        <Field
          label="Detection result"
          value={readable(visit.target_detection_status)}
        />
        <Field label="Status" value={readable(visit.status)} />
      </div>
      {visit.notes && (
        <p className="mt-4 text-sm text-slate-700">{visit.notes}</p>
      )}
      {visit.target_detection_status === "NOT_DETECTED" && (
        <div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          Target not detected during this field visit. A non-detection records
          this survey effort and should not be interpreted as confirmed species
          absence.
        </div>
      )}
      <div className="mt-4">
        <h5 className="text-sm font-bold">Field observations</h5>
        {visit.observations.length === 0 ? (
          <p className="mt-2 text-sm text-app-muted">
            No biological field observations recorded.
          </p>
        ) : (
          visit.observations.map((observation) => (
            <div
              key={observation.id}
              className="mt-2 rounded-lg bg-slate-50 p-3 text-sm"
            >
              <strong>{observation.scientific_name}</strong>
              <span className="ml-2 text-app-muted">
                Count: {observation.count_observed ?? "Not precisely counted"}
              </span>
              {observation.latitude != null && (
                <p className="text-xs text-app-muted">
                  {observation.latitude}, {observation.longitude}
                </p>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function FieldVisitDialog({ investigation, organizations, onClose, onSaved }) {
  const [form, setForm] = useState({
    organization_id: investigation.assigned_organization.id,
    visited_at: new Date().toISOString().slice(0, 16),
    latitude: investigation.latitude,
    longitude: investigation.longitude,
    survey_method: "VISUAL_SURVEY",
    effort_duration_minutes: 30,
    target_detection_status: "INCONCLUSIVE",
    area_description: "",
    conditions_notes: "",
    notes: "",
  });
  const [observations, setObservations] = useState([]);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const addObservation = () =>
    setObservations((current) => [
      ...current,
      {
        scientific_name: "Pterois volitans",
        count_observed: "",
        latitude: "",
        longitude: "",
        notes: "",
      },
    ]);
  const updateObservation = (index, key, value) =>
    setObservations((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index ? { ...item, [key]: value } : item,
      ),
    );
  async function save(submit) {
    setSaving(true);
    setError(null);
    try {
      let visit = await createFieldVisit(investigation.id, {
        ...form,
        organization_id: Number(form.organization_id),
        visited_at: new Date(form.visited_at).toISOString(),
        latitude: Number(form.latitude),
        longitude: Number(form.longitude),
        effort_duration_minutes: Number(form.effort_duration_minutes),
        status: "DRAFT",
      });
      for (const observation of observations) {
        await createFieldObservation(visit.id, {
          ...observation,
          count_observed:
            observation.count_observed === ""
              ? null
              : Number(observation.count_observed),
          latitude:
            observation.latitude === "" ? null : Number(observation.latitude),
          longitude:
            observation.longitude === "" ? null : Number(observation.longitude),
        });
      }
      if (submit) visit = await submitFieldVisit(visit.id);
      else
        visit = (await getFieldVisits(investigation.id)).field_visits.find(
          (item) => item.id === visit.id,
        );
      onSaved(visit);
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="fixed inset-0 z-[1600] grid place-items-center bg-slate-950/45 p-3">
      <div className="max-h-[94vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-5 shadow-2xl sm:p-6">
        <div className="flex justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-teal-700">
              Investigation #{investigation.id}
            </p>
            <h2 className="text-xl font-bold">Record field visit</h2>
          </div>
          <button onClick={onClose} aria-label="Close">
            Ã—
          </button>
        </div>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <Input
            label="Visited at"
            type="datetime-local"
            value={form.visited_at}
            onChange={(value) => setForm({ ...form, visited_at: value })}
          />
          <Select
            label="Organization"
            value={form.organization_id}
            onChange={(value) => setForm({ ...form, organization_id: value })}
            options={organizations.map((organization) => ({
              value: organization.id,
              label: organization.name,
            }))}
          />
          <Input
            label="Latitude"
            type="number"
            value={form.latitude}
            onChange={(value) => setForm({ ...form, latitude: value })}
          />
          <Input
            label="Longitude"
            type="number"
            value={form.longitude}
            onChange={(value) => setForm({ ...form, longitude: value })}
          />
          <Select
            label="Survey method"
            value={form.survey_method}
            onChange={(value) => setForm({ ...form, survey_method: value })}
            options={[
              "VISUAL_SURVEY",
              "DIVE_SURVEY",
              "SNORKEL_SURVEY",
              "SHORE_OBSERVATION",
              "TRAP_OR_CAPTURE",
              "OTHER",
            ]}
          />
          <Input
            label="Effort (minutes)"
            type="number"
            value={form.effort_duration_minutes}
            onChange={(value) =>
              setForm({ ...form, effort_duration_minutes: value })
            }
          />
          <Select
            label="Detection result"
            value={form.target_detection_status}
            onChange={(value) =>
              setForm({ ...form, target_detection_status: value })
            }
            options={["DETECTED", "NOT_DETECTED", "INCONCLUSIVE"]}
          />
        </div>
        {form.target_detection_status === "NOT_DETECTED" && (
          <div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
            Target not detected during this field visit. This result must not be
            interpreted as confirmed species absence.
          </div>
        )}
        <label className="mt-4 block text-sm font-bold">
          Visit notes
          <textarea
            value={form.notes}
            onChange={(event) =>
              setForm({ ...form, notes: event.target.value })
            }
            className="mt-1 min-h-20 w-full rounded-lg border border-app-border p-2.5 font-normal"
          />
        </label>
        <div className="mt-5 flex justify-between">
          <h3 className="font-bold">Field observations</h3>
          <button
            type="button"
            onClick={addObservation}
            className="text-sm font-bold text-teal-700"
          >
            + Add observation
          </button>
        </div>
        {observations.map((observation, index) => (
          <div
            key={index}
            className="mt-3 grid gap-3 rounded-xl border border-app-border p-3 sm:grid-cols-2"
          >
            <Input
              label="Scientific name"
              value={observation.scientific_name}
              onChange={(value) =>
                updateObservation(index, "scientific_name", value)
              }
            />
            <Input
              label="Count (optional)"
              type="number"
              value={observation.count_observed}
              onChange={(value) =>
                updateObservation(index, "count_observed", value)
              }
            />
          </div>
        ))}
        {error && <p className="mt-4 text-sm text-red-700">{error}</p>}
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg border border-app-border px-4 py-2 text-sm font-bold"
          >
            Cancel
          </button>
          <button
            disabled={saving}
            onClick={() => save(false)}
            className="rounded-lg border border-teal-300 px-4 py-2 text-sm font-bold text-teal-700"
          >
            Save draft
          </button>
          <button
            disabled={saving}
            onClick={() => save(true)}
            className="rounded-lg bg-teal-700 px-4 py-2 text-sm font-bold text-white"
          >
            Submit visit
          </button>
        </div>
      </div>
    </div>
  );
}

function CreationDialog({ organizations, searchParams, onClose, onCreated }) {
  const { activeRegion, activeJurisdiction, jurisdiction } = useJurisdiction();
  const sourceType = searchParams.get("source_type") || "MANUAL";
  const [form, setForm] = useState({
    title: "",
    objective: "",
    priority: "MODERATE",
    assigned_organization_id: organizations[0]?.id || "",
    latitude: searchParams.get("latitude") || "",
    longitude: searchParams.get("longitude") || "",
  });
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = {
        ...form,
        assigned_organization_id: Number(form.assigned_organization_id),
        latitude: form.latitude === "" ? null : Number(form.latitude),
        longitude: form.longitude === "" ? null : Number(form.longitude),
        source_type: sourceType,
        source_observation_id: searchParams.get("observation_id")
          ? Number(searchParams.get("observation_id"))
          : null,
        source_prediction_generation_id: searchParams.get("generation_id")
          ? Number(searchParams.get("generation_id"))
          : null,
        source_prediction_cell_id: searchParams.get("cell_id") || null,
      };
      onCreated(await createInvestigation({ region: activeRegion, jurisdiction: activeJurisdiction }, payload));
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="fixed inset-0 z-[1500] grid place-items-center bg-slate-950/45 p-4">
      <form
        onSubmit={submit}
        className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl"
      >
        <div className="flex justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-teal-700">
              {readable(sourceType)}
            </p>
            <h2 className="text-xl font-bold">Create investigation</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        {organizations.length === 0 ? (
          <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            No participating organizations are currently configured for {jurisdiction?.name || "this jurisdiction"}.
            Configure an organization before assigning an investigation.
          </div>
        ) : (
          <div className="mt-5 space-y-4">
            <label className="block text-sm font-bold">
              Title
              <input
                required
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                className="mt-1 w-full rounded-lg border border-app-border p-2.5 font-normal"
              />
            </label>
            <label className="block text-sm font-bold">
              Objective
              <textarea
                required
                value={form.objective}
                onChange={(e) =>
                  setForm({ ...form, objective: e.target.value })
                }
                className="mt-1 min-h-24 w-full rounded-lg border border-app-border p-2.5 font-normal"
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <Select
                label="Operational priority"
                value={form.priority}
                onChange={(value) => setForm({ ...form, priority: value })}
                options={["LOW", "MODERATE", "HIGH", "URGENT"]}
              />
              <label className="text-sm font-bold">
                Assigned organization
                <select
                  required
                  value={form.assigned_organization_id}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      assigned_organization_id: e.target.value,
                    })
                  }
                  className="mt-1 w-full rounded-lg border border-app-border p-2.5 font-normal"
                >
                  {organizations.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {sourceType === "MANUAL" && (
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm font-bold">
                  Latitude
                  <input
                    required
                    type="number"
                    step="any"
                    value={form.latitude}
                    onChange={(e) =>
                      setForm({ ...form, latitude: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-app-border p-2.5 font-normal"
                  />
                </label>
                <label className="text-sm font-bold">
                  Longitude
                  <input
                    required
                    type="number"
                    step="any"
                    value={form.longitude}
                    onChange={(e) =>
                      setForm({ ...form, longitude: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-app-border p-2.5 font-normal"
                  />
                </label>
              </div>
            )}
            {error && <p className="text-sm text-red-700">{error}</p>}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-app-border px-4 py-2 text-sm font-bold"
              >
                Cancel
              </button>
              <button
                disabled={saving}
                className="rounded-lg bg-teal-700 px-4 py-2 text-sm font-bold text-white"
              >
                {saving ? "Creating…" : "Create investigation"}
              </button>
            </div>
          </div>
        )}
      </form>
    </div>
  );
}

function Badge({ value }) {
  return (
    <span className="w-fit rounded-full bg-slate-100 px-2 py-1 text-[11px] font-bold text-slate-700">
      {readable(value)}
    </span>
  );
}
function Field({ label, value }) {
  return (
    <div>
      <span className="block text-[11px] font-bold uppercase tracking-wide text-app-muted">
        {label}
      </span>
      <strong className="mt-1 block text-sm">{value ?? "—"}</strong>
    </div>
  );
}
function Select({ label, value, onChange, options }) {
  return (
    <label className="text-sm font-bold">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-app-border p-2.5 font-normal"
      >
        {options.map((item) => {
          const option =
            typeof item === "object"
              ? item
              : { value: item, label: readable(item) };
          return (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          );
        })}
      </select>
    </label>
  );
}
function Input({ label, value, onChange, type = "text" }) {
  return (
    <label className="text-sm font-bold">
      {label}
      <input
        required
        type={type}
        step={type === "number" ? "any" : undefined}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded-lg border border-app-border p-2.5 font-normal"
      />
    </label>
  );
}
