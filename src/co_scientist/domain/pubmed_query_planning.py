"""Opt-in query syntax policy; not a recall or scientific relevance validator.

The conservative subset deliberately excludes implicit AND, NOT, PMID lookups,
proximity and arbitrary PubMed fields. Reject, never rewrite. Old plans retain
their historical validation. Limits are engineering policy, not domain truth.
"""

import re
from collections.abc import Sequence

VERSION = "pubmed-query-planning-v2"
SKILL_VERSION = "0.2.0"
MAX_QUERY_BYTES = 2048
_TOKEN = re.compile(r'\s*("[^"\r\n]+"\[(?:tiab|mesh|MeSH Terms)\]|[\w-]+\[(?:tiab|mesh|MeSH Terms)\]|AND\b|OR\b|[()])')
_TOKEN_V3 = re.compile(r'\s*([A-Za-z0-9]{4,}\*\[tiab\]|"[^"\r\n]+"\[(?:tiab|mesh|MeSH Terms)\]|[\w-]+\[(?:tiab|mesh|MeSH Terms)\]|AND\b|OR\b|[()])')


def validate_queries(queries: Sequence[str], *, revision: str = VERSION) -> None:
    """Validate 1–3 exact queries; first has <=2 mandatory concept groups."""
    if revision not in {VERSION, "pubmed-query-planning-v3"}:
        raise ValueError("unsupported query revision")
    token_pattern = _TOKEN if revision == VERSION else _TOKEN_V3
    if not 1 <= len(queries) <= 3:
        raise ValueError("query-v2 requires 1-3 queries")
    seen: set[str] = set()
    for index, query in enumerate(queries):
        if not isinstance(query, str) or len(query.encode()) > MAX_QUERY_BYTES:
            raise ValueError("query-v2 byte limit")
        tokens, pos = [], 0
        while pos < len(query):
            match = token_pattern.match(query, pos)
            if match is None:
                raise ValueError("query-v2 requires explicit Boolean syntax and fielded terms")
            tokens.append(match[1])
            pos = match.end()
        if not tokens or len(tokens) > 64:
            raise ValueError("query-v2 token bound")
        identity = tuple(t.casefold() for t in tokens)
        canonical = " ".join(identity)
        if canonical in seen:
            raise ValueError("query-v2 duplicate query")
        seen.add(canonical)
        terms = [t for t in identity if t not in {"and", "or", "(", ")"}]
        if len(set(terms)) != len(terms):
            raise ValueError("query-v2 redundant term")
        count = _concept_count(tokens)
        if count > (2 if index == 0 else 3):
            raise ValueError("query-v2 excessive mandatory concepts; first query must be broad")


def _concept_count(tokens: list[str]) -> int:
    cursor = 0

    def atom(depth: int) -> int:
        nonlocal cursor
        if depth > 8 or cursor == len(tokens):
            raise ValueError("query-v2 incomplete/deep expression")
        token = tokens[cursor]
        cursor += 1
        if token == "(":
            n = expression(depth + 1)
            if cursor == len(tokens) or tokens[cursor] != ")":
                raise ValueError("query-v2 unbalanced parentheses")
            cursor += 1
            return n
        if token in {"AND", "OR", ")"}:
            raise ValueError("query-v2 missing operand")
        return 1

    def conjunction(depth: int) -> int:
        nonlocal cursor
        count = atom(depth)
        while cursor < len(tokens) and tokens[cursor] == "AND":
            cursor += 1
            count += atom(depth)
        return count

    def expression(depth: int) -> int:
        nonlocal cursor
        count = conjunction(depth)
        while cursor < len(tokens) and tokens[cursor] == "OR":
            cursor += 1
            count = max(count, conjunction(depth))
        return count

    count = expression(0)
    if cursor != len(tokens):
        raise ValueError("query-v2 trailing/implicit Boolean expression")
    return count
