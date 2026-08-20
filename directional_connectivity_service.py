import math

from geographic_utils import haversine_km
from ocean_current_service import OceanCurrentLookupService


INTERPRETATION_WARNING = (
    "Experimental environmental directional connectivity only. This is not "
    "lionfish movement, spread, colonization, adult movement, or larval "
    "dispersal probability. A single current vector does not represent a "
    "trajectory; currents vary spatially, temporally, and with depth."
)


def initial_great_circle_bearing(
    source_latitude, source_longitude, candidate_latitude, candidate_longitude
):
    latitude_a = math.radians(source_latitude)
    latitude_b = math.radians(candidate_latitude)
    longitude_delta = math.radians(candidate_longitude - source_longitude)
    east_component = math.sin(longitude_delta) * math.cos(latitude_b)
    north_component = (
        math.cos(latitude_a) * math.sin(latitude_b)
        - math.sin(latitude_a) * math.cos(latitude_b) * math.cos(longitude_delta)
    )
    return (math.degrees(math.atan2(east_component, north_component)) + 360) % 360


def smallest_angular_difference(bearing_a, bearing_b):
    return abs((bearing_a - bearing_b + 180) % 360 - 180)


def alignment_from_bearings(current_bearing, candidate_bearing):
    difference = smallest_angular_difference(current_bearing, candidate_bearing)
    return max(-1.0, min(1.0, math.cos(math.radians(difference))))


class DirectionalConnectivityService:

    def __init__(self, current_service=None):
        self.current_service = current_service or OceanCurrentLookupService()

    @staticmethod
    def calculate_with_current(
        source_latitude,
        source_longitude,
        candidate_latitude,
        candidate_longitude,
        current,
    ):
        distance = haversine_km(
            source_latitude, source_longitude,
            candidate_latitude, candidate_longitude,
        )
        candidate_bearing = initial_great_circle_bearing(
            source_latitude, source_longitude,
            candidate_latitude, candidate_longitude,
        )
        base = {
            "source": {"latitude": source_latitude, "longitude": source_longitude},
            "candidate": {"latitude": candidate_latitude, "longitude": candidate_longitude},
            "source_to_candidate_distance_km": distance,
            "source_to_candidate_bearing_degrees": candidate_bearing,
            "u": current.get("u"),
            "v": current.get("v"),
            "current_speed": current.get("speed"),
            "current_toward_bearing_degrees": current.get("toward_bearing_degrees"),
            "current_source_latitude": current.get("source_latitude"),
            "current_source_longitude": current.get("source_longitude"),
            "current_lookup_distance_km": current.get("spatial_distance_km"),
            "current_timestamp": current.get("source_timestamp"),
            "current_depth_m": current.get("source_depth_m"),
            "provider": current.get("provider"),
            "product": current.get("product"),
            "dataset_id": current.get("dataset_id"),
            "current_lookup_status": current.get("status"),
            "current_sampling_method": current.get("sampling_method"),
            "angular_difference_degrees": None,
            "alignment": None,
            "downstream_alignment": None,
            "speed_weighted_alignment": None,
            "speed_weighted_alignment_label": (
                "diagnostic environmental transport measure"
            ),
            "interpretation_warning": INTERPRETATION_WARNING,
        }
        if current.get("status") != "VALID":
            return base
        difference = smallest_angular_difference(
            current["toward_bearing_degrees"], candidate_bearing
        )
        alignment = alignment_from_bearings(
            current["toward_bearing_degrees"], candidate_bearing
        )
        downstream = max(0.0, alignment)
        base.update({
            "angular_difference_degrees": difference,
            "alignment": alignment,
            "downstream_alignment": downstream,
            "speed_weighted_alignment": downstream * current["speed"],
        })
        return base

    def calculate_directional_connectivity(
        self,
        source_latitude,
        source_longitude,
        candidate_latitude,
        candidate_longitude,
        timestamp,
        depth,
        provider=None,
    ):
        current = self.current_service.get_current(
            source_latitude, source_longitude, timestamp, depth, provider
        )
        return self.calculate_with_current(
            source_latitude, source_longitude,
            candidate_latitude, candidate_longitude,
            current,
        )
