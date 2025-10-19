
import argparse
import os
import json
import torch
from relation_extraction import extract_triples
from kg_build import build_enriched_hetero_graph
from hgt_train_utils import train_hgt_all_edges
from soft_prompting import run_soft_prompting

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", type=str, required=True, help="Input sentence or short paragraph")
    parser.add_argument("--device", type=str, default="auto", choices=["auto","cpu","cuda"])
    parser.add_argument("--model", type=str, default="pat-jj/text2triple-flan-t5", help="Text-to-triple model (English)")
    parser.add_argument("--embed-model", type=str, default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--no-wikidata", action="store_true")
    parser.add_argument("--wikidata-edges", type=int, default=5)
    parser.add_argument("--no-train-hgt", action="store_true", help="Skip HGT training step")
        # HGT training controls
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--neg-per-pos", type=int, default=1)
    parser.add_argument("--lr", type=float, default=5e-4)              # più stabile del 2e-3
    parser.add_argument("--clip", type=float, default=1.0)             # gradient clipping (0 = off)
    parser.add_argument("--early", type=int, default=5)                # early stopping patience (0 = off)
    parser.add_argument("--use-rel-balanced", action="store_true")     # batch bilanciati per relazione
    parser.add_argument("--filter-negs", action="store_true")          # filtra falsi negativi
    parser.add_argument("--wd-props", type=str, default="spouse,country of citizenship,place of birth,instance of")
    parser.add_argument("--wd-props-lang", type=str, default="en")
    parser.add_argument("--wd-max-edges-per-qid", type=int, default=8)
    parser.add_argument("--wd-preferred-rank-only", action="store_true")
    parser.add_argument("--soft-prompt", action="store_true",
                        help="Esegui confronto LLM: baseline vs soft-prompt con graph embeddings")
    parser.add_argument("--llm", type=str, default="gpt2",
                        help="Modello HF (es. gpt2, mistralai/Mistral-7B-Instruct, ecc.)")
    parser.add_argument("--sp-topk", type=int, default=16)
    parser.add_argument("--sp-mix-entity", type=int, default=8)
    parser.add_argument("--sp-mix-wd", type=int, default=8)
    parser.add_argument("--sp-max-new-tokens", type=int, default=120)

    # New enhancement flags
    parser.add_argument("--use-ensemble", action="store_true", help="Use REBEL + Flan-T5 ensemble for extraction")
    parser.add_argument("--use-decomposition", action="store_true", help="Decompose complex questions")
    parser.add_argument("--use-reranking", action="store_true", help="Use cross-encoder for entity linking")
    parser.add_argument("--use-verbalization", action="store_true", help="Use graph verbalization instead of soft prompts")
    parser.add_argument("--use-instruction-model", action="store_true", help="Use Flan-T5 instead of GPT-2")
    parser.add_argument("--train-projector", action="store_true", help="Train soft prompt projector before generation")


    args = parser.parse_args()

    device = "cuda" if (args.device in ("auto","cuda") and torch.cuda.is_available()) else "cpu"
    os.makedirs("outputs", exist_ok=True)

    print(f"[1/4] Extracting triples with {args.model} on device={device}...")
    print(f"  - Ensemble: {args.use_ensemble}")
    print(f"  - Decomposition: {args.use_decomposition}")

    triples = extract_triples(
        args.text,
        model_name=args.model,
        device=("cuda" if device=="cuda" else "cpu"),
        use_ensemble=args.use_ensemble,
        use_decomposition=args.use_decomposition
    )
    print(f"  found {len(triples)} triples")
    with open("outputs/triples.json", "w", encoding="utf-8") as f:
        json.dump(triples, f, ensure_ascii=False, indent=2)

    print(f"[2/4] Costruisci grafo arricchito con Wikidata...")
    print(f"  - Reranking: {args.use_reranking}")

    # [2] Costruisci grafo arricchito con Wikidata
    data, meta = build_enriched_hetero_graph(
        triples,
        embed_model="sentence-transformers/all-MiniLM-L6-v2",
        device="cuda" if args.device=="cuda" else "cpu",
        wd_props=[p.strip() for p in args.wd_props.split(",")] if getattr(args, "wd_props", "") else None,
        wd_lang=getattr(args, "wd_props_lang", "en"),
        wd_max_edges_per_qid=getattr(args, "wd_max_edges_per_qid", 8),
        wd_preferred_only=getattr(args, "wd_preferred_rank_only", False),
        question_context=args.text,
        use_reranking=args.use_reranking,
    )
    print(f"[graph] entity={meta['entity_count']} | wikidata={meta['wikidata_count']}")

    print(f"[3/4] Allena HGT su tutti gli archi (grafo espanso e informativo) {args.model} on device={device}...")

    # [3] Allena HGT su tutti gli archi (grafo espanso e informativo)
    out_x = train_hgt_all_edges(
        data,
        device=args.device, hidden=384, layers=2,
        lr=3e-4, epochs=80, neg_per_pos=2, per_rel=128,
        early=8, clip=1.0
    )

    # Salva embedding
    os.makedirs("outputs", exist_ok=True)
    if "entity" in out_x:
        torch.save(out_x["entity"], "outputs/graph_entity_embs.pt")
    if "wikidata" in out_x:
        torch.save(out_x["wikidata"], "outputs/graph_wikidata_embs.pt")
    with open("outputs/graph_meta.json","w",encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("[done] Saved enriched graph embeddings in outputs/")

    # [3.5] Train projector if requested and not using verbalization
    if args.train_projector and not args.use_verbalization:
        print("\n[3.5/4] Training soft prompt projector...")
        from train_projector import ContrastiveProjectorTrainer, create_training_data_from_graph

        try:
            # Create training data from graph embeddings
            train_data = create_training_data_from_graph(
                entity_emb_path="outputs/graph_entity_embs.pt",
                wd_emb_path="outputs/graph_wikidata_embs.pt",
                triples_path="outputs/triples_expanded.json",
                llm_name=args.llm,
                device=args.device,
                num_negatives=3
            )

            # Get dimensions from first sample
            d_graph = train_data[0][0].shape[0]
            d_llm = train_data[0][1].shape[0]

            print(f"  - Training data: {len(train_data)} pairs")
            print(f"  - Graph dim: {d_graph}, LLM dim: {d_llm}")

            # Initialize and train projector
            trainer = ContrastiveProjectorTrainer(
                d_graph=d_graph,
                d_llm=d_llm,
                device=args.device,
                temperature=0.07
            )

            trainer.train(train_data, epochs=20, lr=1e-3, batch_size=16)
            trainer.save("outputs/trained_projector.pt")

            print("  ✓ Projector trained and saved")

        except Exception as e:
            print(f"  [ERROR] Projector training failed: {e}")
            print("  [WARN] Continuing with random projector")
    elif args.train_projector and args.use_verbalization:
        print("\n[INFO] --train-projector ignored (using verbalization mode)")

    print("\n[4/4] Soft prompting: confronto baseline vs graph-augmented")
    print(f"  - Verbalization: {args.use_verbalization}")
    print(f"  - Instruction Model: {args.use_instruction_model}")
    print(f"  - Trained Projector: {args.train_projector and not args.use_verbalization}")

    baseline, enriched, retrieved = run_soft_prompting(
        text=args.text,              # <-- la tua domanda
        device=args.device,
        embed_model=args.embed_model,
        llm_name=args.llm,
        topk=args.sp_topk,
        mix_entity=args.sp_mix_entity,
        mix_wd=args.sp_mix_wd,
        max_new_tokens=args.sp_max_new_tokens,
        use_verbalization=args.use_verbalization,
        use_instruction_model=args.use_instruction_model
    )

    print("\n=== Baseline (solo domanda) ===")
    print(baseline)

    print("\n=== Soft-Prompt (grafo embeddings + domanda) ===")
    print(enriched)

    print("\n--- Nodi usati per soft prompt (label | tipo | cosine) ---")
    for lab, typ, sc in retrieved:
        print(f"{lab:40s} | {typ:8s} | {sc:.3f}")

if __name__ == "__main__":
    main()
