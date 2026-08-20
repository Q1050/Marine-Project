class MonitoringEngine:
    """
    Converts aggregated observation data into
    monitoring signals.

    These signals describe the observation dataset.
    They are not biological spread predictions.
    """

    def classify_activity(
        self,
        total,
        past_7_days,
        past_30_days,
        past_90_days,
    ):
        if total == 0:
            return "NO_ACTIVITY"

        if (
            past_7_days >= 3
            and past_7_days / total >= 0.5
        ):
            return "EMERGING"

        if (
            past_30_days >= 3
            and past_30_days / total >= 0.5
        ):
            return "ELEVATED"

        if past_30_days > 0:
            return "ACTIVE"

        return "STABLE"


    def classify_invasive_activity(
        self,
        invasive_observations,
        total_observations,
    ):
        if total_observations == 0:
            return "NONE"

        if invasive_observations == 0:
            return "NONE"

        ratio = (
            invasive_observations
            / total_observations
        )

        if (
            invasive_observations >= 3
            and ratio >= 0.5
        ):
            return "HIGH"

        if invasive_observations >= 2:
            return "MODERATE"

        return "LOW"


    def compute_weighted_evidence(
        self,
        confirmed,
        ai_supported,
    ):
        return (
            confirmed * 1.0
            + ai_supported * 0.6
        )


    def classify_verification_aware_invasive_activity(
        self,
        weighted_invasive_evidence,
        total_observations,
    ):
        if total_observations == 0:
            return "NONE"

        if weighted_invasive_evidence == 0:
            return "NONE"

        ratio = (
            weighted_invasive_evidence
            / total_observations
        )

        if (
            weighted_invasive_evidence >= 3
            and ratio >= 0.5
        ):
            return "HIGH"

        if weighted_invasive_evidence >= 2:
            return "MODERATE"

        return "LOW"


    def classify_invasive_evidence_confidence(
        self,
        confirmed,
        ai_supported,
    ):
        return self.classify_evidence_confidence(
            confirmed,
            ai_supported,
        )


    def classify_evidence_confidence(
        self,
        confirmed,
        ai_supported,
    ):
        if confirmed >= 3:
            return "HIGH"

        if confirmed >= 1:
            return "MODERATE"

        if ai_supported > 0:
            return "LOW"

        return "NONE"


    def classify_regional_context(
        self,
        regional_evidence,
    ):
        if not isinstance(regional_evidence, dict):
            return "INSUFFICIENT_DATA"

        species_evidence = regional_evidence.get(
            "species"
        )

        if not isinstance(species_evidence, dict):
            return "INSUFFICIENT_DATA"

        records_50km = species_evidence.get(
            "records_50km"
        )
        records_100km = species_evidence.get(
            "records_100km"
        )

        if (
            not isinstance(records_50km, (int, float))
            or not isinstance(records_100km, (int, float))
        ):
            return "INSUFFICIENT_DATA"

        if (
            records_100km >= 10
            or records_50km >= 5
        ):
            return "ESTABLISHED_RECORDS"

        if records_100km >= 1:
            return "SPARSE_RECORDS"

        return "NO_REGIONAL_RECORDS"


    def interpret_species_monitoring(
        self,
        observation_trend,
        regional_context,
        confirmed,
    ):
        if regional_context == "INSUFFICIENT_DATA":
            return "INSUFFICIENT_REGIONAL_CONTEXT"

        if observation_trend == "NEW_ACTIVITY":
            if regional_context == "ESTABLISHED_RECORDS":
                return "RECENT_REPORTING_EXISTING_RANGE"

            if regional_context == "SPARSE_RECORDS":
                return "NOTABLE_ACTIVITY_SPARSE_HISTORY"

            if regional_context == "NO_REGIONAL_RECORDS":
                if confirmed >= 1:
                    return "POTENTIAL_RANGE_EXPANSION"

                return "UNVERIFIED_OUT_OF_RANGE_REPORT"

        if (
            observation_trend == "INCREASING"
            and regional_context == "ESTABLISHED_RECORDS"
        ):
            return "INCREASED_REPORTING_EXISTING_RANGE"

        return "ROUTINE_MONITORING"


    def classify_species_trend(
        self,
        total,
        past_7_days,
        past_30_days,
        past_90_days,
    ):
        if total == 0:
            return "NO_DATA"

        if past_90_days == 0:
            return "DORMANT"

        if (
            total == past_7_days
            and past_7_days > 0
        ):
            return "NEW_ACTIVITY"

        recent_weekly_rate = (
            past_7_days
        )

        monthly_weekly_rate = (
            past_30_days / 4.285
        )

        quarterly_weekly_rate = (
            past_90_days / 12.857
        )

        if (
            past_30_days >= 3
            and recent_weekly_rate
            > monthly_weekly_rate * 1.5
        ):
            return "INCREASING"

        if past_30_days > 0:
            return "ACTIVE"

        return "STABLE"


    def classify_evidence(
        self,
        identification_status,
        verification_status,
    ):
        """
        Determine how strongly an observation
        should contribute to monitoring signals.
        """

        if verification_status in {
            "CONFIRMED",
            "CORRECTED",
        }:
            return "CONFIRMED"

        if (
            identification_status == "accepted"
            and verification_status == "PENDING"
        ):
            return "AI_SUPPORTED"

        return "UNRESOLVED"

    def build_summary(
        self,
        observations,
        hotspots,
    ):
        total_observations = len(
            observations
        )

        verified_observations = 0
        pending_review = 0
        invasive_observations = 0
        unresolved_identifications = 0

        species = set()

        for observation in observations:

            verification_status = (
                observation.get(
                    "verification_status"
                )
            )

            if verification_status in {
                "CONFIRMED",
                "CORRECTED",
            }:
                verified_observations += 1

            if verification_status == "PENDING":
                pending_review += 1

            if (
                observation.get(
                    "ecological_status"
                )
                == "INVASIVE"
            ):
                invasive_observations += 1

            if (
                observation.get(
                    "identification_status"
                )
                == "unresolved"
            ):
                unresolved_identifications += 1

            species_name = (
                observation.get("species")
                or observation.get(
                    "ai_species"
                )
            )

            if species_name:
                species.add(
                    species_name
                )

        active_hotspots = 0
        high_invasive_hotspots = 0

        species_signals = []
        signal_priority = {
            "POTENTIAL_RANGE_EXPANSION": 1,
            "UNVERIFIED_OUT_OF_RANGE_REPORT": 2,
            "NOTABLE_ACTIVITY_SPARSE_HISTORY": 3,
            "INCREASED_REPORTING_EXISTING_RANGE": 4,
            "RECENT_REPORTING_EXISTING_RANGE": 5,
        }

        for hotspot in hotspots:

            if hotspot.get(
                "activity_status"
            ) in {
                "ACTIVE",
                "ELEVATED",
                "EMERGING",
            }:
                active_hotspots += 1

            if (
                hotspot.get(
                    "invasive_activity"
                )
                == "HIGH"
            ):
                high_invasive_hotspots += 1

            for (
                species_name,
                activity
            ) in hotspot.get(
                "species_activity",
                {}
            ).items():

                observation_trend = activity.get(
                    "observation_trend",
                    activity.get("trend"),
                )
                regional_context = activity.get(
                    "regional_context",
                    "INSUFFICIENT_DATA",
                )
                monitoring_interpretation = activity.get(
                    "monitoring_interpretation",
                    "INSUFFICIENT_REGIONAL_CONTEXT",
                )
                evidence = activity.get(
                    "evidence",
                    {},
                )

                if monitoring_interpretation in signal_priority:
                    species_signals.append({
                        "species":
                            species_name,

                        "trend":
                            observation_trend,

                        "observation_trend":
                            observation_trend,

                        "regional_context":
                            regional_context,

                        "monitoring_interpretation":
                            monitoring_interpretation,

                        "evidence":
                            evidence,

                        "evidence_confidence":
                            self.classify_evidence_confidence(
                                evidence.get("confirmed", 0),
                                evidence.get("ai_supported", 0),
                            ),

                        "latitude":
                            hotspot[
                                "latitude"
                            ],

                        "longitude":
                            hotspot[
                                "longitude"
                            ],

                        "past_7_days":
                            activity[
                                "past_7_days"
                            ],

                        "past_30_days":
                            activity[
                                "past_30_days"
                            ],

                        "past_90_days":
                            activity[
                                "past_90_days"
                            ],
                    })

        species_signals.sort(
            key=lambda signal: signal_priority[
                signal["monitoring_interpretation"]
            ]
        )

        return {
            "total_observations":
                total_observations,

            "verified_observations":
                verified_observations,

            "pending_review":
                pending_review,

            "invasive_observations":
                invasive_observations,

            "unresolved_identifications":
                unresolved_identifications,

            "species_observed":
                len(species),

            "total_hotspots":
                len(hotspots),

            "active_hotspots":
                active_hotspots,

            "high_invasive_hotspots":
                high_invasive_hotspots,

            "species_signals":
                species_signals,
        }
