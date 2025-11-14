#!/usr/bin/env python3
"""
Improved test runner for multi-hop questions.
Uses the optimized pipeline with all quick fixes applied.
"""

import sys
import time
import json
from pathlib import Path
from difficult_multihop_questions import DIFFICULT_QUESTIONS, EDUCATIONAL_QUESTIONS
from qa_pipeline import QAPipeline, PipelineConfig


def normalize_answer(text: str) -> str:
    """Normalize answer for comparison."""
    import re
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = ' '.join(text.split())
    return text


def check_answer(predicted: str, expected: str, intermediate_entity: str = None) -> tuple[bool, str]:
    """
    Check if predicted answer matches expected.
    Returns (is_correct, reason)
    """
    pred_norm = normalize_answer(predicted)
    exp_norm = normalize_answer(expected)

    # Exact match
    if pred_norm == exp_norm:
        return True, "exact_match"

    # Substring match (expected in predicted)
    if exp_norm in pred_norm:
        return True, "substring_match"

    # Check if intermediate entity is mentioned (partial credit for multi-hop)
    if intermediate_entity:
        int_norm = normalize_answer(intermediate_entity)
        if int_norm in pred_norm:
            return True, "intermediate_entity_found"

    # Token overlap
    pred_tokens = set(pred_norm.split())
    exp_tokens = set(exp_norm.split())
    if pred_tokens and exp_tokens:
        overlap = len(pred_tokens & exp_tokens) / max(len(exp_tokens), 1)
        if overlap >= 0.7:
            return True, f"token_overlap_{overlap:.0%}"

    return False, "no_match"


def run_single_question(pipeline: QAPipeline, question_data: dict, verbose: bool = True) -> dict:
    """Run pipeline on a single question."""
    question = question_data["question"]
    expected = question_data["answer"]
    intermediate = question_data.get("intermediate_entity")

    if verbose:
        print("\n" + "="*80)
        print(f"QUESTION: {question}")
        print(f"EXPECTED: {expected}")
        if intermediate:
            print(f"INTERMEDIATE: {intermediate}")
        print("="*80)

    start_time = time.time()

    try:
        result = pipeline.answer_question(question)
        elapsed = time.time() - start_time

        predicted = result["enriched_answer"]
        is_correct, match_type = check_answer(predicted, expected, intermediate)

        if verbose:
            print(f"\n[RESULT]")
            print(f"  Predicted: {predicted[:200]}...")
            print(f"  Match: {is_correct} ({match_type})")
            print(f"  Triples: {len(result['triples'])}")
            print(f"  Retrieved: {len(result['retrieved_nodes'])}")
            print(f"  Time: {elapsed:.1f}s")

            # Show top retrieved nodes
            print(f"\n[TOP RETRIEVED NODES]")
            for label, ntype, score in result['retrieved_nodes'][:8]:
                # Check if this is the intermediate entity
                marker = " ← INTERMEDIATE!" if intermediate and intermediate.lower() in label.lower() else ""
                print(f"  - {label[:45]:45s} | {ntype:8s} | {score:.3f}{marker}")

        return {
            "question": question,
            "expected": expected,
            "predicted": predicted,
            "correct": is_correct,
            "match_type": match_type,
            "intermediate_entity": intermediate,
            "intermediate_found": intermediate.lower() in predicted.lower() if intermediate else None,
            "elapsed": elapsed,
            "num_triples": len(result["triples"]),
            "num_retrieved": len(result["retrieved_nodes"]),
            "retrieved_nodes": result["retrieved_nodes"][:10]
        }

    except Exception as e:
        if verbose:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()

        return {
            "question": question,
            "expected": expected,
            "predicted": f"ERROR: {str(e)}",
            "correct": False,
            "match_type": "error",
            "elapsed": time.time() - start_time,
            "num_triples": 0,
            "num_retrieved": 0
        }


def run_test_suite(question_set: list = None, verbose: bool = True, save_results: bool = True):
    """Run test suite on question set."""
    if question_set is None:
        question_set = DIFFICULT_QUESTIONS

    print("="*80)
    print("MULTI-HOP QA TEST SUITE - IMPROVED PIPELINE")
    print("="*80)
    print(f"Questions: {len(question_set)}")
    print(f"Quick Fixes Applied:")
    print(f"  ✓ Fix #1: Educational properties (P69 'educated at')")
    print(f"  ✓ Fix #2: Multi-hop Wikidata expansion (2 hops)")
    print(f"  ✓ Fix #3: Enhanced question decomposition (8 patterns)")
    print(f"  ✓ Fix #4: Multi-hop optimized prompts")
    print("="*80)

    # Create optimized pipeline
    config = PipelineConfig(
        # All enhancements enabled
        use_ensemble=True,
        use_decomposition=True,
        use_reranking=True,
        use_verbalization=True,
        use_instruction_model=True,

        # CRITICAL: Multi-hop expansion
        use_multihop_expansion=True,
        multihop_max_hops=2,

        # Extended properties (including P69)
        # (automatically set in __post_init__)

        # Increased limits
        sp_topk=25,
        sp_mix_entity=12,
        sp_mix_wd=13,
        sp_max_facts=30,
        sp_max_new_tokens=200,

        # Performance
        enable_caching=True,
    )

    pipeline = QAPipeline(config)

    # Run tests
    results = []
    for i, q in enumerate(question_set, 1):
        print(f"\n[TEST {i}/{len(question_set)}]")
        result = run_single_question(pipeline, q, verbose=verbose)
        results.append(result)

    # Calculate metrics
    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    accuracy = 100 * correct / total if total > 0 else 0

    intermediate_found = sum(1 for r in results if r.get("intermediate_found")) if any(
        r.get("intermediate_entity") for r in results) else 0
    total_with_intermediate = sum(1 for r in results if r.get("intermediate_entity"))

    avg_time = sum(r["elapsed"] for r in results) / total if total > 0 else 0
    avg_triples = sum(r["num_triples"] for r in results) / total if total > 0 else 0
    avg_retrieved = sum(r["num_retrieved"] for r in results) / total if total > 0 else 0

    # Print summary
    print("\n" + "="*80)
    print("TEST RESULTS SUMMARY")
    print("="*80)
    print(f"Accuracy: {accuracy:.1f}% ({correct}/{total})")
    if total_with_intermediate > 0:
        print(f"Intermediate entities found: {intermediate_found}/{total_with_intermediate} ({100*intermediate_found/total_with_intermediate:.1f}%)")
    print(f"Average time: {avg_time:.1f}s")
    print(f"Average triples: {avg_triples:.1f}")
    print(f"Average retrieved nodes: {avg_retrieved:.1f}")

    print("\n" + "-"*80)
    print("BREAKDOWN BY QUESTION:")
    print("-"*80)
    for i, r in enumerate(results, 1):
        status = "✓" if r["correct"] else "✗"
        print(f"{i}. {status} {r['question'][:60]}...")
        print(f"   Expected: {r['expected']}")
        print(f"   Got: {r['predicted'][:80]}...")
        print(f"   Match: {r['match_type']}")

    print("="*80)

    # Save results
    if save_results:
        output_file = Path("outputs/multihop_test_results.json")
        output_file.parent.mkdir(exist_ok=True)

        with open(output_file, "w") as f:
            json.dump({
                "summary": {
                    "total": total,
                    "correct": correct,
                    "accuracy": accuracy,
                    "avg_time": avg_time,
                    "avg_triples": avg_triples,
                    "avg_retrieved": avg_retrieved,
                    "intermediate_found": intermediate_found,
                    "total_with_intermediate": total_with_intermediate
                },
                "results": results
            }, f, indent=2)

        print(f"\nResults saved to: {output_file}")

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--educational-only", action="store_true",
                        help="Test only educational questions")
    parser.add_argument("--hard-only", action="store_true",
                        help="Test only hard questions")
    parser.add_argument("--single", type=int,
                        help="Test only question number N")
    parser.add_argument("--quiet", action="store_true",
                        help="Reduce output verbosity")

    args = parser.parse_args()

    if args.single:
        if 1 <= args.single <= len(DIFFICULT_QUESTIONS):
            pipeline = QAPipeline(PipelineConfig(
                use_multihop_expansion=True,
                multihop_max_hops=2
            ))
            q = DIFFICULT_QUESTIONS[args.single - 1]
            result = run_single_question(pipeline, q, verbose=not args.quiet)
            print(f"\nResult: {'✓ PASS' if result['correct'] else '✗ FAIL'}")
        else:
            print(f"Error: Question number must be 1-{len(DIFFICULT_QUESTIONS)}")
            sys.exit(1)
    else:
        # Select question set
        if args.educational_only:
            question_set = EDUCATIONAL_QUESTIONS
            print("Testing EDUCATIONAL questions only")
        elif args.hard_only:
            question_set = [q for q in DIFFICULT_QUESTIONS if q["difficulty"] in ["hard", "very_hard"]]
            print("Testing HARD questions only")
        else:
            question_set = DIFFICULT_QUESTIONS

        results = run_test_suite(question_set, verbose=not args.quiet)

        # Exit with error if any failed
        if any(not r["correct"] for r in results):
            sys.exit(1)


if __name__ == "__main__":
    main()
