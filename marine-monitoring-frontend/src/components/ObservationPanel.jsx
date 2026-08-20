import {
  getImageUrl,
} from "../services/api";
import { useState } from "react";


function formatDecision(value) {
  if (!value) {
    return "—";
  }

  return value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(
      /\b\w/g,
      (character) =>
        character.toUpperCase()
    );
}


function EvidenceCard({
  title,
  evidence,
}) {

  if (!evidence) {
    return null;
  }

  return (
    <div className="evidence-card">

      <h4>{title}</h4>

      <div className="evidence-number">
        {evidence.records_100km ?? 0}
      </div>

      <span>
        records within 100 km
      </span>

      <div className="evidence-meta">

        <span>
          Nearest
        </span>

        <strong>
          {
            evidence.nearest_km != null
              ? `${evidence.nearest_km.toFixed(1)} km`
              : "—"
          }
        </strong>

      </div>

      <div className="evidence-meta">

        <span>
          Locations
        </span>

        <strong>
          {
            evidence.unique_locations
            ?? 0
          }
        </strong>

      </div>

    </div>
  );
}


export default function ObservationPanel({
  observation,
  details,
  loading,
}) {

  if (!observation) {

    return (
      <div className="observation-panel empty-panel">

        <h2>
          Observation details
        </h2>

        <p>
          Select a sighting on the
          map to inspect its analysis.
        </p>

      </div>
    );
  }


  if (loading) {

    return (
      <div className="observation-panel">

        <h2>
          Loading observation...
        </h2>

      </div>
    );
  }


  const identification =
    details?.identification;

  const regional =
    details?.regional_evidence;

  const verification =
    details?.verification;

  const observationRecord =
    details?.observation || {};

  const sourceImageUrl =
    observationRecord.image_url
    || observation.image_url;


  const displayedSpecies =
    verification?.verified_species
    ||
    identification?.species
    ||
    observation.species;


  return (
    <div className="observation-panel">

      <div className="observation-heading">

        <div>

          <span className="observation-id">
            Observation #{observation.id}
          </span>

          <h2>
            {
              displayedSpecies
              ||
              "Unresolved observation"
            }
          </h2>

        </div>

        <span
          className={`status-badge priority-${(
            details?.priority
            ||
            observation.priority
            ||
            ""
          ).toLowerCase()}`}
        >
          {
            details?.priority
            ||
            observation.priority
          }
        </span>

      </div>


      <ObservationImage
        key={sourceImageUrl || "missing"}
        imageUrl={sourceImageUrl}
        species={displayedSpecies}
      />


      <section className="panel-section">

        <h3>
          Assessment
        </h3>

        <div className="detail-row">
          <span>Decision</span>

          <strong>
            {
              formatDecision(
                details?.decision
                ||
                observation.decision
              )
            }
          </strong>
        </div>


        <div className="detail-row">
          <span>
            Ecological status
          </span>

          <strong>
            {
              details?.ecological_status
              ||
              observation.ecological_status
            }
          </strong>
        </div>


        <div className="detail-row">
          <span>
            Verification
          </span>

          <strong>
            {
              verification?.status
              ||
              observation.verification_status
            }
          </strong>
        </div>


        {details?.reason && (

          <div className="reason-box">
            {details.reason}
          </div>

        )}

      </section>


      <section className="panel-section">

        <h3>
          AI identification
        </h3>

        <div className="detail-row">
          <span>
            AI species
          </span>

          <strong>
            {
              identification?.species
              ||
              "Unresolved"
            }
          </strong>
        </div>


        {identification?.nearest_candidate && (

          <div className="detail-row">

            <span>
              Nearest candidate
            </span>

            <strong>
              {
                identification
                  .nearest_candidate
              }
            </strong>

          </div>

        )}


        <div className="detail-row">
          <span>
            AI identification score
          </span>

          <strong>
            {
              identification?.score != null
                ? identification.score
                    .toFixed(3)
                : "—"
            }
          </strong>
        </div>


        <div className="detail-row">
          <span>
            Candidate margin
          </span>

          <strong>
            {
              identification?.margin != null
                ? identification.margin
                    .toFixed(3)
                : "—"
            }
          </strong>
        </div>

      </section>

      <section className="panel-section">

        <h3>Observation context</h3>

        <div className="detail-row">
          <span>Coordinates</span>
          <strong>
            {formatCoordinates(
              observationRecord.latitude ?? observation.latitude,
              observationRecord.longitude ?? observation.longitude
            )}
          </strong>
        </div>

        <div className="detail-row">
          <span>Submitted</span>
          <strong>{formatTimestamp(observationRecord.created_at)}</strong>
        </div>

        <div className="detail-row">
          <span>Possible duplicate</span>
          <strong>
            {details?.is_possible_duplicate === true
              ? details.duplicate_of_observation_id
                ? `Yes — observation #${details.duplicate_of_observation_id}`
                : "Yes"
              : details?.is_possible_duplicate === false
                ? "No"
                : "Unavailable"}
          </strong>
        </div>

        {verification?.verified_at && (
          <div className="detail-row">
            <span>Verification action</span>
            <strong>{formatTimestamp(verification.verified_at)}</strong>
          </div>
        )}

      </section>


      {regional && (

        <details className="panel-section scientific-details">

          <summary>
            Show regional evidence
          </summary>

          <div className="evidence-grid">

            <EvidenceCard
              title="Species"
              evidence={
                regional.species
              }
            />

            <EvidenceCard
              title="Genus"
              evidence={
                regional.genus
              }
            />

            <EvidenceCard
              title="Family"
              evidence={
                regional.family
              }
            />

          </div>

        </details>

      )}


      {identification?.candidates?.length > 0 && (

        <details className="panel-section scientific-details">

          <summary>
            Show candidate species
          </summary>

          <div className="candidate-list">

            {identification.candidates.map(
              (candidate, index) => (

                <div
                  className="candidate-row"
                  key={
                    candidate.label
                  }
                >

                  <span>
                    {index + 1}.{" "}
                    {
                      candidate
                        .scientific_name
                    }
                  </span>

                  <strong>
                    {
                      candidate.score
                        .toFixed(3)
                    }
                  </strong>

                </div>

              )
            )}

          </div>

        </details>

      )}


      {verification?.verified_species && (

        <section className="panel-section verification-box">

          <h3>
            Expert verification
          </h3>

          <strong>
            {
              verification
                .verified_species
            }
          </strong>

          {verification.notes && (
            <p>
              {verification.notes}
            </p>
          )}

        </section>

      )}

    </div>
  );
}


function ObservationImage({ imageUrl, species }) {
  const [failed, setFailed] = useState(false);
  const resolvedUrl = getImageUrl(imageUrl);

  if (!resolvedUrl || failed) {
    return (
      <div className="observation-image-fallback" role="status">
        <strong>Image unavailable</strong>
        <span>The submitted image could not be loaded.</span>
      </div>
    );
  }

  return (
    <img
      src={resolvedUrl}
      alt={species || "Marine observation"}
      className="observation-image"
      onError={() => setFailed(true)}
    />
  );
}


function formatCoordinates(latitude, longitude) {
  if (latitude == null || longitude == null) {
    return "Unavailable";
  }

  return `${Number(latitude).toFixed(5)}, ${Number(longitude).toFixed(5)}`;
}


function formatTimestamp(value) {
  if (!value) {
    return "Unavailable";
  }

  const timestampValue = /(?:Z|[+-]\d\d:\d\d)$/i.test(value)
    ? value
    : `${value}Z`;
  const timestamp = new Date(timestampValue);

  return Number.isNaN(timestamp.getTime())
    ? "Unavailable"
    : timestamp.toLocaleString();
}
