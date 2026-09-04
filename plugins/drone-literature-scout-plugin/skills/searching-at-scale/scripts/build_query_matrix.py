from __future__ import annotations

import argparse
from dataclasses import dataclass
from itertools import chain, islice, product
import json
import sys
from typing import Iterable, Iterator


@dataclass(frozen=True)
class QueryDimensions:
    topics: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    times: tuple[str, ...] = ()
    source_facets: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    qualifiers: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryBatch:
    queries: tuple[str, ...]
    next_offset: int
    exhausted: bool


def _values(values: tuple[str, ...]) -> tuple[str, ...]:
    return values or ("",)


def _clean(parts: Iterable[str], exclusions: tuple[str, ...]) -> str:
    positive = " ".join(part.strip() for part in parts if part and part.strip())
    negative = " ".join(
        f"-{term.strip()}" for term in exclusions if term.strip()
    )
    return " ".join(part for part in (positive, negative) if part)


def iter_query_matrix(dims: QueryDimensions) -> Iterator[str]:
    seen: set[str] = set()
    subjects = tuple(dict.fromkeys(chain(dims.topics, dims.aliases)))
    families = product(
        _values(subjects),
        _values(dims.locations),
        _values(dims.times),
        _values(dims.source_facets),
        _values(dims.languages),
        _values(dims.qualifiers),
    )
    for parts in families:
        query = _clean(parts, dims.exclusions)
        if query and query not in seen:
            seen.add(query)
            yield query


def query_batch(
    dims: QueryDimensions,
    *,
    offset: int,
    limit: int,
) -> QueryBatch:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    window = tuple(islice(iter_query_matrix(dims), offset, offset + limit + 1))
    queries = window[:limit]
    return QueryBatch(
        queries=queries,
        next_offset=offset + len(queries),
        exhausted=len(window) <= limit,
    )


def _parse_dimensions(payload: object) -> QueryDimensions:
    if not isinstance(payload, dict):
        raise ValueError("input must be a JSON object")

    fields = set(QueryDimensions.__dataclass_fields__)
    unknown = set(payload) - fields
    if unknown:
        raise ValueError(f"unknown field: {sorted(unknown)[0]}")
    if "topics" not in payload:
        raise ValueError("missing required field: topics")

    normalized: dict[str, tuple[str, ...]] = {}
    for field, values in payload.items():
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"{field} must be an array of strings")
        normalized[field] = tuple(values)
    return QueryDimensions(**normalized)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stream or batch a query matrix")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    arguments = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        dimensions = _parse_dimensions(payload)
        if arguments.limit is None:
            if arguments.offset < 0:
                raise ValueError("offset must be a non-negative integer")
            queries = islice(iter_query_matrix(dimensions), arguments.offset, None)
        else:
            queries = query_batch(
                dimensions,
                offset=arguments.offset,
                limit=arguments.limit,
            ).queries
    except (json.JSONDecodeError, ValueError) as error:
        print(f"invalid query dimensions: {error}", file=sys.stderr)
        return 2

    for query in queries:
        print(json.dumps({"query": query}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
