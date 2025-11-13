#!/usr/bin/env python3
"""
Refactored main entry point using centralized QAPipeline.

This is the new, improved version that uses the centralized pipeline
for better performance, caching, and maintainability.

For the legacy version, see main.py (kept for compatibility).
"""

import argparse
import os
import sys
from qa_pipeline import QAPipeline, PipelineConfig, create_optimized_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Multi-hop Question Answering with Knowledge Graphs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with optimized settings
  python main_refactored.py --text "Which country has Mohamed Morsi in a government post?"

  # Disable specific features
  python main_refactored.py --text "Your question" --no-ensemble --no-decomposition

  # Use custom model
  python main_refactored.py --text "Your question" --llm google/flan-t5-xl

  # Fast mode (skip HGT training, use cached embeddings)
  python main_refactored.py --text "Your question" --skip-hgt

  # Clear cache and run fresh
  python main_refactored.py --text "Your question" --clear-cache
        """
    )

    # Required
    parser.add_argument("--text", type=str, required=True,
                        help="Input question")

    # Device
    parser.add_argument("--device", type=str, default="auto",
                        choices=["auto", "cpu", "cuda"],
                        help="Device to use (default: auto)")

    # Models
    parser.add_argument("--triple-model", type=str,
                        default="pat-jj/text2triple-flan-t5",
                        help="Triple extraction model")
    parser.add_argument("--embed-model", type=str,
                        default="sentence-transformers/all-MiniLM-L6-v2",
                        help="Sentence embedding model")
    parser.add_argument("--llm", type=str,
                        default="google/flan-t5-large",
                        help="LLM for answer generation")

    # Feature toggles
    parser.add_argument("--no-ensemble", action="store_true",
                        help="Disable REBEL+Flan-T5 ensemble")
    parser.add_argument("--no-decomposition", action="store_true",
                        help="Disable question decomposition")
    parser.add_argument("--no-reranking", action="store_true",
                        help="Disable cross-encoder reranking")
    parser.add_argument("--no-verbalization", action="store_true",
                        help="Use soft prompts instead of verbalization")
    parser.add_argument("--no-instruction-model", action="store_true",
                        help="Use GPT-2 instead of Flan-T5")

    # Wikidata
    parser.add_argument("--wikidata-props", type=str,
                        default="spouse,country of citizenship,place of birth,instance of,occupation,position held,member of,capital,continent,shares border with,head of government,head of state,located in,part of",
                        help="Comma-separated Wikidata properties")
    parser.add_argument("--wikidata-max-edges", type=int, default=15,
                        help="Max Wikidata edges per QID")

    # HGT training
    parser.add_argument("--skip-hgt", action="store_true",
                        help="Skip HGT training (use existing embeddings)")
    parser.add_argument("--hgt-epochs", type=int, default=80,
                        help="HGT training epochs")
    parser.add_argument("--hgt-hidden", type=int, default=384,
                        help="HGT hidden dimension")

    # Retrieval & Generation
    parser.add_argument("--topk", type=int, default=25,
                        help="Top-K nodes to retrieve")
    parser.add_argument("--max-facts", type=int, default=30,
                        help="Maximum facts to verbalize")
    parser.add_argument("--max-tokens", type=int, default=200,
                        help="Maximum tokens to generate")

    # Performance
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable all caching")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Clear cache before running")

    # Output
    parser.add_argument("--output-dir", type=str, default="outputs",
                        help="Output directory")
    parser.add_argument("--quiet", action="store_true",
                        help="Reduce output verbosity")

    args = parser.parse_args()

    # Build configuration
    config = PipelineConfig(
        # Paths
        output_dir=args.output_dir,
        cache_dir=os.path.join(args.output_dir, "cache"),

        # Device
        device=args.device,

        # Models
        triple_extraction_model=args.triple_model,
        embed_model=args.embed_model,
        llm_model=args.llm,

        # Features
        use_ensemble=not args.no_ensemble,
        use_decomposition=not args.no_decomposition,
        use_reranking=not args.no_reranking,
        use_verbalization=not args.no_verbalization,
        use_instruction_model=not args.no_instruction_model,

        # Wikidata
        wikidata_props=[p.strip() for p in args.wikidata_props.split(",")],
        wikidata_max_edges_per_qid=args.wikidata_max_edges,

        # HGT
        hgt_epochs=args.hgt_epochs,
        hgt_hidden=args.hgt_hidden,

        # Retrieval & Generation
        sp_topk=args.topk,
        sp_mix_entity=args.topk // 2,
        sp_mix_wd=args.topk // 2,
        sp_max_facts=args.max_facts,
        sp_max_new_tokens=args.max_tokens,

        # Performance
        enable_caching=not args.no_cache,
    )

    # Create pipeline
    if not args.quiet:
        print("="*80)
        print("MULTI-HOP QUESTION ANSWERING PIPELINE")
        print("="*80)
        print(f"Question: {args.text}")
        print(f"Device: {config.device}")
        print(f"Ensemble: {config.use_ensemble}")
        print(f"Decomposition: {config.use_decomposition}")
        print(f"Reranking: {config.use_reranking}")
        print(f"Verbalization: {config.use_verbalization}")
        print(f"Caching: {config.enable_caching}")
        print("="*80)

    pipeline = QAPipeline(config)

    # Clear cache if requested
    if args.clear_cache:
        print("[INFO] Clearing cache...")
        pipeline.clear_cache()

    # Run pipeline
    try:
        result = pipeline.answer_question(args.text, skip_hgt_training=args.skip_hgt)

        # Print results
        if not args.quiet:
            print("\n" + "="*80)
            print("RESULTS")
            print("="*80)

            print(f"\n[BASELINE ANSWER]")
            print(result["baseline_answer"])

            print(f"\n[ENRICHED ANSWER (with Knowledge Graph)]")
            print(result["enriched_answer"])

            print(f"\n[STATISTICS]")
            print(f"  - Triples extracted: {len(result['triples'])}")
            print(f"  - Graph entities: {result['graph_meta']['entity_count']}")
            print(f"  - Graph wikidata nodes: {result['graph_meta']['wikidata_count']}")
            print(f"  - Retrieved nodes: {len(result['retrieved_nodes'])}")
            print(f"  - Elapsed time: {result['elapsed_time']:.2f}s")

            print(f"\n[TOP RETRIEVED NODES]")
            for i, (label, ntype, score) in enumerate(result['retrieved_nodes'][:15], 1):
                print(f"  {i:2d}. {label:50s} | {ntype:8s} | {score:.3f}")

            print("\n" + "="*80)
        else:
            # Quiet mode: just print the answer
            print(result["enriched_answer"])

        return 0

    except Exception as e:
        print(f"\n[ERROR] Pipeline failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
