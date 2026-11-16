"""Versioned, offline main-campus building registry and walking estimates.

Building codes and pedestrian access are curated from the PolyU Campus Map
(https://www.polyu.edu.hk/cdo/docdrive/Useful%20Information/CampusMap.pdf)
and Campus Access
(https://www.polyu.edu.hk/cfso/informationhub/access-to-campus-and-premises/).
Edge weights are CampusHands project estimates in whole minutes, not official
walking times or navigation instructions. Changes to the static graph should
be reviewed against a current map and released with a version change.
"""

from __future__ import annotations

from functools import lru_cache
from heapq import heappop, heappush
import re
import unicodedata


GRAPH_VERSION = "2026-11-m06-v2"

# The P/Q handoff area remains a named node for Milestones 01–05 data.
# Junctions are not selectable locations and are deliberately kept internal.
_BUILDING_CODES = (
    "A", "B", "C", "D", "E", "F", "G", "H", "J", "L", "M", "N",
    "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    "VA", "VS", "MN", "PQ",
)
_JUNCTIONS = ("X_Z_FOOTBRIDGE", "Y_Z_UNDERPASS", "PQ_VA_PODIUM")

_DISPLAY_NAMES = {
    code: (f"{code}座", f"Block {code}") for code in _BUILDING_CODES
}
_DISPLAY_NAMES.update({
    "L": ("图书馆", "Library"),
    "V": ("賽馬會創新樓", "Jockey Club Innovation Tower"),
    "VA": ("邵逸夫樓", "Shaw Amenities Building"),
    "VS": ("邵逸夫體育館", "Shaw Sports Complex"),
    "Y": ("李兆基樓", "Lee Shau Kee Building"),
    "PQ": ("P/Q交接区", "P/Q area"),
})

# Approximate pedestrian links follow the map's spatial building groups:
# upper A/G/H/V/VS/Z, middle B/VA/C/F/J/X/M/MN, lower D/E/R/S/N/L/W/Y,
# and southern U/T/Q/P. This topology and the regular two-minute edge weights
# are project estimates; the source maps do not publish these walking times.
# Do not infer a direct connection from code similarity or matching text.
_WALK_EDGES = (
    ("A", "G", 2), ("G", "H", 2), ("H", "V", 2), ("V", "VS", 2),
    ("VS", "Z", 2),
    ("B", "VA", 2), ("VA", "C", 2), ("C", "F", 2), ("F", "J", 2),
    ("J", "X", 2), ("X", "M", 2), ("M", "MN", 2),
    ("D", "E", 2), ("E", "R", 2), ("R", "S", 2), ("S", "N", 2),
    ("N", "L", 2), ("L", "W", 2), ("W", "Y", 2),
    ("U", "T", 2), ("T", "Q", 2), ("Q", "P", 2),
    ("A", "B", 2), ("G", "C", 2), ("H", "F", 2), ("V", "J", 2),
    ("VS", "X", 2), ("Z", "Y_Z_UNDERPASS", 1),
    ("Y_Z_UNDERPASS", "Y", 1),
    ("B", "D", 2), ("VA", "E", 2), ("C", "R", 2), ("F", "S", 2),
    ("J", "N", 2), ("X", "L", 2), ("M", "W", 2), ("MN", "Y", 2),
    ("D", "U", 2), ("E", "T", 2), ("R", "Q", 2), ("S", "P", 2),
    ("X", "X_Z_FOOTBRIDGE", 2),
    ("X_Z_FOOTBRIDGE", "Z", 2),  # Campus Access records the X–Z footbridge.
    ("P", "PQ", 1), ("Q", "PQ", 1),
    ("PQ", "PQ_VA_PODIUM", 2),
    ("PQ_VA_PODIUM", "VA", 2),  # Legacy P/Q-to-VA podium walk estimate.
)


def _alias_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s\-_./]+", "", normalized)


def _build_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}

    def add(alias: str, code: str) -> None:
        key = _alias_key(alias)
        existing = aliases.get(key)
        if not key or existing not in (None, code):
            raise ValueError(f"conflicting campus location alias: {alias!r}")
        aliases[key] = code

    for code in _BUILDING_CODES:
        for alias in (
            code, f"Block {code}", f"{code} Block", f"PolyU Block {code}",
            f"{code}座", f"{code}栋", f"{code}棟", f"{code}楼", f"{code}樓",
        ):
            add(alias, code)
    for alias in (
        "Library", "PolyU Library", "University Library", "Pao Yue-kong Library", "图书馆",
        "圖書館", "香港理工大学图书馆", "香港理工大學圖書館",
        "理工大学图书馆", "理工大學圖書館", "LIBRARY",
    ):
        add(alias, "L")
    # Named-building aliases are kept explicit: historical campus maps have
    # assigned some names to different block codes, so never infer the code.
    named_aliases = {
        "V": ("Jockey Club Innovation Tower", "賽馬會創新樓", "赛马会创新楼"),
        "VA": ("Shaw Amenities Building", "邵逸夫樓", "邵逸夫楼"),
        "VS": ("Shaw Sports Complex", "邵逸夫體育館", "邵逸夫体育馆"),
        "Y": ("Lee Shau Kee Building", "李兆基樓", "李兆基楼"),
    }
    for code, names in named_aliases.items():
        for name in names:
            add(name, code)
    for alias in ("P/Q", "P-Q", "P Q", "P/Q area", "P/Q交接区", "P/Q交接區"):
        add(alias, "PQ")
    return aliases


_ALIASES = _build_aliases()


def _build_graph() -> dict[str, tuple[tuple[str, int], ...]]:
    graph: dict[str, list[tuple[str, int]]] = {code: [] for code in (*_BUILDING_CODES, *_JUNCTIONS)}
    seen_edges: set[frozenset[str]] = set()
    for source, target, minutes in _WALK_EDGES:
        edge = frozenset((source, target))
        if source not in graph or target not in graph or source == target:
            raise ValueError(f"invalid campus edge: {source}-{target}")
        if not isinstance(minutes, int) or minutes <= 0 or edge in seen_edges:
            raise ValueError(f"invalid campus edge weight or duplicate: {source}-{target}")
        seen_edges.add(edge)
        graph[source].append((target, minutes))
        graph[target].append((source, minutes))

    visited = {next(iter(graph))}
    pending = list(visited)
    while pending:
        for neighbour, _ in graph[pending.pop()]:
            if neighbour not in visited:
                visited.add(neighbour)
                pending.append(neighbour)
    if visited != set(graph):
        raise ValueError(f"disconnected campus locations: {sorted(set(graph) - visited)}")
    return {code: tuple(neighbours) for code, neighbours in graph.items()}


_GRAPH = _build_graph()


def normalize_location(value: str | None) -> str | None:
    """Resolve a supported building name or alias; never guess unknown text."""
    if not isinstance(value, str):
        return None
    return _ALIASES.get(_alias_key(value))


@lru_cache(maxsize=None)
def _shortest_path_minutes(start: str, end: str) -> int | None:
    if start == end:
        return 0
    queue = [(0, start)]
    distances = {start: 0}
    while queue:
        elapsed, node = heappop(queue)
        if elapsed != distances[node]:
            continue
        if node == end:
            return elapsed
        for neighbour, weight in _GRAPH[node]:
            candidate = elapsed + weight
            if candidate < distances.get(neighbour, float("inf")):
                distances[neighbour] = candidate
                heappush(queue, (candidate, neighbour))
    return None


def travel_minutes(origin: str | None, destination: str | None) -> int | None:
    """Return a project walking estimate, or None if either end is unknown."""
    start = normalize_location(origin)
    end = normalize_location(destination)
    if start is None or end is None:
        return None
    return _shortest_path_minutes(start, end)


def location_options() -> list[dict[str, str]]:
    """Public selectable names only; no graph, helper, or inventory data."""
    return [
        {"code": code, "label_zh": _DISPLAY_NAMES[code][0], "label_en": _DISPLAY_NAMES[code][1]}
        for code in _BUILDING_CODES
    ]
