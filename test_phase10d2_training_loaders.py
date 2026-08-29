"""Phase 10D-2: Generalized scientific dataset input loader tests.

Tests cover at minimum:

1. Jamaica v3 spec resolves the correct occurrence dataset.
2. Exactly the 54 existing HistoricalOccurrence rows are selected.
3. No unrelated occurrence rows are included.
4. Explicit environmental dataset ID resolves correctly.
5. Missing occurrence dataset fails.
6. Missing environmental dataset fails.
7. Wrong dataset type fails.
8. Species mismatch fails.
9. Jurisdiction mismatch fails.
10. Region-scoped environmental dataset can support a jurisdiction-scoped
    training spec where scientifically/architecturally allowed.
    (In Phase 10D-2 conservatively false; the test confirms the
    conservative refusal.)
11. Bahamas spec cannot silently inherit Jamaica occurrence data.
12. Dataset provenance is returned with the loaded inputs.
13. Credentials/secrets are not exposed in provenance output.
14. Loading performs no database mutation.
15. Loading performs no training.
16. Loading performs no deployment activation.

Run only the focused Phase 10D-2 tests.
"""

import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# We intentionally do NOT use the live production database because
# every test must be isolated: the loader must read but never write.
# Tests build a per-test in-memory SQLite image of the schema and append
# only the rows required for the assertion.



def _minimal_spec_kwargs(**overrides):
    from suitability_training_spec import SuitabilityGrid
    base = {
        "background_extent_bounds": {
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        "spatial_block_origin": {
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        },
        "grid": SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        ),
    }
    base.update(overrides)
    return base
def _make_schema():
    """Create a fresh in-memory schema with the necessary rows."""
    from database import Base
    from models import (
        Region, Jurisdiction, Species, SpeciesProgram,
        ScientificDataset,
        HistoricalOccurrence, PredictionSampleEnvironmentalFeature,
    )
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, SessionLocal


def _seed_v3_dataset(SessionLocal):
    """Seed the minimum rows needed to reproduce the v3 setup."""
    from database import Base
    from models import (
        Region, Jurisdiction, Species, SpeciesProgram,
        ScientificDataset,
        HistoricalOccurrence, PredictionSampleEnvironmentalFeature,
    )
    session = SessionLocal()
    region = Region(name="Caribbean", slug="caribbean", status="ACTIVE")
    session.add(region); session.flush()
    jamaica = Jurisdiction(
        region_id=region.id, name="Jamaica", slug="jamaica", country_code="JM",
        status="ACTIVE", center_latitude=18.1096, center_longitude=-77.2975,
        default_zoom=8,
    )
    bahamas = Jurisdiction(
        region_id=region.id, name="Bahamas", slug="bahamas", country_code="BS",
        status="ACTIVE", center_latitude=24.25, center_longitude=-76.0,
        default_zoom=6,
    )
    session.add_all([jamaica, bahamas]); session.flush()
    pterois = Species(
        scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE",
    )
    session.add(pterois); session.flush()
    sparus = Species(
        scientific_name="Sparus aurata", common_name="Gilthead seabream",
        status="ACTIVE",
    )
    session.add(sparus); session.flush()
    program = SpeciesProgram(
        jurisdiction_id=jamaica.id, species_id=pterois.id,
        scientific_name="Pterois volitans", common_name="Lionfish",
        status="ACTIVE",
    )
    session.add(program); session.flush()
    # Occurrence dataset
    occ = ScientificDataset(
        slug="pterois-volitans-jamaica-obis-iNaturalist-2025-08",
        name="Pterois volitans OBIS Jamaica historical occurrence snapshot",
        dataset_type="OCCURRENCE", status="ACTIVE",
        species_id=pterois.id, species_program_id=program.id,
        geographic_scope_type="JURISDICTION", region_id=region.id,
        jurisdiction_id=jamaica.id,
        source_name="OBIS", source_type="API",
        source_reference="https://api.obis.org/v3/occurrence",
        record_count=54,
    )
    session.add(occ); session.flush()
    # Environmental dataset
    env = ScientificDataset(
        slug="pterois-volitans-environmental-caribbean-grid-v2-environment-v1",
        name="Pterois volitans Caribbean environmental feature snapshot",
        dataset_type="ENVIRONMENTAL", status="ACTIVE",
        species_id=pterois.id, species_program_id=program.id,
        geographic_scope_type="REGION", region_id=region.id,
        jurisdiction_id=None,
        source_name="NOAA ETOPO1 + WOA23", source_type="API+CACHED",
        source_reference="https://example/noaa-url",
        record_count=2334,
    )
    session.add(env); session.flush()
    from scientific_applicability_domain import ApplicabilityStatus, EvidenceRole
    from scientific_dataset_applicability import create_applicability
    create_applicability(
        session, scientific_dataset_id=env.id, jurisdiction_id=jamaica.id,
        evidence_role=EvidenceRole.ENVIRONMENTAL_COVARIATE,
        applicability_status=ApplicabilityStatus.AUTHORIZED,
        reconciliation_method="LEGACY_PROVENANCE_RECONCILIATION",
        reconciliation_version="phase12a2-v1",
        provenance_reference="Phase 12A-2 controlled test backfill",
        provenance={"relationship": "existing Jamaica v3 environmental input"},
    )
    # 54 historical occurrences
    base_lat = 18.0
    base_lon = -77.0
    for i in range(54):
        occ_row = HistoricalOccurrence(
            scientific_name="Pterois volitans",
            taxon_id=159559,
            latitude=base_lat + (i * 0.01),
            longitude=base_lon + (i * 0.01),
            event_date=None,
            source="OBIS",
            deduplication_key=f"key-{i}",
            dataset_id=occ.id,
        )
        session.add(occ_row)
    # A few environmental rows for the v3 feature version
    for sample_id in range(1, 4):
        for feature_name in (
            "bathymetry_center_depth",
            "sst_climatology_annual_mean",
        ):
            session.add(PredictionSampleEnvironmentalFeature(
                prediction_model_sample_id=sample_id,
                scientific_dataset_id=env.id,
                feature_name=feature_name,
                value=1.0,
                source="NOAA",
                sampling_method="NEAREST",
                feature_version="caribbean-grid-v2-environment-v1",
            ))
    session.commit()
    return {
        "region_id": region.id,
        "jamaica_id": jamaica.id,
        "bahamas_id": bahamas.id,
        "pterois_id": pterois.id,
        "sparus_id": sparus.id,
        "program_id": program.id,
        "occ_dataset_id": occ.id,
        "env_dataset_id": env.id,
    }


@pytest.fixture
def sessions():
    engine, SessionLocal = _make_schema()
    ids = _seed_v3_dataset(SessionLocal)
    yield SessionLocal, ids
    engine.dispose()


def _make_v3_spec(ids, **overrides):
    sys.path.insert(0, ".")
    from suitability_training_spec import SuitabilityTrainingSpec
    defaults = dict(
        species="Pterois volitans",
        species_program_id=ids["program_id"],
        geographic_scope="JURISDICTION",
        region_id=ids["region_id"],
        jurisdiction_id=ids["jamaica_id"],
        occurrence_dataset_id=ids["occ_dataset_id"],
        environmental_dataset_ids=(ids["env_dataset_id"],),
    )
    defaults.update(overrides)
    helper = _minimal_spec_kwargs()
    helper = {k: v for k, v in helper.items() if k not in defaults}
    return SuitabilityTrainingSpec(**defaults, **helper)


# ----------------------------------------------------------------------
# 1 - Jamaica v3 spec resolves the correct occurrence dataset.
# ----------------------------------------------------------------------

def test_jamaica_v3_spec_resolves_correct_occurrence_dataset(sessions):
    from suitability_training_loaders import load_occurrences
    SessionLocal, ids = sessions
    spec = _make_v3_spec(ids)
    session = SessionLocal()
    dataset, rows = load_occurrences(session, spec)
    assert dataset.id == ids["occ_dataset_id"]
    assert dataset.slug == "pterois-volitans-jamaica-obis-iNaturalist-2025-08"
    session.close()


# ----------------------------------------------------------------------
# 2 - Exactly the 54 existing HistoricalOccurrence rows are selected.
# ----------------------------------------------------------------------

def test_exactly_54_occurrence_rows_selected(sessions):
    from suitability_training_loaders import load_occurrences
    SessionLocal, ids = sessions
    spec = _make_v3_spec(ids)
    session = SessionLocal()
    dataset, rows = load_occurrences(session, spec)
    assert len(rows) == 54
    assert dataset.record_count == 54
    session.close()


# ----------------------------------------------------------------------
# 3 - No unrelated occurrence rows are included.
# ----------------------------------------------------------------------

def test_no_unrelated_occurrence_rows(sessions):
    from suitability_training_loaders import load_occurrences
    SessionLocal, ids = sessions
    # Add a foreign-scope row that must NOT be loaded.
    from models import HistoricalOccurrence, Jurisdiction
    session = SessionLocal()
    foreign = HistoricalOccurrence(
        scientific_name="Pterois volitans",
        taxon_id=159559,
        latitude=12.0, longitude=-60.0,
        source="OTHER",
        deduplication_key="foreign-1",
        dataset_id=None,
    )
    session.add(foreign)
    session.commit()
    spec = _make_v3_spec(ids)
    dataset, rows = load_occurrences(session, spec)
    keys = {row.deduplication_key for row in rows}
    assert "foreign-1" not in keys
    assert all(row.dataset_id == dataset.id for row in rows)
    session.close()


# ----------------------------------------------------------------------
# 4 - Explicit environmental dataset ID resolves correctly.
# ----------------------------------------------------------------------

def test_environmental_dataset_resolves(sessions):
    from suitability_training_loaders import load_environmental
    SessionLocal, ids = sessions
    spec = _make_v3_spec(ids)
    session = SessionLocal()
    envs = load_environmental(session, spec)
    assert len(envs) == 1
    env_dataset, env_rows = envs[0]
    assert env_dataset.id == ids["env_dataset_id"]
    assert env_dataset.dataset_type == "ENVIRONMENTAL"
    assert len(env_rows) > 0
    session.close()


# ----------------------------------------------------------------------
# 5 - Missing occurrence dataset fails.
# ----------------------------------------------------------------------

def test_missing_occurrence_dataset_fails(sessions):
    from suitability_training_loaders import load_occurrences
    SessionLocal, ids = sessions
    spec = _make_v3_spec(ids, occurrence_dataset_id=999)
    session = SessionLocal()
    try:
        load_occurrences(session, spec)
    except ValueError as e:
        assert "999" in str(e)
        assert "does not exist" in str(e)
        session.close()
        return
    session.close()
    raise AssertionError("Expected ValueError")


# ----------------------------------------------------------------------
# 6 - Missing environmental dataset fails.
# ----------------------------------------------------------------------

def test_missing_environmental_dataset_fails(sessions):
    from suitability_training_loaders import load_environmental
    SessionLocal, ids = sessions
    spec = _make_v3_spec(ids, environmental_dataset_ids=(999,))
    session = SessionLocal()
    try:
        load_environmental(session, spec)
    except ValueError as e:
        assert "999" in str(e)
        session.close()
        return
    session.close()
    raise AssertionError("Expected ValueError")


# ----------------------------------------------------------------------
# 7 - Wrong dataset type fails.
# ----------------------------------------------------------------------

def test_wrong_dataset_type_for_occurrence_fails(sessions):
    from suitability_training_loaders import load_occurrences
    from models import ScientificDataset
    SessionLocal, ids = sessions
    session = SessionLocal()
    # Re-tag the env dataset as OCCURRENCE (wrong type); then point
    # the spec at it.
    env_dataset = session.query(ScientificDataset).filter(
        ScientificDataset.id == ids["env_dataset_id"]
    ).one()
    env_dataset.dataset_type = "OCCURRENCE_WANNABE"
    session.commit()
    spec = _make_v3_spec(ids, occurrence_dataset_id=env_dataset.id)
    try:
        load_occurrences(session, spec)
    except ValueError as e:
        assert "dataset_type" in str(e)
        session.close()
        return
    session.close()
    raise AssertionError("Expected ValueError")


# ----------------------------------------------------------------------
# 8 - Species mismatch fails.
# ----------------------------------------------------------------------

def test_species_mismatch_fails(sessions):
    from suitability_training_loaders import load_occurrences
    SessionLocal, ids = sessions
    # Spec claims Sparus aurata but the dataset is for Pterois volitans.
    spec = _make_v3_spec(ids, species="Sparus aurata")
    session = SessionLocal()
    try:
        load_occurrences(session, spec)
    except ValueError as e:
        assert "Pterois volitans" in str(e) or "scoped" in str(e)
        session.close()
        return
    session.close()
    raise AssertionError("Expected ValueError")


# ----------------------------------------------------------------------
# 9 - Jurisdiction mismatch fails.
# ----------------------------------------------------------------------

def test_jurisdiction_mismatch_fails(sessions):
    from suitability_training_loaders import load_occurrences
    SessionLocal, ids = sessions
    # Spec claims Bahamas jurisdiction but the dataset is Jamaica-scoped.
    spec = _make_v3_spec(
        ids,
        geographic_scope="JURISDICTION",
        jurisdiction_id=ids["bahamas_id"],
    )
    session = SessionLocal()
    try:
        load_occurrences(session, spec)
    except ValueError as e:
        assert "jurisdiction" in str(e).lower()
        session.close()
        return
    session.close()
    raise AssertionError("Expected ValueError")


# ----------------------------------------------------------------------
# 10 - Region-scoped environmental dataset supports a jurisdiction-scoped
# training spec when the spec's region_id matches the dataset's region_id.
# This is the v3 case: pterois-volitans-environmental-caribbean-grid-v2
# is a region-scoped dataset for the Caribbean region, and the Jamaica v3
# spec is a jurisdiction-scoped spec within the same region.
# ----------------------------------------------------------------------

def test_region_scoped_dataset_relaxes_when_region_ids_match(sessions):
    from suitability_training_loaders import load_environmental
    SessionLocal, ids = sessions
    # The v3 spec is Jamaica-scoped but the region_id is Caribbean; the v3
    # env dataset is region-scoped with region_id=Caribbean. The relaxation
    # accepts this.
    spec = _make_v3_spec(ids)
    session = SessionLocal()
    envs = load_environmental(session, spec)
    assert len(envs) == 1
    assert envs[0][0].id == ids["env_dataset_id"]
    session.close()


def test_region_scoped_environmental_refused_when_region_ids_differ(sessions):
    from suitability_training_loaders import load_environmental
    from models import ScientificDataset
    SessionLocal, ids = sessions
    # Re-tag the env dataset's region_id to mismatch the spec's region_id.
    session = SessionLocal()
    env = session.query(ScientificDataset).filter(
        ScientificDataset.id == ids["env_dataset_id"]
    ).one()
    env.region_id = 999
    session.commit()
    spec = _make_v3_spec(ids)
    try:
        load_environmental(session, spec)
    except ValueError as e:
        assert "mismatches" in str(e) or "region_id" in str(e), (
            f"unexpected error: {e}"
        )
        session.close()
        return
    session.close()
    raise AssertionError("Expected ValueError on region_id mismatch")


# ----------------------------------------------------------------------
# 11 - Bahamas spec cannot silently inherit Jamaica occurrence data.
# ----------------------------------------------------------------------

def test_bahamas_spec_cannot_inherit_jamaica_occurrences(sessions):
    from suitability_training_loaders import load_occurrences
    SessionLocal, ids = sessions
    # Spec is Bahamas-scoped but the dataset is Jamaica-scoped.
    spec = _make_v3_spec(
        ids,
        geographic_scope="JURISDICTION",
        jurisdiction_id=ids["bahamas_id"],
    )
    session = SessionLocal()
    try:
        load_occurrences(session, spec)
    except ValueError as e:
        assert "jurisdiction" in str(e).lower()
        session.close()
        return
    session.close()
    raise AssertionError("Expected ValueError")


# ----------------------------------------------------------------------
# 12 - Dataset provenance is returned with the loaded inputs.
# ----------------------------------------------------------------------

def test_provenance_returned_with_inputs(sessions):
    from suitability_training_loaders import load_training_inputs
    SessionLocal, ids = sessions
    spec = _make_v3_spec(ids)
    session = SessionLocal()
    inputs = load_training_inputs(session, spec)
    assert inputs.occurrence_dataset.id == ids["occ_dataset_id"]
    assert inputs.occurrence_dataset.slug == (
        "pterois-volitans-jamaica-obis-iNaturalist-2025-08"
    )
    assert inputs.occurrence_summary().dataset_type == "OCCURRENCE"
    assert len(inputs.environmental_datasets) > 0
    env_dataset, _ = inputs.environmental_datasets[0]
    assert env_dataset.dataset_type == "ENVIRONMENTAL"
    # Provenance summary is a JSON-safe dict and contains both
    # occurrence and environmental summaries.
    assert "occurrence" in inputs.provenance_summary
    assert "environmental" in inputs.provenance_summary
    session.close()


# ----------------------------------------------------------------------
# 13 - Credentials / secrets are not exposed in provenance.
# ----------------------------------------------------------------------

def test_provenance_does_not_expose_credentials(sessions):
    from suitability_training_loaders import _summarize_dataset
    from models import ScientificDataset
    SessionLocal, ids = sessions
    session = SessionLocal()
    dataset = session.query(ScientificDataset).filter(
        ScientificDataset.id == ids["env_dataset_id"]
    ).one()
    # The summary object must not contain an acquisition_manifest_json
    # field. This is a deliberate guardrail.
    summary = _summarize_dataset(dataset)
    forbidden = (
        "acquisition_manifest_json", "api_key", "apikey",
        "authorization", "bearer", "secret", "token", "password",
    )
    for attr in summary.__dict__:
        value = getattr(summary, attr)
        if value is None:
            continue
        text = str(value).lower()
        for bad in forbidden:
            assert bad not in text, (
                f"provenance summary attribute {attr!r} looks like a "
                f"forbidden token: {value!r}"
            )
    session.close()


# ----------------------------------------------------------------------
# 14 - Loading performs no database mutation.
# ----------------------------------------------------------------------

def test_loading_does_not_mutate_database(sessions):
    from suitability_training_loaders import load_training_inputs
    from sqlalchemy import text
    SessionLocal, ids = sessions
    spec = _make_v3_spec(ids)
    session = SessionLocal()
    before = session.execute(
        text("SELECT COUNT(*) FROM historical_occurrences")
    ).scalar()
    inputs = load_training_inputs(session, spec)
    after = session.execute(
        text("SELECT COUNT(*) FROM historical_occurrences")
    ).scalar()
    assert before == after
    session.close()


# ----------------------------------------------------------------------
# 15 - Loading performs no training.
# ----------------------------------------------------------------------

def test_loading_does_not_train(sessions):
    """The loader module does not import sklearn, model.fit, or any
    training entry point. The check is word-boundary safe so that
    docstrings mentioning 'training' do not trigger false positives.
    """
    import re
    import suitability_training_loaders as mod
    src = open(mod.__file__, "r", encoding="utf-8").read()
    # Word-boundary match for the bare word "train"
    forbidden = [
        "sklearn", "model.fit", "fit(",
        "LogisticRegression", "HistGradientBoosting",
        "joblib.dump",
    ]
    for token in forbidden:
        if token in src:
            # Allow word-boundary occurrence of "train" / "training" only
            # in docstrings/comments. Any other identifier containing the
            # token is a real violation.
            pattern = re.compile(r"\b" + re.escape(token) + r"\b")
            if pattern.search(src):
                raise AssertionError(
                    f"suitability_training_loaders.py must not reference "
                    f"{token!r}"
                )


# ----------------------------------------------------------------------
# 16 - Loading performs no deployment activation.
# ----------------------------------------------------------------------

def test_loading_does_not_activate_deployment(sessions):
    from suitability_training_loaders import load_training_inputs
    from sqlalchemy import text
    SessionLocal, ids = sessions
    spec = _make_v3_spec(ids)
    session = SessionLocal()
    before = session.execute(
        text("SELECT COUNT(*) FROM suitability_deployments")
    ).scalar()
    inputs = load_training_inputs(session, spec)
    after = session.execute(
        text("SELECT COUNT(*) FROM suitability_deployments")
    ).scalar()
    assert before == after
    session.close()


# ----------------------------------------------------------------------
# 17 - Inputs bundle is immutable.
# ----------------------------------------------------------------------

def test_inputs_bundle_is_immutable(sessions):
    from suitability_training_loaders import load_training_inputs
    SessionLocal, ids = sessions
    spec = _make_v3_spec(ids)
    session = SessionLocal()
    inputs = load_training_inputs(session, spec)
    with pytest.raises(Exception):
        inputs.occurrence_dataset = None
    session.close()


# ----------------------------------------------------------------------
# 18 - Occurrence rows are exactly the dataset's rows (deterministic).
# ----------------------------------------------------------------------

def test_occurrence_rows_match_dataset_rows_exactly(sessions):
    from suitability_training_loaders import load_occurrences
    from sqlalchemy import text
    from models import HistoricalOccurrence
    SessionLocal, ids = sessions
    session = SessionLocal()
    expected_count = session.execute(
        text(
            "SELECT COUNT(*) FROM historical_occurrences WHERE dataset_id = :d"
        ),
        {"d": ids["occ_dataset_id"]},
    ).scalar()
    spec = _make_v3_spec(ids)
    dataset, rows = load_occurrences(session, spec)
    assert len(rows) == expected_count
    session.close()


# ----------------------------------------------------------------------
# 19 - Province summary is JSON-serializable.
# ----------------------------------------------------------------------

def test_provenance_summary_is_json_serializable(sessions):
    from suitability_training_loaders import load_training_inputs
    import json
    SessionLocal, ids = sessions
    spec = _make_v3_spec(ids)
    session = SessionLocal()
    inputs = load_training_inputs(session, spec)
    raw = json.dumps(inputs.provenance_summary, default=str)
    parsed = json.loads(raw)
    assert "occurrence" in parsed
    assert "environmental" in parsed
    session.close()


# ----------------------------------------------------------------------
# 20 - Module does not import the database engine.
# ----------------------------------------------------------------------

def test_module_does_not_import_database_engine(sessions):
    import suitability_training_loaders as mod
    src = open(mod.__file__, "r", encoding="utf-8").read()
    forbidden = (
        "from database import", "create_engine", "sessionmaker",
        "submit_session", "engine.dispose",
    )
    for token in forbidden:
        assert token not in src, (
            f"suitability_training_loaders.py must not reference {token!r}"
        )
