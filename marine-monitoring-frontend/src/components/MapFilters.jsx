export default function MapFilters({
  filters,
  onChange,
  observations,
}) {

  const speciesOptions = [
    ...new Set(
      observations
        .map((item) => item.species)
        .filter(Boolean)
    ),
  ].sort();

  function updateFilter(
    key,
    value
  ) {
    onChange({
      ...filters,
      [key]: value,
    });
  }


  return (
    <div className="filters-panel">

      <div className="filter-header">
        <h3>Filters</h3>

        <button
          className="clear-button"
          onClick={() =>
            onChange({
              species: "",
              ecological_status: "",
              priority: "",
              verification_status: "",
              decision: "",
            })
          }
        >
          Clear
        </button>
      </div>


      <label>
        Species

        <select
          value={filters.species}
          onChange={(event) =>
            updateFilter(
              "species",
              event.target.value
            )
          }
        >

          <option value="">
            All species
          </option>

          {speciesOptions.map(
            (species) => (

              <option
                key={species}
                value={species}
              >
                {species}
              </option>

            )
          )}

        </select>
      </label>


      <label>
        Ecological status

        <select
          value={
            filters.ecological_status
          }
          onChange={(event) =>
            updateFilter(
              "ecological_status",
              event.target.value
            )
          }
        >

          <option value="">
            All
          </option>

          <option value="NATIVE">
            Native
          </option>

          <option value="INVASIVE">
            Invasive
          </option>

          <option value="UNKNOWN">
            Unknown
          </option>

        </select>
      </label>


      <label>
        Priority

        <select
          value={filters.priority}
          onChange={(event) =>
            updateFilter(
              "priority",
              event.target.value
            )
          }
        >

          <option value="">
            All
          </option>

          <option value="LOW">
            Low
          </option>

          <option value="MONITOR">
            Monitor
          </option>

          <option value="REVIEW">
            Review
          </option>

          <option value="HIGH">
            High
          </option>

        </select>
      </label>


      <label>
        Verification

        <select
          value={
            filters.verification_status
          }
          onChange={(event) =>
            updateFilter(
              "verification_status",
              event.target.value
            )
          }
        >

          <option value="">
            All
          </option>

          <option value="PENDING">
            Pending
          </option>

          <option value="CONFIRMED">
            Confirmed
          </option>

          <option value="CORRECTED">
            Corrected
          </option>

          <option value="NEEDS_MORE_REVIEW">
            Needs more review
          </option>

        </select>
      </label>

    </div>
  );
}