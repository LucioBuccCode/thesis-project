#!/usr/bin/env python3
"""
Integrated test runner for QA pipeline.
Runs the improved pipeline on difficult multi-hop questions.
"""

import sys
import argparse
from test_questions import TEST_CASES, check_answer, save_results, print_results
from qa_pipeline import create_optimized_pipeline, PipelineConfig


def run_single_test(pipeline, test_case, verbose=True):
    """Run a single test case."""
    question = test_case["question"]
    expected = test_case["expected"]

    if verbose:
        print("\n" + "="*80)
        print(f"TESTING: {question}")
        print("="*80)

    try:
        # Run pipeline
        result = pipeline.answer_question(question)

        # Get predicted answer
        predicted = result["enriched_answer"]

        # Check if correct
        correct = check_answer(predicted, expected)

        if verbose:
            print(f"\n[RESULT]")
            print(f"  Expected: {expected}")
            print(f"  Predicted: {predicted[:200]}...")
            print(f"  Status: {'✓ PASS' if correct else '✗ FAIL'}")
            print(f"  Elapsed: {result['elapsed_time']:.2f}s")

            # Show retrieved facts
            print(f"\n[RETRIEVED NODES] ({len(result['retrieved_nodes'])})")
            for label, ntype, score in result['retrieved_nodes'][:10]:
                print(f"  - {label:50s} | {ntype:8s} | {score:.3f}")

        return {
            "question": question,
            "expected": expected,
            "predicted": predicted,
            "correct": correct,
            "elapsed_time": result["elapsed_time"],
            "num_triples": len(result["triples"]),
            "num_retrieved": len(result["retrieved_nodes"])
        }

    except Exception as e:
        print(f"\n[ERROR] Test failed with exception: {e}")
        import traceback
        traceback.print_exc()

        return {
            "question": question,
            "expected": expected,
            "predicted": f"ERROR: {str(e)}",
            "correct": False,
            "elapsed_time": 0,
            "num_triples": 0,
            "num_retrieved": 0
        }


def run_all_tests(use_cache=True, verbose=True):
    """Run all test cases."""
    print("="*80)
    print("MULTI-HOP QA PIPELINE TEST SUITE")
    print("="*80)
    print(f"Total test cases: {len(TEST_CASES)}")
    print(f"Caching: {'Enabled' if use_cache else 'Disabled'}")
    print("="*80)

    # Create optimized pipeline
    config = PipelineConfig(
        # Enable all enhancements
        use_ensemble=True,
        use_decomposition=True,
        use_reranking=True,
        use_verbalization=True,
        use_instruction_model=True,

        # Increase limits for better coverage
        sp_topk=25,
        sp_mix_entity=12,
        sp_mix_wd=13,
        sp_max_facts=30,
        sp_max_new_tokens=200,

        # Extended Wikidata properties
        wikidata_props=[
            "spouse", "country of citizenship", "place of birth",
            "instance of", "occupation", "position held",
            "member of", "capital", "continent", "shares border with",
            "head of government", "head of state", "located in",
            "part of", "religion", "official language", "league",
            "sport", "participant in", "winner", "location"
        ],
        wikidata_max_edges_per_qid=20,

        # Performance
        enable_caching=use_cache,
    )

    pipeline = create_optimized_pipeline()
    pipeline.config = config

    # Run tests
    results = []
    for i, test_case in enumerate(TEST_CASES, 1):
        print(f"\n[TEST {i}/{len(TEST_CASES)}]")
        result = run_single_test(pipeline, test_case, verbose=verbose)
        results.append(result)

    # Print summary
    print_results(results)

    # Save results
    save_results(results, "outputs/test_results.json")

    # Calculate metrics
    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    accuracy = 100 * correct / total if total > 0 else 0

    avg_time = sum(r["elapsed_time"] for r in results) / total if total > 0 else 0
    avg_triples = sum(r["num_triples"] for r in results) / total if total > 0 else 0
    avg_retrieved = sum(r["num_retrieved"] for r in results) / total if total > 0 else 0

    print("\n" + "="*80)
    print("DETAILED METRICS")
    print("="*80)
    print(f"Accuracy: {accuracy:.1f}% ({correct}/{total})")
    print(f"Average time per question: {avg_time:.2f}s")
    print(f"Average triples extracted: {avg_triples:.1f}")
    print(f"Average nodes retrieved: {avg_retrieved:.1f}")
    print("="*80)

    return results


def main():
    parser = argparse.ArgumentParser(description="Run QA pipeline tests")
    parser.add_argument("--no-cache", action="store_true", help="Disable caching")
    parser.add_argument("--quiet", action="store_true", help="Reduce output verbosity")
    parser.add_argument("--single", type=int, help="Run only test number N (1-indexed)")

    args = parser.parse_args()

    if args.single:
        if 1 <= args.single <= len(TEST_CASES):
            pipeline = create_optimized_pipeline()
            if args.no_cache:
                pipeline.config.enable_caching = False

            test_case = TEST_CASES[args.single - 1]
            result = run_single_test(pipeline, test_case, verbose=not args.quiet)

            print("\n" + "="*80)
            print(f"RESULT: {'✓ PASS' if result['correct'] else '✗ FAIL'}")
            print("="*80)
        else:
            print(f"Error: Test number must be between 1 and {len(TEST_CASES)}")
            sys.exit(1)
    else:
        results = run_all_tests(use_cache=not args.no_cache, verbose=not args.quiet)

        # Exit with error code if any test failed
        if any(not r["correct"] for r in results):
            sys.exit(1)


if __name__ == "__main__":
    main()
