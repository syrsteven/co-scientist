Return only exact RankingResultV1 JSON (schema_version 1), including all registered
provenance fields. decision_status is decisive, inconclusive, invalid, or
needs_tiebreaker; winner_slot is 1 or 2 only for decisive. Never return winner IDs,
ratings, Elo, or extra fields.
