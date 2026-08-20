import csv
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import gzip
import io
import math
from threading import Lock
from urllib.parse import quote

import requests

from geographic_utils import haversine_km


SST_SOURCE = (
    "NOAA CoastWatch Geo-polar Blended SST Daily"
)
SALINITY_SOURCE = (
    "NOAA CoastWatch SMOS SSS Daily"
)
SALINITY_CLIMATOLOGY_SOURCE = (
    "NOAA World Ocean Atlas 2018 Monthly Salinity Climatology"
)
DEPTH_SOURCE = "NOAA ETOPO1"

SST_URL = (
    "https://coastwatch.noaa.gov/erddap/griddap/"
    "noaacwBLENDEDCsstDaily.csvp"
)
SALINITY_URL = (
    "https://coastwatch.noaa.gov/erddap/griddap/"
    "noaacwSMOSsssDaily.csvp"
)
DEPTH_URL = (
    "https://gis.ngdc.noaa.gov/arcgis/rest/services/"
    "etopo1/MapServer/identify"
)
WOA_SALINITY_URL = (
    "https://www.ncei.noaa.gov/data/oceans/woa/WOA18/"
    "DATA/salinity/csv/decav/0.25/"
    "woa18_decav_s{month:02d}mn04.csv.gz"
)


class EnvironmentalFeatureService:

    def __init__(self, timeout=30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "marine-monitoring-environmental-prototype/0.1"
            )
        })
        self._woa_month_points = {}
        self._woa_month_index = {}
        self._woa_cache_lock = Lock()
        self.daily_provider_enabled = True
        self.nearest_fallbacks_enabled = True

    @staticmethod
    def _parse_erddap_value(response, field):
        response.raise_for_status()
        rows = list(csv.DictReader(
            io.StringIO(response.text)
        ))

        if not rows:
            return None

        raw_value = rows[0].get(field)

        if raw_value is None:
            return None

        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None

        return value if math.isfinite(value) else None

    def _erddap_point(self, url, query, field):
        encoded_query = quote(
            query,
            safe="[](),:.-_",
        )
        response = self.session.get(
            f"{url}?{encoded_query}",
            timeout=self.timeout,
        )
        return self._parse_erddap_value(
            response,
            field,
        )

    @lru_cache(maxsize=4096)
    def _get_sst(self, latitude, longitude, date_text):
        if not self.daily_provider_enabled:
            raise requests.ConnectionError(
                "Daily CoastWatch provider disabled after health-check failure."
            )
        query = (
            "analysed_sst"
            f"[({date_text})]"
            f"[({latitude})]"
            f"[({longitude})]"
        )
        return self._erddap_point(
            SST_URL,
            query,
            "analysed_sst (degree_C)",
        )

    @lru_cache(maxsize=4096)
    def _get_salinity(
        self,
        latitude,
        longitude,
        date_text,
    ):
        if not self.daily_provider_enabled:
            raise requests.ConnectionError(
                "Daily CoastWatch provider disabled after health-check failure."
            )
        query = (
            "sss"
            f"[({date_text})]"
            "[(0.0)]"
            f"[({latitude})]"
            f"[({longitude})]"
        )
        return self._erddap_point(
            SALINITY_URL,
            query,
            "sss (PSU)",
        )

    @staticmethod
    def _neighbor_coordinates(
        latitude,
        longitude,
        distances,
    ):
        coordinates = []

        for distance in distances:
            coordinates.extend([
                (latitude - distance, longitude),
                (latitude + distance, longitude),
                (latitude, longitude - distance),
                (latitude, longitude + distance),
                (latitude - distance, longitude - distance),
                (latitude - distance, longitude + distance),
                (latitude + distance, longitude - distance),
                (latitude + distance, longitude + distance),
            ])

        return coordinates

    @staticmethod
    def _nearest_valid(
        fetch,
        origin_latitude,
        origin_longitude,
        coordinates,
    ):
        candidates = []

        def fetch_candidate(coordinate):
            latitude, longitude = coordinate

            try:
                value = fetch(latitude, longitude)
            except requests.RequestException:
                return None

            if value is None:
                return None

            return (
                value,
                haversine_km(
                    origin_latitude,
                    origin_longitude,
                    latitude,
                    longitude,
                ),
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            for result in executor.map(
                fetch_candidate,
                coordinates,
            ):
                if result is not None:
                    candidates.append(result)

        return (
            min(candidates, key=lambda item: item[1])
            if candidates else None
        )

    def _load_woa_month(self, month):
        with self._woa_cache_lock:
            if month in self._woa_month_points:
                return self._woa_month_points[month]

            try:
                response = self.session.get(
                    WOA_SALINITY_URL.format(month=month),
                    timeout=(15, 180),
                )
                response.raise_for_status()
            except requests.RequestException:
                # Cache provider failure for this run so waiting worker threads
                # do not retry the same unavailable monthly archive serially.
                self._woa_month_points[month] = []
                self._woa_month_index[month] = {}
                raise
            points = []

            with gzip.GzipFile(
                fileobj=io.BytesIO(response.content)
            ) as compressed_file:
                reader = csv.reader(
                    io.TextIOWrapper(
                        compressed_file,
                        encoding="utf-8",
                    )
                )

                for row in reader:
                    if not row or row[0].startswith("#"):
                        continue

                    try:
                        latitude = float(row[0])
                        longitude = float(row[1])
                    except (IndexError, ValueError):
                        continue

                    # Cache only the prototype Caribbean training extent, while
                    # retaining Jamaica coverage used by historical monitoring.
                    if not (9.0 <= latitude <= 28.0 and -89.0 <= longitude <= -59.0):
                        continue

                    try:
                        salinity = float(row[2])
                    except (IndexError, ValueError):
                        continue

                    if math.isfinite(salinity):
                        points.append((latitude, longitude, salinity))

            self._woa_month_points[month] = points
            index = {}
            for point in points:
                key = (round(point[0] * 4), round(point[1] * 4))
                index.setdefault(key, []).append(point)
            self._woa_month_index[month] = index
            return points

    def _get_woa_salinity(
        self,
        latitude,
        longitude,
        month,
    ):
        candidates = []

        self._load_woa_month(month)
        index = self._woa_month_index[month]
        latitude_key = round(latitude * 4)
        longitude_key = round(longitude * 4)
        nearby_points = []
        for latitude_offset in range(-2, 3):
            for longitude_offset in range(-2, 3):
                nearby_points.extend(index.get((
                    latitude_key + latitude_offset,
                    longitude_key + longitude_offset,
                ), ()))

        for point_latitude, point_longitude, value in nearby_points:
            distance_km = haversine_km(
                latitude,
                longitude,
                point_latitude,
                point_longitude,
            )

            if distance_km <= 50:
                candidates.append((value, distance_km))

        return (
            min(candidates, key=lambda item: item[1])
            if candidates else None
        )

    @lru_cache(maxsize=4096)
    def _get_elevation(self, latitude, longitude):
        extent_delta = 0.01
        response = self.session.get(
            DEPTH_URL,
            params={
                "geometry": f"{longitude},{latitude}",
                "geometryType": "esriGeometryPoint",
                "sr": 4326,
                "layers": "all:1",
                "tolerance": 1,
                "mapExtent": (
                    f"{longitude - extent_delta},"
                    f"{latitude - extent_delta},"
                    f"{longitude + extent_delta},"
                    f"{latitude + extent_delta}"
                ),
                "imageDisplay": "400,400,96",
                "returnGeometry": "false",
                "f": "json",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        results = response.json().get("results", [])

        if not results:
            return None

        raw_elevation = results[0].get(
            "attributes",
            {},
        ).get("Stretch.Pixel Value")

        try:
            elevation = float(raw_elevation)
        except (TypeError, ValueError):
            return None

        if not math.isfinite(elevation):
            return None

        return elevation

    @lru_cache(maxsize=4096)
    def _get_depth(self, latitude, longitude):
        elevation = self._get_elevation(latitude, longitude)

        if elevation is None or elevation >= 0:
            return None

        return abs(elevation)

    def classify_marine_coordinate(self, latitude, longitude):
        """Classify an ETOPO location without treating failures as land."""
        try:
            elevation = self._get_elevation(
                round(float(latitude), 6),
                round(float(longitude), 6),
            )
        except requests.RequestException as error:
            return {
                "classification": "UNAVAILABLE",
                "depth": None,
                "source": DEPTH_SOURCE,
                "error": str(error),
            }

        if elevation is None:
            classification = "UNAVAILABLE"
            depth = None
        elif elevation < 0:
            classification = "MARINE"
            depth = abs(elevation)
        else:
            classification = "TERRESTRIAL"
            depth = None

        return {
            "classification": classification,
            "depth": depth,
            "source": DEPTH_SOURCE,
            "error": None,
        }

    def get_features(
        self,
        latitude,
        longitude,
        date=None,
    ):
        date_text = (
            date.strftime("%Y-%m-%dT%H:%M:%SZ")
            if date is not None
            else None
        )
        features = {
            "sst": None,
            "salinity": None,
            "depth": None,
            "sst_source": SST_SOURCE,
            "salinity_source": SALINITY_SOURCE,
            "depth_source": DEPTH_SOURCE,
            "sst_distance_km": None,
            "salinity_distance_km": None,
            "depth_distance_km": None,
            "sst_sampling_method": "MISSING",
            "salinity_sampling_method": "MISSING",
            "depth_sampling_method": "MISSING",
            "depth_quality_flag": "MISSING",
        }
        errors = {}
        latitude = round(float(latitude), 6)
        longitude = round(float(longitude), 6)

        if date_text is None:
            errors["sst"] = "Occurrence date unavailable."
            errors["salinity"] = "Occurrence date unavailable."
        else:
            try:
                features["sst"] = self._get_sst(
                    latitude,
                    longitude,
                    date_text,
                )

                if features["sst"] is not None:
                    features["sst_distance_km"] = 0.0
                    features["sst_sampling_method"] = "EXACT"
                else:
                    nearest_sst = self._nearest_valid(
                        lambda sample_latitude, sample_longitude:
                            self._get_sst(
                                sample_latitude,
                                sample_longitude,
                                date_text,
                            ),
                        latitude,
                        longitude,
                        self._neighbor_coordinates(
                            latitude,
                            longitude,
                            (0.05, 0.1),
                        ),
                    )

                    if nearest_sst is not None:
                        (
                            features["sst"],
                            features["sst_distance_km"],
                        ) = nearest_sst
                        features[
                            "sst_sampling_method"
                        ] = "NEAREST_VALID"
            except requests.RequestException as error:
                errors["sst"] = str(error)

            try:
                features["salinity"] = self._get_salinity(
                    latitude,
                    longitude,
                    date_text,
                )

                if features["salinity"] is not None:
                    features["salinity_distance_km"] = 0.0
                    features[
                        "salinity_sampling_method"
                    ] = "EXACT"
                else:
                    nearest_salinity = self._nearest_valid(
                        lambda sample_latitude, sample_longitude:
                            self._get_salinity(
                                sample_latitude,
                                sample_longitude,
                                date_text,
                            ),
                        latitude,
                        longitude,
                        self._neighbor_coordinates(
                            latitude,
                            longitude,
                            (0.25,),
                        ),
                    )

                    if nearest_salinity is not None:
                        (
                            features["salinity"],
                            features["salinity_distance_km"],
                        ) = nearest_salinity
                        features[
                            "salinity_sampling_method"
                        ] = "NEAREST_VALID"

                if features["salinity"] is None:
                    woa_salinity = self._get_woa_salinity(
                        latitude,
                        longitude,
                        date.month,
                    )

                    if woa_salinity is not None:
                        (
                            features["salinity"],
                            features["salinity_distance_km"],
                        ) = woa_salinity
                        features["salinity_source"] = (
                            SALINITY_CLIMATOLOGY_SOURCE
                        )
                        features[
                            "salinity_sampling_method"
                        ] = "NEAREST_VALID"
            except requests.RequestException as error:
                errors["salinity"] = str(error)

            # The daily service can be unavailable independently of the WOA
            # climatology archive, so a transport failure must not suppress
            # the established fallback provider.
            if features["salinity"] is None:
                try:
                    woa_salinity = self._get_woa_salinity(
                        latitude,
                        longitude,
                        date.month,
                    )
                    if woa_salinity is not None:
                        (
                            features["salinity"],
                            features["salinity_distance_km"],
                        ) = woa_salinity
                        features["salinity_source"] = SALINITY_CLIMATOLOGY_SOURCE
                        features["salinity_sampling_method"] = "NEAREST_VALID"
                except requests.RequestException as error:
                    errors["salinity"] = str(error)

        try:
            features["depth"] = self._get_depth(
                latitude,
                longitude,
            )

            if features["depth"] is not None:
                features["depth_distance_km"] = 0.0
                features["depth_sampling_method"] = "EXACT"
                features["depth_quality_flag"] = "OK"
            elif self.nearest_fallbacks_enabled:
                nearest_depth = self._nearest_valid(
                    self._get_depth,
                    latitude,
                    longitude,
                    self._neighbor_coordinates(
                        latitude,
                        longitude,
                        (0.02, 0.05, 0.1),
                    ),
                )

                if nearest_depth is not None:
                    (
                        features["depth"],
                        features["depth_distance_km"],
                    ) = nearest_depth
                    features[
                        "depth_sampling_method"
                    ] = "NEAREST_VALID"
                    features["depth_quality_flag"] = (
                        "DISTANT_FALLBACK"
                        if nearest_depth[1] > 10
                        else "NEARBY_FALLBACK"
                    )
        except requests.RequestException as error:
            errors["depth"] = str(error)

        features["errors"] = errors
        return features
