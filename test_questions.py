#!/usr/bin/env python3
"""
Test script for evaluating multi-hop question answering performance.
"""

import json
import os

# Test cases: difficult multi-hop questions with expected answers
TEST_CASES = [
    {
        "question": "When did the team that led by Giuseppe Marotta win the champions league?",
        "expected": "1996 UEFA Champions League Final",
        "type": "multi-hop",
        "hops": 2
    },
    {
        "question": "The country that contains Balochistan, Pakistan had what President in 1980?",
        "expected": "Muhammad Zia-ul-Haq",
        "type": "multi-hop",
        "hops": 2
    },
    {
        "question": "Which country has Mohamed Morsi in a government post and is the location of the Giza Pyramids?",
        "expected": "Egypt",
        "type": "multi-hop",
        "hops": 2
    },
    {
        "question": "Which country whose religious organization is led by the Ukrainian Orthodox Church of the Kyivan Patriarchate borders Slovakia?",
        "expected": "Ukraine",
        "type": "multi-hop",
        "hops": 2
    }
]


def normalize_answer(text: str) -> str:
    """Normalize answer for comparison."""
    import re
    # Lowercase and strip
    text = text.lower().strip()
    # Remove punctuation
    text = re.sub(r'[^\w\s]', ' ', text)
    # Remove extra whitespace
    text = ' '.join(text.split())
    return text


def check_answer(predicted: str, expected: str) -> bool:
    """Check if predicted answer matches expected."""
    pred_norm = normalize_answer(predicted)
    exp_norm = normalize_answer(expected)

    # Exact match
    if pred_norm == exp_norm:
        return True

    # Substring match (expected in predicted)
    if exp_norm in pred_norm:
        return True

    # Token overlap
    pred_tokens = set(pred_norm.split())
    exp_tokens = set(exp_norm.split())
    overlap = len(pred_tokens & exp_tokens) / max(len(exp_tokens), 1)
    if overlap >= 0.8:  # 80% token overlap
        return True

    return False


def save_results(results: list, output_path: str = "outputs/test_results.json"):
    """Save test results to file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[RESULTS] Saved to {output_path}")


def print_results(results: list):
    """Print formatted test results."""
    print("\n" + "="*80)
    print("TEST RESULTS")
    print("="*80)

    total = len(results)
    correct = sum(1 for r in results if r["correct"])

    for i, result in enumerate(results, 1):
        status = "✓ PASS" if result["correct"] else "✗ FAIL"
        print(f"\n[{i}/{total}] {status}")
        print(f"Question: {result['question']}")
        print(f"Expected: {result['expected']}")
        print(f"Predicted: {result['predicted'][:200]}...")  # Truncate long answers
        print(f"Match: {result['correct']}")

    print("\n" + "="*80)
    print(f"ACCURACY: {correct}/{total} ({100*correct/total:.1f}%)")
    print("="*80)


if __name__ == "__main__":
    print("Test cases loaded:")
    for i, test in enumerate(TEST_CASES, 1):
        print(f"{i}. {test['question'][:60]}... -> {test['expected']}")
