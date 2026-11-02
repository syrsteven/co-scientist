"""Shared structural checks only; these do not evaluate scientific content."""


def require_refs(*refs: object) -> None:
    if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
        raise ValueError("References must be nonempty strings")


def unique_tuple(values: tuple, label: str, *, nonempty: bool = False) -> None:
    if not isinstance(values, tuple) or (nonempty and not values):
        raise ValueError(f"{label} requires an immutable tuple")
    try:
        unique = len(set(values)) == len(values)
    except TypeError:
        raise ValueError(f"{label} must contain immutable values") from None
    if not unique:
        raise ValueError(f"Duplicate {label}")
