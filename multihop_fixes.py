#!/usr/bin/env python3
"""
Concrete implementations of multi-hop reasoning improvements.

This file contains ready-to-use fixes for the identified problems.
Import and integrate these functions into the main pipeline.
"""

import re
import time
import torch
import networkx as nx
from typing import List, Dict, Tuple, Set, Optional, Any
from collections import deque
from sentence_transformers import SentenceTransformer


# ============================================================================
# FIX 1: IMPROVED QUESTION DECOMPOSITION
# ============================================================================

def decompose_question_enhanced(text: str) -> List[str]:
    """
    Enhanced question decomposition with support for complex multi-hop patterns.

    NEW PATTERNS:
    - "What X did the Y who Z do?"
    - "What X did Y who Z have?"
    - More robust entity extraction
    """
    sub_questions = [text]  # Always include original
    text_lower = text.lower()

    # PATTERN 1: "Who is the X of the Y that Z?"
    pattern1 = r"who\s+is\s+the\s+(\w+)\s+of\s+the\s+(\w+)\s+(.*?)[\?]?"
    match1 = re.search(pattern1, text_lower)
    if match1:
        relation1 = match1.group(1)
        entity_type = match1.group(2)
        constraint = match1.group(3)

        if constraint:
            sub_questions.append(f"What {entity_type} {constraint}?")
            sub_questions.append(f"Who {constraint}?")
        sub_questions.append(f"Who is the {entity_type}?")
        sub_questions.append(f"{entity_type} has {relation1}")

    # PATTERN 2: "When did the X that Y do Z?"
    pattern2 = r"(when|where)\s+did\s+the\s+(\w+)\s+that\s+(.*?)\s+(win|achieve|do|get)\s+(.*?)[\?]?"
    match2 = re.search(pattern2, text_lower)
    if match2:
        wh = match2.group(1)
        entity_type = match2.group(2)
        constraint = match2.group(3)
        action = match2.group(4)
        obj = match2.group(5)

        sub_questions.append(f"What {entity_type} {constraint}?")
        sub_questions.append(f"Which {entity_type} {constraint}?")
        sub_questions.append(f"{wh} did {action} {obj}?")
        sub_questions.append(f"{entity_type} {constraint}")

    # PATTERN 3: "Which X has Y and is Z?"
    pattern3 = r"which\s+(\w+)\s+(.*?)\s+and\s+(.*?)[\?]?"
    match3 = re.search(pattern3, text_lower)
    if match3:
        entity_type = match3.group(1)
        constraint1 = match3.group(2)
        constraint2 = match3.group(3)

        sub_questions.append(f"Which {entity_type} {constraint1}?")
        sub_questions.append(f"Which {entity_type} {constraint2}?")
        sub_questions.append(f"{entity_type} {constraint1}")
        sub_questions.append(f"{entity_type} {constraint2}")

    # PATTERN 4: "The X that contains Y had what Z?"
    pattern4 = r"the\s+(\w+)\s+that\s+(contains|includes|has)\s+(.*?)\s+(?:had|has)\s+what\s+(\w+)"
    match4 = re.search(pattern4, text_lower)
    if match4:
        entity_type = match4.group(1)
        relation = match4.group(2)
        obj = match4.group(3)
        target = match4.group(4)

        sub_questions.append(f"Which {entity_type} {relation} {obj}?")
        sub_questions.append(f"What {entity_type} has {obj}?")
        sub_questions.append(f"{entity_type} has {target}")
        sub_questions.append(f"What is the {target}?")

    # PATTERN 5: "Which X whose Y is Z borders/relates to W?"
    pattern5 = r"which\s+(\w+)\s+whose\s+(.*?)\s+is\s+(.*?)\s+(borders|relates|connects)\s+(.*?)[\?]?"
    match5 = re.search(pattern5, text_lower)
    if match5:
        entity_type = match5.group(1)
        property_path = match5.group(2)
        property_value = match5.group(3)
        relation = match5.group(4)
        target = match5.group(5)

        sub_questions.append(f"Which {entity_type} {property_path} {property_value}?")
        sub_questions.append(f"Which {entity_type} {relation} {target}?")
        sub_questions.append(f"{property_path} is {property_value}")
        sub_questions.append(f"{entity_type} {relation} {target}")

    # ⭐ PATTERN 6 (NEW): "What X did the Y who Z do/have/attend?"
    # Example: "What college did the President who attended Minneapolis High School go to?"
    pattern6 = r"what\s+(\w+)\s+did\s+(?:the\s+)?(\w+)\s+who\s+(.*?)\s+(?:go\s+to|attend|have|get|do)"
    match6 = re.search(pattern6, text_lower)
    if match6:
        target_entity = match6.group(1)  # "college"
        intermediate_type = match6.group(2)  # "president"
        constraint = match6.group(3)  # "attended Minneapolis High School"

        print(f"[DECOMPOSE] Detected 2-hop pattern: target={target_entity}, intermediate={intermediate_type}")

        # Sub-question 1: Find intermediate entity
        sub_questions.append(f"Which {intermediate_type} {constraint}?")
        sub_questions.append(f"Who {constraint}?")

        # Sub-question 2: Find target relation
        sub_questions.append(f"What {target_entity} did the {intermediate_type} attend?")
        sub_questions.append(f"{intermediate_type} attended {target_entity}")

        # Sub-question 3: Extract constraint as standalone
        sub_questions.append(f"{intermediate_type} {constraint}")
        sub_questions.append(constraint)

        # Sub-question 4: Simple entity queries
        sub_questions.append(f"What is {intermediate_type}?")
        if target_entity not in ["college", "university", "school"]:
            sub_questions.append(f"What is {target_entity}?")

    # PATTERN 7 (NEW): Extract named entities more aggressively
    capitalized = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
    for entity in capitalized:
        if len(entity.split()) >= 2:  # Multi-word entities
            sub_questions.append(f"What is {entity}?")
            sub_questions.append(f"{entity}")

    # Deduplicate
    seen = set()
    unique_questions = []
    for q in sub_questions:
        q_lower = q.lower().strip()
        if q_lower not in seen:
            seen.add(q_lower)
            unique_questions.append(q)

    print(f"[DECOMPOSE] Generated {len(unique_questions)} sub-questions")
    return unique_questions


# ============================================================================
# FIX 2: MULTI-HOP WIKIDATA EXPANSION
# ============================================================================

def expand_multi_hop_wikidata(
    seed_qids: List[str],
    props: List[str],
    max_hops: int = 2,
    max_nodes_per_hop: int = 30,
    lang: str = "en"
) -> List[Tuple[str, str, str]]:
    """
    Multi-hop Wikidata expansion with depth control.

    Args:
        seed_qids: Starting QIDs
        props: Properties to follow
        max_hops: Maximum hop distance (1 or 2)
        max_nodes_per_hop: Limit nodes per hop to avoid explosion

    Returns:
        List of (head_qid, property, tail_qid) edges
    """
    from wikidata_utils import wd_get_claims

    all_edges = []
    visited = set()

    # Convert property names to PIDs if needed
    from wikidata_utils import resolve_property_keys
    pids = resolve_property_keys(props, lang=lang)

    print(f"[EXPAND] Multi-hop expansion: {len(seed_qids)} seeds, {max_hops} hops, {len(pids)} properties")

    current_level = seed_qids
    for hop in range(max_hops):
        print(f"[EXPAND] Hop {hop+1}: expanding {len(current_level)} nodes")
        next_level = set()

        for qid in current_level:
            if qid in visited:
                continue
            visited.add(qid)

            # Get edges for this QID
            try:
                edges = wd_get_claims(
                    qid,
                    prop_keys=props,
                    lang=lang,
                    max_edges=max_nodes_per_hop // max(len(current_level), 1) + 1
                )

                all_edges.extend(edges)

                # Add tail QIDs to next level (for next hop)
                for _, _, tail_qid in edges:
                    if tail_qid not in visited and tail_qid.startswith("Q"):
                        next_level.add(tail_qid)

                time.sleep(0.1)  # Rate limiting

            except Exception as e:
                print(f"[WARN] Failed to expand {qid}: {e}")
                continue

        # Limit next level size to prevent explosion
        current_level = list(next_level)[:max_nodes_per_hop]

        if not current_level:
            break

    print(f"[EXPAND] Total: {len(all_edges)} edges, {len(visited)} nodes visited")
    return all_edges


# ============================================================================
# FIX 3: MULTI-HOP PATH EXTRACTION
# ============================================================================

def extract_multi_hop_paths(
    triples: List[Dict],
    max_path_length: int = 3,
    min_path_length: int = 2
) -> List[Dict]:
    """
    Extract explicit multi-hop paths from triples.

    Returns:
        List of paths with nodes and edges
    """
    # Build directed graph
    G = nx.DiGraph()

    for triple in triples:
        G.add_edge(
            triple['head'],
            triple['tail'],
            relation=triple['relation'],
            source=triple.get('source', 'unknown')
        )

    # Find all simple paths
    paths = []
    nodes = list(G.nodes())

    print(f"[PATHS] Extracting paths from {len(nodes)} nodes, {G.number_of_edges()} edges")

    # Limit to avoid combinatorial explosion
    max_pairs = min(len(nodes) * 10, 500)
    pairs_checked = 0

    for i, source in enumerate(nodes):
        for target in nodes[i+1:]:
            if pairs_checked >= max_pairs:
                break

            try:
                # Use simple_paths with cutoff
                all_paths = list(nx.all_simple_paths(
                    G, source, target,
                    cutoff=max_path_length
                ))

                for path_nodes in all_paths:
                    path_len = len(path_nodes) - 1
                    if min_path_length <= path_len <= max_path_length:
                        # Extract edges
                        edges = []
                        for j in range(len(path_nodes)-1):
                            edge_data = G.get_edge_data(path_nodes[j], path_nodes[j+1])
                            edges.append(edge_data['relation'])

                        paths.append({
                            'nodes': path_nodes,
                            'edges': edges,
                            'length': path_len
                        })

                pairs_checked += 1

            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue

    print(f"[PATHS] Found {len(paths)} paths")
    return paths


def score_paths_for_question(
    paths: List[Dict],
    question: str,
    embed_model: SentenceTransformer
) -> List[Tuple[Dict, float]]:
    """
    Score paths by relevance to question using embeddings.
    """
    if not paths:
        return []

    # Encode question
    q_emb = embed_model.encode([question], convert_to_tensor=True)

    scored_paths = []
    for path in paths:
        # Create path text representation
        path_text = " → ".join(path['nodes'])

        # Encode path
        path_emb = embed_model.encode([path_text], convert_to_tensor=True)

        # Cosine similarity
        score = torch.cosine_similarity(q_emb, path_emb, dim=1).item()

        scored_paths.append((path, score))

    # Sort by score descending
    scored_paths.sort(key=lambda x: x[1], reverse=True)

    return scored_paths


# ============================================================================
# FIX 4: MULTI-HOP AWARE RETRIEVAL
# ============================================================================

def retrieve_with_bridging_boost(
    question: str,
    all_embeddings: torch.Tensor,
    all_labels: List[str],
    all_types: List[str],
    triples: List[Dict],
    topk: int = 25,
    bridge_boost: float = 2.0,
    embed_model: Optional[SentenceTransformer] = None
) -> List[Tuple[str, str, float]]:
    """
    Multi-hop aware retrieval that boosts bridging nodes.

    Args:
        question: Question text
        all_embeddings: All node embeddings [N, D]
        all_labels: Node labels
        all_types: Node types
        triples: Graph triples for path finding
        topk: Final top-K to return
        bridge_boost: Multiplier for bridging node scores
        embed_model: Sentence transformer model

    Returns:
        List of (label, type, score) tuples
    """
    if embed_model is None:
        embed_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

    # Step 1: Initial retrieval (2x topk)
    q_emb = embed_model.encode([question], convert_to_tensor=True)

    # Normalize
    q_norm = torch.nn.functional.normalize(q_emb, dim=1)
    emb_norm = torch.nn.functional.normalize(all_embeddings, dim=1)

    # Cosine similarity
    sims = (q_norm @ emb_norm.T).squeeze(0)

    # Get top-2K indices initially
    initial_k = min(topk * 2, len(all_labels))
    top_indices = torch.argsort(sims, descending=True)[:initial_k].tolist()

    # Step 2: Build node set for path finding
    top_nodes = [all_labels[i] for i in top_indices]

    # Step 3: Find paths between top nodes
    bridging_nodes = find_bridging_nodes(top_nodes, triples, max_path_length=3)

    print(f"[RETRIEVAL] Found {len(bridging_nodes)} bridging nodes")

    # Step 4: Re-score with bridge boost
    final_scores = {}
    for i in top_indices:
        label = all_labels[i]
        ntype = all_types[i]
        score = sims[i].item()

        # Boost if bridging node
        if label in bridging_nodes:
            score *= bridge_boost
            print(f"[RETRIEVAL] Boosting bridging node: {label} ({score:.3f})")

        final_scores[label] = (ntype, score)

    # Sort and return top-K
    sorted_results = sorted(
        final_scores.items(),
        key=lambda x: x[1][1],
        reverse=True
    )[:topk]

    return [(label, ntype, score) for label, (ntype, score) in sorted_results]


def find_bridging_nodes(
    high_sim_nodes: List[str],
    triples: List[Dict],
    max_path_length: int = 3
) -> Set[str]:
    """
    Find nodes that bridge between high-similarity nodes.

    A bridging node is an intermediate node on a path between two
    high-similarity nodes.
    """
    # Build graph
    G = nx.Graph()  # Undirected for bidirectional paths
    for t in triples:
        G.add_edge(t['head'], t['tail'])

    bridging = set()

    # Find paths between pairs of high-sim nodes
    for i, source in enumerate(high_sim_nodes[:20]):  # Limit to avoid explosion
        if source not in G:
            continue

        for target in high_sim_nodes[i+1:i+11]:  # Check 10 targets per source
            if target not in G:
                continue

            try:
                # Find shortest path
                if nx.has_path(G, source, target):
                    path = nx.shortest_path(G, source, target)

                    if 2 < len(path) <= max_path_length + 1:
                        # Add intermediate nodes as bridging
                        for node in path[1:-1]:
                            bridging.add(node)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue

    return bridging


# ============================================================================
# FIX 5: PATH-AWARE VERBALIZATION
# ============================================================================

def verbalize_paths(
    paths: List[Tuple[Dict, float]],
    qid_to_label: Dict[str, str],
    max_paths: int = 5
) -> str:
    """
    Verbalize top-scoring paths as reasoning chains.

    Args:
        paths: List of (path_dict, score) tuples
        qid_to_label: QID to label mapping
        max_paths: Maximum paths to verbalize

    Returns:
        Formatted text
    """
    from wikidata_utils import wd_get_property_label

    output = ["Reasoning Chains:"]

    for i, (path, score) in enumerate(paths[:max_paths], 1):
        nodes = path['nodes']
        edges = path['edges']

        # Build chain representation
        chain_parts = []
        for j, node in enumerate(nodes):
            # Replace QID with label if available
            if node.startswith('Q') and node in qid_to_label:
                node_label = qid_to_label[node]
            else:
                node_label = node

            chain_parts.append(node_label)

            # Add relation
            if j < len(edges):
                rel = edges[j]
                # Make relation readable
                if rel.startswith('P'):
                    rel_label = wd_get_property_label(rel, 'en')
                else:
                    rel_label = rel.replace('_', ' ')

                chain_parts.append(f"--[{rel_label}]-->")

        chain_text = " ".join(chain_parts)
        output.append(f"{i}. {chain_text} (score: {score:.3f})")

    return "\n".join(output)


def verbalize_multi_hop_facts(
    retrieved_nodes: List[Tuple[str, str, float]],
    triples: List[Dict],
    question: str,
    qid_to_label: Dict[str, str],
    max_paths: int = 5,
    max_facts: int = 20
) -> str:
    """
    Enhanced verbalization maintaining multi-hop structure.
    """
    # Extract node names
    node_names = set()
    for label, ntype, _ in retrieved_nodes:
        if ntype == "entity":
            node_names.add(label.replace("ENTITY::", ""))
        else:
            node_names.add(label.replace("WIKIDATA::", ""))

    # Filter triples to retrieved nodes
    relevant_triples = []
    for t in triples:
        if t['head'] in node_names or t['tail'] in node_names:
            relevant_triples.append(t)

    print(f"[VERBALIZE] {len(relevant_triples)} relevant triples from {len(triples)} total")

    # Extract paths
    paths = extract_multi_hop_paths(relevant_triples, max_path_length=3)

    # Score paths
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('all-MiniLM-L6-v2')
    scored_paths = score_paths_for_question(paths, question, model)

    # Verbalize paths
    path_text = verbalize_paths(scored_paths[:max_paths], qid_to_label, max_paths)

    # Add flat facts as fallback
    fact_lines = []
    for t in relevant_triples[:max_facts]:
        head = qid_to_label.get(t['head'], t['head'])
        tail = qid_to_label.get(t['tail'], t['tail'])
        rel = t['relation'].replace('_', ' ')

        if rel.startswith('P'):
            from wikidata_utils import wd_get_property_label
            rel = wd_get_property_label(rel, 'en')

        fact_lines.append(f"- {head} {rel} {tail}")

    facts_text = "\n".join(fact_lines)

    return f"{path_text}\n\nSupporting Facts:\n{facts_text}"


# ============================================================================
# FIX 6: STRUCTURED MULTI-HOP PROMPTS
# ============================================================================

def build_multi_hop_prompt(
    question: str,
    graph_facts: str
) -> str:
    """
    Build a structured prompt optimized for multi-hop reasoning.
    """
    # Detect question type
    q_lower = question.lower()

    # Type 1: "What X did Y who Z"
    if re.search(r"what\s+\w+\s+did\s+(?:the\s+)?\w+\s+who", q_lower):
        prompt = f"""You are answering a TWO-STEP question.

Question: {question}

This requires TWO steps:
STEP 1: Identify the specific person/entity that satisfies the constraint
STEP 2: Find what that person/entity did or had

Knowledge Graph Information:
{graph_facts}

Solve step-by-step:

STEP 1 - Find the entity:
Look through the facts above. Which specific person or entity satisfies the constraint mentioned in the question?
Write the name:

STEP 2 - Find the answer:
Now look for facts about that entity. What did they do or have related to the question?
Final Answer: """

    # Type 2: "Which X has Y and Z"
    elif re.search(r"which\s+\w+.*\s+and\s+", q_lower):
        prompt = f"""Find the entity that satisfies ALL constraints.

Question: {question}

Knowledge Graph Information:
{graph_facts}

Look for an entity that satisfies ALL the constraints mentioned in the question.

Answer: """

    # Generic fallback
    else:
        prompt = f"""Answer the question using the knowledge graph information.

Knowledge Graph Information:
{graph_facts}

Question: {question}

If the question requires multiple steps, solve it step-by-step.

Answer: """

    return prompt


# ============================================================================
# INTEGRATION HELPER
# ============================================================================

def integrate_fixes_into_pipeline():
    """
    Instructions for integrating these fixes into the main pipeline.
    """
    instructions = """
    INTEGRATION GUIDE
    =================

    1. Question Decomposition:
       In relation_extraction.py, replace decompose_question() with:
       from multihop_fixes import decompose_question_enhanced

    2. Wikidata Expansion:
       In kg_build.py or qa_pipeline.py, replace expand_with_wikidata_qids() with:
       from multihop_fixes import expand_multi_hop_wikidata

    3. Add Education Properties:
       In qa_pipeline.py, PipelineConfig, add to wikidata_props:
       "educated at", "academic degree", "P69", "P512"

    4. Retrieval:
       In soft_prompting.py, replace cosine_topk() with:
       from multihop_fixes import retrieve_with_bridging_boost

    5. Verbalization:
       In soft_prompting.py, replace verbalize_with_labels() with:
       from multihop_fixes import verbalize_multi_hop_facts

    6. Prompting:
       In soft_prompting.py, replace build_llm_prompt_with_graph() with:
       from multihop_fixes import build_multi_hop_prompt

    Quick Test:
    -----------
    python test_multihop_fixes.py
    """

    return instructions


if __name__ == "__main__":
    print(integrate_fixes_into_pipeline())
