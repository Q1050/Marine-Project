import math


def haversine_km(
    latitude_a,
    longitude_a,
    latitude_b,
    longitude_b,
):
    """Return the great-circle distance between two coordinates."""
    earth_radius_km = 6371.0088

    latitude_a = math.radians(latitude_a)
    longitude_a = math.radians(longitude_a)
    latitude_b = math.radians(latitude_b)
    longitude_b = math.radians(longitude_b)

    latitude_delta = latitude_b - latitude_a
    longitude_delta = longitude_b - longitude_a

    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude_a)
        * math.cos(latitude_b)
        * math.sin(longitude_delta / 2) ** 2
    )

    return earth_radius_km * 2 * math.atan2(
        math.sqrt(haversine),
        math.sqrt(1 - haversine),
    )
