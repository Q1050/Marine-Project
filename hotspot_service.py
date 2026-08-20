from collections import defaultdict
from math import floor
from datetime import datetime, timezone, timedelta
from monitoring_engine import MonitoringEngine

class HotspotService:

    def __init__(
        self,
        grid_size=0.1,
    ):
        self.grid_size = grid_size
        self.monitoring_engine = (
            MonitoringEngine()
        )

    def _grid_cell(
        self,
        latitude,
        longitude,
    ):
        """
        Convert coordinates into a simple
        geographic grid cell.
        """

        lat_cell = (
            floor(
                latitude
                / self.grid_size
            )
            * self.grid_size
        )

        lon_cell = (
            floor(
                longitude
                / self.grid_size
            )
            * self.grid_size
        )

        return (
            round(lat_cell, 4),
            round(lon_cell, 4),
        )


    def aggregate(
        self,
        observations,
    ):

        cells = defaultdict(
            lambda: {
                "total_observations": 0,
                "verified_observations": 0,
                "invasive_observations": 0,
                "confirmed_invasive_observations": 0,
                "ai_supported_invasive_observations": 0,
                "unresolved_observations": 0,
                "species": defaultdict(int),
                "confirmed_observations": 0,
                "ai_supported_observations": 0,
                "unresolved_evidence": 0,
                "species_activity": defaultdict(
                    lambda: {
                        "total": 0,
                        "past_7_days": 0,
                        "past_30_days": 0,
                        "past_90_days": 0,
                        "confirmed": 0,
                        "ai_supported": 0,
                        "unresolved": 0,
                        "regional_context":
                            "INSUFFICIENT_DATA",
                    }
                ),
                "observation_ids": [],
                "past_7_days": 0,
                "past_30_days": 0,
                "past_90_days": 0,
            }
        )


        for observation in observations:
            evidence_level = (
                self.monitoring_engine
                .classify_evidence(
                    observation.get(
                        "identification_status"
                    ),
                    observation.get(
                        "verification_status"
                    ),
                )
            )

            latitude = (
                observation["latitude"]
            )

            longitude = (
                observation["longitude"]
            )

            cell = self._grid_cell(
                latitude,
                longitude,
            )

            data = cells[cell]

            if evidence_level == "CONFIRMED":
                data["confirmed_observations"] += 1
            elif evidence_level == "AI_SUPPORTED":
                data["ai_supported_observations"] += 1
            else:
                data["unresolved_evidence"] += 1

            is_past_7_days = False
            is_past_30_days = False
            is_past_90_days = False

            created_at = observation.get(
                "created_at"
            )

            if created_at:

                if isinstance(
                    created_at,
                    str
                ):
                    try:
                        created_at = (
                            datetime
                            .fromisoformat(
                                created_at
                            )
                        )
                    except ValueError:
                        created_at = None

                if created_at:

                    if (
                        created_at.tzinfo
                        is None
                    ):
                        created_at = (
                            created_at.replace(
                                tzinfo=timezone.utc
                            )
                        )

                    now = datetime.now(
                        timezone.utc
                    )
                    if (
                        created_at
                        >=
                        now
                        - timedelta(days=7)
                    ):
                        data[
                            "past_7_days"
                        ] += 1
                        is_past_7_days = True
                    if (
                        created_at
                        >=
                        now
                        - timedelta(days=30)
                    ):
                        data[
                            "past_30_days"
                        ] += 1
                        is_past_30_days = True

                    if (
                        created_at
                        >=
                        now
                        - timedelta(days=90)
                    ):
                        data[
                            "past_90_days"
                        ] += 1
                        is_past_90_days = True
            data[
                "total_observations"
            ] += 1

            data[
                "observation_ids"
            ].append(
                observation["id"]
            )


            # ------------------------------------------
            # Verification
            # ------------------------------------------

            verification_status = (
                observation.get(
                    "verification_status"
                )
            )

            if verification_status in {
                "CONFIRMED",
                "CORRECTED",
            }:

                data[
                    "verified_observations"
                ] += 1


            # ------------------------------------------
            # Ecological status
            # ------------------------------------------

            if (
                observation.get(
                    "ecological_status"
                )
                == "INVASIVE"
            ):

                data[
                    "invasive_observations"
                ] += 1

                if evidence_level == "CONFIRMED":
                    data[
                        "confirmed_invasive_observations"
                    ] += 1
                elif evidence_level == "AI_SUPPORTED":
                    data[
                        "ai_supported_invasive_observations"
                    ] += 1


            # ------------------------------------------
            # Unresolved
            # ------------------------------------------

            if (
                observation.get(
                    "identification_status"
                )
                == "unresolved"
            ):

                data[
                    "unresolved_observations"
                ] += 1


            # ------------------------------------------
            # Species
            # ------------------------------------------

            species = (
                observation.get("species")
                or observation.get("ai_species")
            )

            if species:

                # Existing overall species count
                data["species"][species] += 1

                # Species-specific temporal activity
                species_data = (
                    data["species_activity"][species]
                )

                species_data["total"] += 1

                if evidence_level == "CONFIRMED":
                    species_data["confirmed"] += 1
                elif evidence_level == "AI_SUPPORTED":
                    species_data["ai_supported"] += 1
                else:
                    species_data["unresolved"] += 1

                regional_context = (
                    self.monitoring_engine
                    .classify_regional_context(
                        observation.get(
                            "regional_evidence"
                        )
                    )
                )
                regional_context_priority = {
                    "INSUFFICIENT_DATA": 0,
                    "NO_REGIONAL_RECORDS": 1,
                    "SPARSE_RECORDS": 2,
                    "ESTABLISHED_RECORDS": 3,
                }

                if (
                    regional_context_priority[
                        regional_context
                    ]
                    > regional_context_priority[
                        species_data[
                            "regional_context"
                        ]
                    ]
                ):
                    species_data[
                        "regional_context"
                    ] = regional_context

                if is_past_7_days:
                    species_data["past_7_days"] += 1

                if is_past_30_days:
                    species_data["past_30_days"] += 1

                if is_past_90_days:
                    species_data["past_90_days"] += 1


        # ==================================================
        # SERIALIZE
        # ==================================================

        hotspots = []


        for (
            latitude,
            longitude
        ), data in cells.items():

            species_counts = dict(
                sorted(
                    data["species"].items(),
                    key=lambda item:
                        item[1],
                    reverse=True,
                )
            )
            species_activity = {}

            for (
                species_name,
                species_data
            ) in data[
                "species_activity"
            ].items():
                species_trend = (
                    self.monitoring_engine.classify_species_trend(
                        species_data["total"],
                        species_data["past_7_days"],
                        species_data["past_30_days"],
                        species_data["past_90_days"],
                    )
                )
                regional_context = species_data[
                    "regional_context"
                ]
                monitoring_interpretation = (
                    self.monitoring_engine
                    .interpret_species_monitoring(
                        species_trend,
                        regional_context,
                        species_data["confirmed"],
                    )
                )

                species_activity[
                    species_name
                ] = {
                    "total":
                        species_data["total"],

                    "past_7_days":
                        species_data[
                            "past_7_days"
                        ],

                    "past_30_days":
                        species_data[
                            "past_30_days"
                        ],

                    "past_90_days":
                        species_data[
                            "past_90_days"
                        ],
                    "evidence": {
                        "confirmed":
                            species_data[
                                "confirmed"
                            ],

                        "ai_supported":
                            species_data[
                                "ai_supported"
                            ],

                        "unresolved":
                            species_data[
                                "unresolved"
                            ],
                    },
                    "activity_status":
                        self.monitoring_engine.classify_activity(
                            species_data["total"],
                            species_data[
                                "past_7_days"
                            ],
                            species_data[
                                "past_30_days"
                            ],
                            species_data[
                                "past_90_days"
                            ],
                        ),
                    "observation_trend":
                        species_trend,
                    "regional_context":
                        regional_context,
                    "monitoring_interpretation":
                        monitoring_interpretation,
                    "trend": species_trend,
                }

            activity_status = (
                self.monitoring_engine.classify_activity(
                    data["total_observations"],
                    data["past_7_days"],
                    data["past_30_days"],
                    data["past_90_days"],
                )
            )

            weighted_invasive_evidence = (
                self.monitoring_engine.compute_weighted_evidence(
                    data[
                        "confirmed_invasive_observations"
                    ],
                    data[
                        "ai_supported_invasive_observations"
                    ],
                )
            )

            invasive_activity = (
                self.monitoring_engine
                .classify_verification_aware_invasive_activity(
                    weighted_invasive_evidence,
                    data["total_observations"],
                )
            )

            invasive_evidence_confidence = (
                self.monitoring_engine
                .classify_invasive_evidence_confidence(
                    data[
                        "confirmed_invasive_observations"
                    ],
                    data[
                        "ai_supported_invasive_observations"
                    ],
                )
            )
            hotspots.append({

                "latitude":
                    round(
                        latitude
                        + self.grid_size / 2,
                        4,
                    ),

                "longitude":
                    round(
                        longitude
                        + self.grid_size / 2,
                        4,
                    ),

                "grid_size":
                    self.grid_size,

                "total_observations":
                    data[
                        "total_observations"
                    ],
                "activity_status":
                    activity_status,

                "invasive_activity":
                    invasive_activity,

                "weighted_invasive_evidence":
                    weighted_invasive_evidence,

                "invasive_evidence_confidence":
                    invasive_evidence_confidence,

                "verified_observations":
                    data[
                        "verified_observations"
                    ],
                "species_activity":
                    species_activity,
                "invasive_observations":
                    data[
                        "invasive_observations"
                    ],

                "unresolved_observations":
                    data[
                        "unresolved_observations"
                    ],

                "species":
                    species_counts,
                "past_7_days":
                    data[
                        "past_7_days"
                    ],

                "past_30_days":
                    data[
                        "past_30_days"
                    ],

                "past_90_days":
                    data[
                        "past_90_days"
                    ],
                "observation_ids":
                    data[
                        "observation_ids"
                    ],
            })


        hotspots.sort(
            key=lambda item:
                item[
                    "total_observations"
                ],
            reverse=True,
        )


        return hotspots
