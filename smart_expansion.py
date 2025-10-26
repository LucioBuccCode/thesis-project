# smart_expansion.py
"""
Intelligent multi-hop graph expansion for Wikidata.
Expands graph based on semantic relevance and query intent.
"""

from typing import List, Dict, Tuple, Set, Optional
import time
from dataclasses import dataclass
from collections import defaultdict
from wikidata_utils import wd_get_claims, wd_get_label_desc


@dataclass
class ExpansionResult:
    """Result of graph expansion."""

    # All edges found (headQID, PID, tailQID)
    edges: List[Tuple[str, str, str]]

    # All QIDs discovered (including intermediate)
    qids: Set[str]

    # Expansion statistics
    stats: Dict[str, int]

    # QID to label mapping
    qid_labels: Dict[str, str]


def smart_expand_graph(
    seed_qids: List[str],
    properties: List[str],
    max_depth: int = 2,
    max_edges_per_qid: int = 10,
    max_total_qids: int = 100,
    relevance_filter: Optional[callable] = None,
    sleep_s: float = 0.1,
    lang: str = "en"
) -> ExpansionResult:
    """
    Intelligently expand graph from seed QIDs using BFS with pruning.

    Args:
        seed_qids: Starting QIDs
        properties: Wikidata properties to follow (PIDs)
        max_depth: Maximum number of hops (1-3)
        max_edges_per_qid: Max edges to retrieve per QID
        max_total_qids: Stop expansion after this many QIDs
        relevance_filter: Optional function to filter QIDs by relevance
        sleep_s: Sleep between API calls
        lang: Language for labels

    Returns:
        ExpansionResult with edges and statistics
    """
    print(f"[SMART EXPAND] Starting from {len(seed_qids)} seed QIDs")
    print(f"  - Max depth: {max_depth}")
    print(f"  - Properties: {properties[:5]}..." if len(properties) > 5 else f"  - Properties: {properties}")
    print(f"  - Max edges per QID: {max_edges_per_qid}")

    all_edges = []
    discovered_qids = set(seed_qids)
    visited_qids = set()
    qid_labels = {}

    # BFS queue: (qid, current_depth)
    queue = [(qid, 0) for qid in seed_qids]

    # Statistics
    stats = {
        "total_qids": 0,
        "total_edges": 0,
        "depth_0_qids": len(seed_qids),
        "depth_1_qids": 0,
        "depth_2_qids": 0,
        "depth_3_qids": 0,
        "filtered_qids": 0,
        "api_calls": 0
    }

    while queue and len(discovered_qids) < max_total_qids:
        current_qid, depth = queue.pop(0)

        # Skip if already visited
        if current_qid in visited_qids:
            continue

        # Skip if beyond max depth
        if depth >= max_depth:
            continue

        visited_qids.add(current_qid)
        stats["api_calls"] += 1

        # Get label for this QID
        try:
            label, desc = wd_get_label_desc(current_qid, lang=lang)
            qid_labels[current_qid] = label or current_qid
        except Exception as e:
            print(f"[WARN] Could not get label for {current_qid}: {e}")
            qid_labels[current_qid] = current_qid

        # Get claims for this QID
        try:
            edges = wd_get_claims(
                current_qid,
                prop_keys=properties,
                lang=lang,
                max_edges=max_edges_per_qid,
                preferred_only=False
            )
        except Exception as e:
            print(f"[WARN] Failed to get claims for {current_qid}: {e}")
            time.sleep(sleep_s)
            continue

        # Process edges
        for head, pid, tail in edges:
            all_edges.append((head, pid, tail))
            stats["total_edges"] += 1

            # Add tail to queue if not discovered yet
            if tail not in discovered_qids:
                # Apply relevance filter if provided
                if relevance_filter is None or relevance_filter(tail, pid, depth + 1):
                    discovered_qids.add(tail)
                    queue.append((tail, depth + 1))

                    # Track depth statistics
                    depth_key = f"depth_{min(depth + 1, 3)}_qids"
                    stats[depth_key] += 1
                else:
                    stats["filtered_qids"] += 1

        time.sleep(sleep_s)

        # Progress update
        if stats["api_calls"] % 10 == 0:
            print(f"  [Progress] QIDs: {len(discovered_qids)}, Edges: {stats['total_edges']}, Queue: {len(queue)}")

    stats["total_qids"] = len(discovered_qids)

    print(f"[SMART EXPAND] Completed:")
    print(f"  - Total QIDs: {stats['total_qids']}")
    print(f"  - Total edges: {stats['total_edges']}")
    print(f"  - Depth breakdown: D0={stats['depth_0_qids']}, D1={stats['depth_1_qids']}, D2={stats['depth_2_qids']}")
    print(f"  - Filtered: {stats['filtered_qids']}")

    return ExpansionResult(
        edges=all_edges,
        qids=discovered_qids,
        stats=stats,
        qid_labels=qid_labels
    )


def create_relevance_filter(
    focus_keywords: List[str],
    forbidden_types: Optional[List[str]] = None
) -> callable:
    """
    Create a relevance filter function to prune irrelevant QIDs during expansion.

    Args:
        focus_keywords: Keywords that indicate relevance
        forbidden_types: QID types to exclude (e.g., ["Q5"] for humans if not needed)

    Returns:
        Filter function: (qid, pid, depth) -> bool
    """
    def filter_fn(qid: str, pid: str, depth: int) -> bool:
        # Always include at depth 1 (direct connections)
        if depth <= 1:
            return True

        # At depth 2+, apply stricter filtering
        # This is where you could add semantic filtering logic
        # For now, we use simple heuristics

        # Exclude certain properties at higher depths
        if depth >= 2:
            # Skip overly generic properties at depth 2+
            generic_properties = ["P31", "P279"]  # instance of, subclass of
            if pid in generic_properties:
                return False

        return True

    return filter_fn


def group_edges_by_property(edges: List[Tuple[str, str, str]]) -> Dict[str, List[Tuple[str, str, str]]]:
    """
    Group edges by property type for better organization.

    Args:
        edges: List of (head, pid, tail) tuples

    Returns:
        Dict mapping PID -> list of edges
    """
    grouped = defaultdict(list)
    for head, pid, tail in edges:
        grouped[pid].append((head, pid, tail))

    return dict(grouped)


def get_expansion_statistics(result: ExpansionResult) -> Dict[str, any]:
    """
    Compute detailed statistics about the expansion.

    Args:
        result: ExpansionResult from smart_expand_graph

    Returns:
        Dict with detailed stats
    """
    # Group edges by property
    by_property = group_edges_by_property(result.edges)

    # Count edges per property
    property_counts = {pid: len(edges) for pid, edges in by_property.items()}

    # Sort by count
    top_properties = sorted(property_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Compute graph metrics
    unique_heads = len(set(h for h, _, _ in result.edges))
    unique_tails = len(set(t for _, _, t in result.edges))

    return {
        "total_edges": len(result.edges),
        "total_qids": len(result.qids),
        "unique_heads": unique_heads,
        "unique_tails": unique_tails,
        "num_properties": len(by_property),
        "top_properties": top_properties,
        "avg_edges_per_qid": len(result.edges) / max(len(result.qids), 1),
        "stats": result.stats
    }


def smart_expand_with_context(
    seed_qids: List[str],
    question: str,
    triples: List[Dict],
    max_depth: int = 2,
    max_total_qids: int = 100,
    lang: str = "en"
) -> ExpansionResult:
    """
    Context-aware graph expansion using intent analysis.

    Args:
        seed_qids: Starting QIDs
        question: Original user question
        triples: Extracted triples
        max_depth: Maximum expansion depth
        max_total_qids: Maximum QIDs to discover
        lang: Language

    Returns:
        ExpansionResult
    """
    # Import intent analyzer
    from intent_analyzer import analyze_expansion_intent, get_relevant_wikidata_properties, estimate_max_edges_per_qid

    # Analyze intent
    intent = analyze_expansion_intent(question, triples)

    print(f"[INTENT ANALYSIS]")
    print(f"  - Expansion depth: {intent.expansion_depth}")
    print(f"  - Relation types: {intent.relation_types}")
    print(f"  - Comprehensive: {intent.comprehensive}")
    print(f"  - Focus areas: {intent.focus_areas}")

    # Get relevant properties based on intent
    properties = get_relevant_wikidata_properties(intent)

    # Estimate max edges per QID
    max_edges_per_qid = estimate_max_edges_per_qid(intent)

    # Use intent depth if specified, otherwise use parameter
    expansion_depth = intent.expansion_depth if intent.expansion_depth > 0 else max_depth

    # Create relevance filter
    relevance_filter = create_relevance_filter(
        focus_keywords=intent.focus_areas,
        forbidden_types=None
    )

    # Perform smart expansion
    result = smart_expand_graph(
        seed_qids=seed_qids,
        properties=properties,
        max_depth=expansion_depth,
        max_edges_per_qid=max_edges_per_qid,
        max_total_qids=max_total_qids,
        relevance_filter=relevance_filter,
        lang=lang
    )

    return result
