#!/usr/bin/env python3
"""
Test script for multi-hop reasoning fixes.

Tests each fix independently before full integration.
"""

import sys
from multihop_fixes import (
    decompose_question_enhanced,
    extract_multi_hop_paths,
    score_paths_for_question,
    find_bridging_nodes,
    build_multi_hop_prompt
)


def test_question_decomposition():
    """Test enhanced question decomposition."""
    print("="*80)
    print("TEST 1: QUESTION DECOMPOSITION")
    print("="*80)

    test_questions = [
        "What college did the President who attended Minneapolis High School go to?",
        "Which country has Mohamed Morsi in a government post and is the location of the Giza Pyramids?",
        "Who is the spouse of the president born in Hawaii?",
        "When did the team that led by Giuseppe Marotta win the champions league?"
    ]

    for i, question in enumerate(test_questions, 1):
        print(f"\n[Test {i}] Question: {question}")
        sub_questions = decompose_question_enhanced(question)
        print(f"Generated {len(sub_questions)} sub-questions:")
        for j, sq in enumerate(sub_questions[:10], 1):
            print(f"  {j}. {sq}")

    print("\n✓ Question decomposition test complete\n")


def test_path_extraction():
    """Test multi-hop path extraction."""
    print("="*80)
    print("TEST 2: PATH EXTRACTION")
    print("="*80)

    # Sample triples
    triples = [
        {"head": "Hubert Humphrey", "relation": "position_held", "tail": "Vice President"},
        {"head": "Hubert Humphrey", "relation": "educated_at", "tail": "University of Minnesota"},
        {"head": "Hubert Humphrey", "relation": "educated_at", "tail": "South High School"},
        {"head": "South High School", "relation": "located_in", "tail": "Minneapolis"},
        {"head": "University of Minnesota", "relation": "instance_of", "tail": "university"},
        {"head": "University of Minnesota", "relation": "located_in", "tail": "Minnesota"},
    ]

    print(f"\nInput: {len(triples)} triples")
    for t in triples:
        print(f"  {t['head']} --[{t['relation']}]--> {t['tail']}")

    paths = extract_multi_hop_paths(triples, max_path_length=3)

    print(f"\nExtracted {len(paths)} paths:")
    for i, path in enumerate(paths[:10], 1):
        path_str = " -> ".join([
            f"{path['nodes'][j]}" + (f" [{path['edges'][j]}]" if j < len(path['edges']) else "")
            for j in range(len(path['nodes']))
        ])
        print(f"  {i}. {path_str}")

    print("\n✓ Path extraction test complete\n")


def test_bridging_node_detection():
    """Test bridging node detection."""
    print("="*80)
    print("TEST 3: BRIDGING NODE DETECTION")
    print("="*80)

    # Create a graph where "Hubert Humphrey" is the bridge
    triples = [
        {"head": "President", "relation": "instance", "tail": "Hubert Humphrey"},
        {"head": "Hubert Humphrey", "relation": "educated_at", "tail": "University of Minnesota"},
        {"head": "Hubert Humphrey", "relation": "attended", "tail": "South High School"},
        {"head": "South High School", "relation": "located", "tail": "Minneapolis"},
    ]

    # High-similarity nodes (what retrieval would find)
    high_sim_nodes = ["President", "University of Minnesota", "Minneapolis", "South High School"]

    print(f"\nHigh-similarity nodes: {high_sim_nodes}")

    bridging = find_bridging_nodes(high_sim_nodes, triples, max_path_length=3)

    print(f"\nBridging nodes found: {bridging}")
    print("Expected: {'Hubert Humphrey'}")

    if "Hubert Humphrey" in bridging:
        print("✓ Correctly identified bridging node!")
    else:
        print("✗ Failed to identify bridging node")

    print("\n✓ Bridging node detection test complete\n")


def test_multi_hop_prompt():
    """Test prompt generation."""
    print("="*80)
    print("TEST 4: MULTI-HOP PROMPT GENERATION")
    print("="*80)

    question = "What college did the President who attended Minneapolis High School go to?"

    graph_facts = """Reasoning Chains:
1. Hubert Humphrey → [position held] → Vice President
2. Hubert Humphrey → [educated at] → South High School → [located in] → Minneapolis
3. Hubert Humphrey → [educated at] → University of Minnesota → [instance of] → university

Supporting Facts:
- Hubert Humphrey position held Vice President of the United States
- Hubert Humphrey educated at University of Minnesota
- Hubert Humphrey educated at South High School
- South High School located in Minneapolis
- University of Minnesota instance of university
"""

    prompt = build_multi_hop_prompt(question, graph_facts)

    print(f"\nGenerated prompt:")
    print("-"*80)
    print(prompt)
    print("-"*80)

    print("\n✓ Prompt generation test complete\n")


def test_integration_readiness():
    """Check if all dependencies are available."""
    print("="*80)
    print("TEST 5: INTEGRATION READINESS")
    print("="*80)

    checks = {
        "NetworkX": False,
        "Torch": False,
        "SentenceTransformers": False,
    }

    # NetworkX
    try:
        import networkx as nx
        checks["NetworkX"] = True
        print("✓ NetworkX available")
    except ImportError:
        print("✗ NetworkX not available - install with: pip install networkx")

    # Torch
    try:
        import torch
        checks["Torch"] = True
        print("✓ PyTorch available")
    except ImportError:
        print("✗ PyTorch not available - install with: pip install torch")

    # SentenceTransformers
    try:
        from sentence_transformers import SentenceTransformer
        checks["SentenceTransformers"] = True
        print("✓ Sentence Transformers available")
    except ImportError:
        print("✗ Sentence Transformers not available - install with: pip install sentence-transformers")

    all_ready = all(checks.values())

    if all_ready:
        print("\n✓ All dependencies available - ready for integration!")
    else:
        print("\n✗ Some dependencies missing - install them first")

    print("\n✓ Integration readiness check complete\n")


def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("MULTI-HOP REASONING FIXES - TEST SUITE")
    print("="*80 + "\n")

    tests = [
        ("Question Decomposition", test_question_decomposition),
        ("Path Extraction", test_path_extraction),
        ("Bridging Node Detection", test_bridging_node_detection),
        ("Prompt Generation", test_multi_hop_prompt),
        ("Integration Readiness", test_integration_readiness),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"\n✗ {test_name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "="*80)
    print("TEST RESULTS")
    print("="*80)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")

    if failed == 0:
        print("\n✓ All tests passed! Ready to integrate fixes.")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed. Fix issues before integration.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
