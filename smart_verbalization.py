# smart_verbalization.py
"""
Intelligent graph verbalization with semantic context.
Converts graph knowledge to structured natural language optimized for LLM reasoning.
"""

from typing import List, Dict, Tuple, Optional, Set
from collections import defaultdict
from wikidata_utils import wd_get_property_label


def verbalize_graph_with_structure(
    triples: List[Dict],
    qid_to_label: Dict[str, str],
    question: str,
    max_facts: int = 30,
    include_meta: bool = True
) -> str:
    """
    Create structured verbalization of graph facts optimized for LLM reasoning.

    Args:
        triples: List of {head, relation, tail, source} dicts
        qid_to_label: Mapping from QID to human-readable label
        question: Original user question
        max_facts: Maximum facts to include
        include_meta: Include metadata about graph structure

    Returns:
        Structured natural language representation
    """
    # Separate triples by source
    text_triples = [t for t in triples if t.get("source") == "text"]
    wikidata_triples = [t for t in triples if t.get("source") == "wikidata"]
    bridge_triples = [t for t in triples if t.get("source") == "bridge"]

    # Build entity network
    entity_network = _build_entity_network(triples, qid_to_label)

    # Create sections
    sections = []

    # Section 1: Question entities
    sections.append("=== Question Entities ===")
    question_entities = _extract_question_entities(text_triples, qid_to_label)
    for entity, qid in question_entities.items():
        sections.append(f"- {entity} (Wikidata: {qid})")

    # Section 2: Direct facts from text
    sections.append("\n=== Facts from Question ===")
    for t in text_triples[:max_facts // 3]:
        head = t["head"]
        rel = t["relation"].replace("_", " ").lower()
        tail = t["tail"]
        sections.append(f"- {head} {rel} {tail}")

    # Section 3: Wikidata knowledge (organized by entity)
    sections.append("\n=== Wikidata Knowledge Graph ===")
    wikidata_facts = _organize_wikidata_facts_by_entity(
        wikidata_triples,
        qid_to_label,
        max_facts=max_facts * 2 // 3
    )

    for entity, facts in list(wikidata_facts.items())[:10]:  # Top 10 entities
        sections.append(f"\n{entity}:")
        for fact in facts[:5]:  # Top 5 facts per entity
            sections.append(f"  - {fact}")

    # Section 4: Graph structure metadata (if requested)
    if include_meta:
        sections.append("\n=== Graph Structure ===")
        sections.append(f"- Total entities: {len(entity_network)}")
        sections.append(f"- Text facts: {len(text_triples)}")
        sections.append(f"- Wikidata facts: {len(wikidata_triples)}")

        # Connection paths
        paths = _find_connection_paths(entity_network, max_paths=3)
        if paths:
            sections.append("\nKey connection paths:")
            for path in paths:
                sections.append(f"  - {path}")

    return "\n".join(sections)


def _extract_question_entities(text_triples: List[Dict], qid_to_label: Dict[str, str]) -> Dict[str, str]:
    """Extract entities mentioned in question with their QIDs."""
    entities = {}

    for t in text_triples:
        head = t["head"]
        tail = t["tail"]

        # Find matching QIDs
        for qid, label in qid_to_label.items():
            if label.lower() == head.lower():
                entities[head] = qid
            if label.lower() == tail.lower():
                entities[tail] = qid

    return entities


def _organize_wikidata_facts_by_entity(
    wikidata_triples: List[Dict],
    qid_to_label: Dict[str, str],
    max_facts: int = 20
) -> Dict[str, List[str]]:
    """
    Organize Wikidata facts by entity for structured presentation.

    Returns:
        Dict mapping entity label -> list of fact strings
    """
    # Group by head QID
    by_entity = defaultdict(list)

    for t in wikidata_triples:
        head = t["head"]
        rel = t["relation"]
        tail = t["tail"]

        # Convert to readable format
        head_label = qid_to_label.get(head, head)
        tail_label = qid_to_label.get(tail, tail)

        # Get property label
        if rel.startswith("P") and rel[1:].isdigit():
            rel_label = wd_get_property_label(rel, "en")
        else:
            rel_label = rel.replace("_", " ")

        fact = f"{rel_label}: {tail_label}"
        by_entity[head_label].append(fact)

    # Limit facts per entity
    for entity in by_entity:
        by_entity[entity] = by_entity[entity][:5]

    return dict(by_entity)


def _build_entity_network(triples: List[Dict], qid_to_label: Dict[str, str]) -> Dict[str, Set[str]]:
    """
    Build adjacency network of entities.

    Returns:
        Dict mapping entity -> set of connected entities
    """
    network = defaultdict(set)

    for t in triples:
        head = t["head"]
        tail = t["tail"]

        # Convert QIDs to labels
        head_label = qid_to_label.get(head, head)
        tail_label = qid_to_label.get(tail, tail)

        network[head_label].add(tail_label)
        network[tail_label].add(head_label)

    return dict(network)


def _find_connection_paths(network: Dict[str, Set[str]], max_paths: int = 3) -> List[str]:
    """
    Find interesting connection paths in the entity network.

    Returns:
        List of path descriptions
    """
    paths = []

    # Simple BFS to find paths
    # For now, just show high-degree nodes (hubs)
    node_degrees = {node: len(connections) for node, connections in network.items()}
    top_nodes = sorted(node_degrees.items(), key=lambda x: x[1], reverse=True)[:max_paths]

    for node, degree in top_nodes:
        if degree > 1:
            paths.append(f"{node} connected to {degree} other entities")

    return paths


def create_llm_prompt_enhanced(
    question: str,
    structured_facts: str,
    expansion_depth: int = 1,
    use_cot: bool = True
) -> str:
    """
    Create an enhanced prompt with explicit reasoning instructions.

    Args:
        question: User question
        structured_facts: Verbalized graph facts
        expansion_depth: Depth of graph expansion (for context)
        use_cot: Use chain-of-thought prompting

    Returns:
        Optimized prompt for LLM
    """
    prompt = f"""
    You are a precise answer extraction system. You will receive context sentences and a complex multi-hop question that requires connecting information from multiple sources.

    ## Critical Instructions:

    1. **Analyze Carefully**: The question is multi-hop, meaning you MUST connect information from multiple sentences and/or your knowledge base to find the answer.

    2. **Information Sources**:
    - PRIMARY: Use the provided sentences as supporting evidence
    - SECONDARY: Leverage your own knowledge to fill gaps or enhance understanding
    - The sentences should guide and support your reasoning, but you're not limited to only their content
    - Combine both sources intelligently to reach the most accurate answer

    3. **Chain Information**: 
    - Identify relevant facts from the provided sentences
    - Connect these with your broader knowledge
    - Trace the reasoning path from question to answer
    - Use the sentences to validate or refine your knowledge-based answer

    4. **Answer Format**:
    - Respond with ONLY 2-3 words maximum
    - Use the most specific and direct answer possible
    - No explanations, no additional text
    - Just the precise answer entity/phrase

    5. **Accuracy Rules**:
    - Prioritize information from provided sentences when available
    - Use your knowledge to interpret, connect, and complete the information

    ## Context Sentences:
    {structured_facts}

    ## Question:
    {question}

    ## Answer (Ultra-concise responses, No verbose explanations, Direct, precise answers only, Focus on multi-hop reasoning ):"""
    return prompt


def verbalize_paths(
    paths: List[List[Tuple[str, str, str]]],
    qid_to_label: Dict[str, str],
    max_paths: int = 5
) -> str:
    """
    Verbalize reasoning paths through the graph.

    Args:
        paths: List of paths, where each path is [(head, rel, tail), ...]
        qid_to_label: QID to label mapping
        max_paths: Maximum paths to verbalize

    Returns:
        Natural language description of paths
    """
    if not paths:
        return "No connection paths found."

    path_descriptions = []

    for i, path in enumerate(paths[:max_paths], 1):
        steps = []

        for head, rel, tail in path:
            head_label = qid_to_label.get(head, head)
            tail_label = qid_to_label.get(tail, tail)

            # Get relation label
            if rel.startswith("P") and rel[1:].isdigit():
                rel_label = wd_get_property_label(rel, "en")
            else:
                rel_label = rel.replace("_", " ")

            steps.append(f"{head_label} --[{rel_label}]--> {tail_label}")

        path_desc = f"Path {i}: " + " → ".join(steps)
        path_descriptions.append(path_desc)

    return "\n".join(path_descriptions)


def create_hierarchical_verbalization(
    triples: List[Dict],
    qid_to_label: Dict[str, str],
    central_entities: List[str],
    max_depth: int = 2
) -> Dict[int, List[str]]:
    """
    Create hierarchical verbalization organized by distance from central entities.

    Args:
        triples: All triples
        qid_to_label: QID to label mapping
        central_entities: Central entities from the question
        max_depth: Maximum depth to verbalize

    Returns:
        Dict mapping depth -> list of fact strings
    """
    # Build graph
    graph = defaultdict(list)
    for t in triples:
        head = t["head"]
        rel = t["relation"]
        tail = t["tail"]
        graph[head].append((rel, tail))

    # BFS from central entities
    depth_facts = defaultdict(list)
    visited = set()
    queue = [(entity, 0) for entity in central_entities]

    while queue:
        current, depth = queue.pop(0)

        if current in visited or depth > max_depth:
            continue

        visited.add(current)

        # Get facts for this entity
        for rel, tail in graph.get(current, []):
            current_label = qid_to_label.get(current, current)
            tail_label = qid_to_label.get(tail, tail)

            if rel.startswith("P"):
                rel_label = wd_get_property_label(rel, "en")
            else:
                rel_label = rel.replace("_", " ")

            fact = f"{current_label} {rel_label} {tail_label}"
            depth_facts[depth].append(fact)

            # Add to queue for next depth
            if tail not in visited:
                queue.append((tail, depth + 1))

    return dict(depth_facts)
