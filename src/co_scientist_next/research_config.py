"""Frozen, count-based research limits. No invented monetary budget."""

DEFAULTS = {
    "directed_count": 1,
    "open_count": 1,
    "max_directions": 2,
    "candidates_per_mode": 1,
    "mode": "DIRECT",
    "queries_per_round": 2,
    "pages_per_query": 1,
    "page_size": 5,
    "sources_per_round": 3,
    "max_followup_rounds": 1,
    "segment_characters": 12000,
    "max_segments_per_source": 6,
    "max_model_calls": 80,
    "max_search_pages": 20,
    "max_material_fetches": 40,
    "max_remote_queries": 60,
    "poll_interval_seconds": 15,
}


def validate_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Unknown research configuration; USD budgets are not supported")
    config = {**DEFAULTS, **value}
    maxima = {
        "directed_count": 5,
        "open_count": 3,
        "max_directions": 8,
        "candidates_per_mode": 5,
        "queries_per_round": 10,
        "pages_per_query": 10,
        "page_size": 20,
        "sources_per_round": 20,
        "max_followup_rounds": 5,
        "segment_characters": 50000,
        "max_segments_per_source": 100,
        "max_model_calls": 1000,
        "max_search_pages": 500,
        "max_material_fetches": 1000,
        "max_remote_queries": 240,
        "poll_interval_seconds": 600,
    }
    for key, maximum in maxima.items():
        minimum = 0 if key in ("directed_count", "open_count", "max_followup_rounds") else 1
        if type(config[key]) is not int or not minimum <= config[key] <= maximum:
            raise ValueError(f"{key} must be {minimum}..{maximum}")
    if config["poll_interval_seconds"] < 15:
        raise ValueError("Remote queries must be at least 15 seconds apart")
    total = config["directed_count"] + config["open_count"]
    if not 1 <= total <= config["max_directions"]:
        raise ValueError("Directed + Open must be positive and within maximum directions")
    if config["mode"] not in ("DIRECT", "ASSUMPTION_STRUCTURED", "Both"):
        raise ValueError("Unsupported generation mode")
    return config


def expected_candidates(config):
    return (
        (config["directed_count"] + config["open_count"])
        * config["candidates_per_mode"]
        * (2 if config["mode"] == "Both" else 1)
    )
