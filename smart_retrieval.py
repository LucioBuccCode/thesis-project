# smart_retrieval.py
"""
Smart retrieval using graph structure and reasoning paths.
Instead of relying only on cosine similarity, this uses actual paths in the graph.
"""

from typing import List, Dict, Tuple, Set, Optional
import torch
import torch.nn.functional as F
from collections import defaultdict
import re


def extract_question_entities(question: str, entity_names: List[str]) -> List[str]:
    """
    Extract entities from question that match graph entities.

    Args:
        question: User question
        entity_names: List of entity names in graph

    Returns:
        List of matched entities
    """
    question_lower = question.lower()
    matched = []

    # Sort by length (longest first) to avoid partial matches
    sorted_entities = sorted(entity_names, key=len, reverse=True)

    for entity in sorted_entities:
        # Check if entity appears in question
        if entity.lower() in question_lower:
            matched.append(entity)
            # Remove from question to avoid duplicate matches
            question_lower = question_lower.replace(entity.lower(), "")

    return matched


def find_reasoning_paths(
    all_triples: List[Dict],
    question_entities: List[str],
    max_hops: int = 3,
    max_paths: int = 20
) -> List[List[Dict]]:
    """
    Find reasoning paths between question entities using graph structure.

    Args:
        all_triples: All triples in the graph
        question_entities: Entities mentioned in question
        max_hops: Maximum path length
        max_paths: Maximum paths to return

    Returns:
        List of paths, where each path is a list of triples
    """
    # Build adjacency list
    graph = defaultdict(list)
    for t in all_triples:
        head = t["head"]
        tail = t["tail"]
        graph[head].append((t["relation"], tail, t))
        # Also add reverse for bidirectional search
        graph[tail].append((f"reverse_{t['relation']}", head, t))

    # BFS from each question entity
    all_paths = []

    for start_entity in question_entities:
        if start_entity not in graph:
            continue

        # BFS
        queue = [(start_entity, [])]  # (current_entity, path_so_far)
        visited = {start_entity}

        while queue and len(all_paths) < max_paths:
            current, path = queue.pop(0)

            # Save this path if non-empty
            if len(path) > 0:
                all_paths.append(path)

            # Don't expand beyond max_hops
            if len(path) >= max_hops:
                continue

            # Explore neighbors
            for rel, neighbor, triple in graph.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_path = path + [triple]
                    queue.append((neighbor, new_path))

    return all_paths[:max_paths]


def score_path_relevance(
    path: List[Dict],
    question: str,
    qid_to_label: Dict[str, str]
) -> float:
    """
    Score how relevant a path is to answering the question.

    Args:
        path: List of triples forming a path
        question: User question
        qid_to_label: QID to label mapping

    Returns:
        Relevance score (0-1)
    """
    score = 0.0
    question_lower = question.lower()

    # Keywords in question that suggest answer type
    answer_keywords = {
        'who': ['person', 'people', 'spouse', 'parent', 'child', 'president', 'leader'],
        'when': ['date', 'time', 'year', 'born', 'death', 'founded'],
        'where': ['place', 'location', 'city', 'country', 'birthplace'],
        'what': ['occupation', 'position', 'instance of', 'type'],
        'how many': ['count', 'number', 'quantity'],
    }

    # Detect question type
    question_type = None
    for qword in answer_keywords:
        if qword in question_lower:
            question_type = qword
            break

    # Score based on path properties
    for triple in path:
        rel = triple["relation"].lower()
        tail = triple["tail"]

        # Resolve QID to label if applicable
        if tail.startswith("Q") and tail in qid_to_label:
            tail_label = qid_to_label[tail].lower()
        else:
            tail_label = tail.lower()

        # Check if relation matches question type
        if question_type and question_type in answer_keywords:
            for keyword in answer_keywords[question_type]:
                if keyword in rel or keyword in tail_label:
                    score += 0.5

        # Boost if entities in path appear in question
        if tail_label in question_lower:
            score += 1.0

        # Boost for common important relations
        important_relations = ['spouse', 'parent', 'child', 'born', 'occupation', 'position']
        for imp_rel in important_relations:
            if imp_rel in rel:
                score += 0.3

    # Penalize very long paths (they tend to be less relevant)
    path_length_penalty = 1.0 / (1.0 + 0.2 * len(path))
    score *= path_length_penalty

    return score


def select_best_paths(
    paths: List[List[Dict]],
    question: str,
    qid_to_label: Dict[str, str],
    max_paths: int = 10
) -> List[List[Dict]]:
    """
    Select most relevant paths for answering the question.

    Args:
        paths: All candidate paths
        question: User question
        qid_to_label: QID to label mapping
        max_paths: Maximum paths to return

    Returns:
        Sorted list of best paths
    """
    # Score each path
    scored_paths = []
    for path in paths:
        score = score_path_relevance(path, question, qid_to_label)
        scored_paths.append((score, path))

    # Sort by score
    scored_paths.sort(key=lambda x: x[0], reverse=True)

    # Return top paths
    return [path for score, path in scored_paths[:max_paths]]


def extract_facts_from_paths(
    paths: List[List[Dict]],
    qid_to_label: Dict[str, str]
) -> List[Dict]:
    """
    Extract unique facts from selected paths.

    Args:
        paths: Selected reasoning paths
        qid_to_label: QID to label mapping

    Returns:
        Deduplicated list of facts
    """
    seen = set()
    facts = []

    for path in paths:
        for triple in path:
            # Create unique key
            key = (triple["head"], triple["relation"], triple["tail"])

            if key not in seen:
                seen.add(key)
                facts.append(triple)

    return facts


def smart_retrieve_and_rank(
    question: str,
    all_triples: List[Dict],
    entity_names: List[str],
    qid_to_label: Dict[str, str],
    max_hops: int = 3,
    max_paths: int = 20,
    max_facts: int = 15
) -> Tuple[List[Dict], List[List[Dict]]]:
    """
    Smart retrieval using graph paths instead of just cosine similarity.

    Args:
        question: User question
        all_triples: All triples in graph
        entity_names: List of entity names
        qid_to_label: QID to label mapping
        max_hops: Maximum path length
        max_paths: Maximum paths to find
        max_facts: Maximum facts to return

    Returns:
        - List of relevant facts (deduplicated from best paths)
        - List of reasoning paths (for explanation)
    """
    print(f"[SMART RETRIEVAL] Starting path-based retrieval")

    # 1. Extract question entities
    question_entities = extract_question_entities(question, entity_names)
    print(f"  - Question entities: {question_entities}")

    if not question_entities:
        print(f"  [WARN] No entities found in question, using keyword fallback")
        # Fallback: extract capitalized words
        words = question.split()
        question_entities = [w for w in words if w and w[0].isupper()]

    # 2. Find reasoning paths
    paths = find_reasoning_paths(
        all_triples,
        question_entities,
        max_hops=max_hops,
        max_paths=max_paths * 3  # Find more paths initially
    )
    print(f"  - Found {len(paths)} candidate paths")

    # 3. Score and select best paths
    best_paths = select_best_paths(
        paths,
        question,
        qid_to_label,
        max_paths=max_paths
    )
    print(f"  - Selected {len(best_paths)} best paths")

    # 4. Extract facts from best paths
    facts = extract_facts_from_paths(best_paths, qid_to_label)[:max_facts]
    print(f"  - Extracted {len(facts)} unique facts")

    return facts, best_paths


def create_path_aware_prompt(
    question: str,
    facts: List[Dict],
    paths: List[List[Dict]],
    qid_to_label: Dict[str, str],
    max_paths_show: int = 5
) -> str:
    """
    Create LLM prompt with explicit reasoning paths.

    Args:
        question: User question
        facts: Relevant facts
        paths: Reasoning paths
        qid_to_label: QID to label mapping
        max_paths_show: Max paths to include in prompt

    Returns:
        Formatted prompt
    """
    from wikidata_utils import wd_get_property_label

    # Section 1: Reasoning paths
    prompt_sections = []
    prompt_sections.append(f"""
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

    ## Question:
    {question}

    ## Answer (Ultra-concise responses, No verbose explanations, Direct, precise answers only, Focus on multi-hop reasoning ):""")
    prompt_sections.append("=== Reasoning Paths ===")
    prompt_sections.append("Here are the relevant connections in the knowledge graph:")

    for i, path in enumerate(paths[:max_paths_show], 1):
        if not path:
            continue

        path_desc = []
        for triple in path:
            head = triple["head"]
            rel = triple["relation"]
            tail = triple["tail"]

            # Resolve labels
            if head.startswith("Q") and head in qid_to_label:
                head = qid_to_label[head]
            if tail.startswith("Q") and tail in qid_to_label:
                tail = qid_to_label[tail]
            if rel.startswith("P"):
                rel = wd_get_property_label(rel, "en")
            else:
                rel = rel.replace("_", " ").replace("reverse_", "← ")

            path_desc.append(f"{head} --[{rel}]--> {tail}")

        prompt_sections.append(f"\nPath {i}: " + " → ".join(path_desc))

    # Section 2: Key facts
    prompt_sections.append("\n\n=== Key Facts ===")
    for fact in facts[:15]:
        head = fact["head"]
        rel = fact["relation"]
        tail = fact["tail"]

        # Resolve labels
        if head.startswith("Q") and head in qid_to_label:
            head = qid_to_label[head]
        if tail.startswith("Q") and tail in qid_to_label:
            tail = qid_to_label[tail]
        if rel.startswith("P"):
            rel = wd_get_property_label(rel, "en")
        else:
            rel = rel.replace("_", " ")

        prompt_sections.append(f"- {head} {rel} {tail}")

    # Section 3: Instructions

    return "\n".join(prompt_sections)
