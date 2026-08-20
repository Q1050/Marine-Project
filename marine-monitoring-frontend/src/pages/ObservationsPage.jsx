import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getImageUrl, getJurisdictions, getMapObservations } from "../services/api";
import { jurisdictionRoles, useAuth } from "../auth/AuthContext";
import { useJurisdiction } from "../geography/JurisdictionContext";

const label = (value) =>
  value
    ? String(value)
        .replaceAll("_", " ")
        .toLowerCase()
        .replace(/\b\w/g, (c) => c.toUpperCase())
    : "Unavailable";

export default function ObservationsPage({ scope = "country", onOpenMap }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const {
    activeRegion,
    activeJurisdiction,
    jurisdiction: metadata,
  } = useJurisdiction();
  const regional = scope === "regional";
  const [items, setItems] = useState([]);
  const [jurisdictionOptions, setJurisdictionOptions] = useState([]);
  const [jurisdictionFilter, setJurisdictionFilter] = useState("");
  const [query, setQuery] = useState("");
  const [verification, setVerification] = useState("");
  const [state, setState] = useState("loading");
  const canManage =
    scope === "country" &&
    (user?.is_platform_admin ||
      jurisdictionRoles(user, activeRegion, activeJurisdiction).includes(
        "MANAGER",
      ));

  useEffect(() => {
    let active = true;
    if (regional) {
      getJurisdictions("caribbean")
        .then((data) => {
          if (!active) return;
          const configured = (data.jurisdictions || []).filter(
            (item) => item.status === "ACTIVE",
          );
          setJurisdictionOptions(configured);
        })
        .catch(() => active && setJurisdictionOptions([]));
    }
    return () => {
      active = false;
    };
  }, [regional]);

  useEffect(() => {
    let active = true;
    const geographicScope = regional
      ? jurisdictionFilter
        ? { region: "caribbean", jurisdiction: jurisdictionFilter }
        : { region: "caribbean" }
      : { region: activeRegion, jurisdiction: activeJurisdiction };
    getMapObservations(geographicScope)
      .then((data) => {
        if (active) {
          setItems(data.markers || []);
          setState("ready");
        }
      })
      .catch(() => active && setState("error"));
    return () => {
      active = false;
    };
  }, [activeJurisdiction, activeRegion, regional, jurisdictionFilter, scope]);

  const filtered = useMemo(
    () =>
      items.filter(
        (item) =>
          (!query ||
            `${item.species || ""} ${item.id}`
              .toLowerCase()
              .includes(query.toLowerCase())) &&
          (!verification || item.verification_status === verification),
      ),
    [items, query, verification],
  );

  return (
    <div className="mx-auto max-w-[1400px]">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[.15em] text-teal-700">
            {regional
              ? "Caribbean regional monitoring"
              : `${metadata?.name || "Jurisdiction"} workspace`}
          </p>
          <h1 className="mt-1 text-3xl font-bold">Observations</h1>
          <p className="mt-2 text-sm text-app-muted">
            {regional
              ? "Available reports from configured Caribbean jurisdictions."
              : "Browse current reports without changing review or verification state."}
          </p>
        </div>
        <button
          onClick={onOpenMap}
          className="rounded-lg border border-app-border bg-white px-4 py-2 text-sm font-bold text-teal-700"
        >
          View on map
        </button>
      </div>
      <div className="mt-6 flex flex-wrap gap-3 rounded-xl border border-app-border bg-white p-4">
        <input
          className="min-w-[220px] flex-1 rounded-lg border border-app-border px-3 py-2 text-sm"
          placeholder="Search species or observation ID"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {regional && (
          <select
            className="rounded-lg border border-app-border px-3 py-2 text-sm"
            value={jurisdictionFilter}
            onChange={(e) => setJurisdictionFilter(e.target.value)}
          >
            <option value="">All jurisdictions</option>
            {jurisdictionOptions.map((item) => (
              <option key={item.slug} value={item.slug}>
                {item.name}
              </option>
            ))}
          </select>
        )}
        <select
          className="rounded-lg border border-app-border px-3 py-2 text-sm"
          value={verification}
          onChange={(e) => setVerification(e.target.value)}
        >
          <option value="">All verification states</option>
          <option value="CONFIRMED">Expert confirmed</option>
          <option value="CORRECTED">Corrected</option>
          <option value="PENDING">Pending review</option>
          <option value="NEEDS_MORE_REVIEW">Needs more review</option>
        </select>
      </div>
      {state === "error" && (
        <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-red-700">
          Observations failed to load.
        </div>
      )}
      {state === "loading" && (
        <div className="mt-5 rounded-xl bg-white p-8 text-center text-app-muted">
          Loading observations…
        </div>
      )}
      {state === "ready" && (
        <div className="mt-5 overflow-hidden rounded-xl border border-app-border bg-white">
          <div
            className={`hidden gap-4 border-b border-app-border bg-slate-50 px-4 py-3 text-[11px] font-bold uppercase tracking-wide text-app-muted md:grid ${regional ? "grid-cols-[64px_1.4fr_1fr_1fr_1fr_1fr_90px]" : canManage ? "grid-cols-[64px_1.3fr_1fr_1fr_1fr_90px_120px]" : "grid-cols-[64px_1.4fr_1fr_1fr_1fr_90px]"}`}
          >
            <span>Image</span>
            <span>Species</span>
            <span>Location</span>
            {regional && <span>Jurisdiction</span>}
            <span>AI identification</span>
            <span>Verification</span>
            <span>Priority</span>
            {canManage && <span>Action</span>}
          </div>
          {filtered.map((item) => (
            <article
              key={item.id}
              className={`grid gap-3 border-b border-app-border p-4 last:border-0 md:items-center ${regional ? "md:grid-cols-[64px_1.4fr_1fr_1fr_1fr_1fr_90px]" : canManage ? "md:grid-cols-[64px_1.3fr_1fr_1fr_1fr_90px_120px]" : "md:grid-cols-[64px_1.4fr_1fr_1fr_1fr_90px]"}`}
            >
              <Image url={item.image_url} />
              <div>
                <strong className="block text-sm">
                  {item.species || "Unresolved observation"}
                </strong>
                <small className="text-app-muted">Observation #{item.id}</small>
              </div>
              <span className="text-sm text-app-muted">
                {Number(item.latitude).toFixed(3)},{" "}
                {Number(item.longitude).toFixed(3)}
              </span>
              {regional && (
                <span className="text-sm">
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold">
                    {item.jurisdiction ? label(item.jurisdiction) : "Unknown"}
                  </span>
                </span>
              )}
              <span className="text-sm">
                {label(item.identification_status)}
              </span>
              <span className="text-sm font-medium">
                {label(item.verification_status || item.decision)}
              </span>
              <span className="w-fit rounded-full bg-slate-100 px-2 py-1 text-xs font-bold">
                {label(item.priority)}
              </span>
              {canManage && (
                <button
                  type="button"
                  onClick={() =>
                    navigate(
                      `/region/${activeRegion}/${activeJurisdiction}/investigations?source_type=OBSERVATION&observation_id=${encodeURIComponent(item.id)}&latitude=${encodeURIComponent(item.latitude)}&longitude=${encodeURIComponent(item.longitude)}`,
                    )
                  }
                  className="rounded-lg border border-teal-200 px-3 py-2 text-xs font-bold text-teal-700"
                >
                  Investigate
                </button>
              )}
            </article>
          ))}
          {filtered.length === 0 && (
            <p className="p-10 text-center text-app-muted">
              No observations match these filters.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function Image({ url }) {
  const [failed, setFailed] = useState(false);
  const src = getImageUrl(url);
  return src && !failed ? (
    <img
      src={src}
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