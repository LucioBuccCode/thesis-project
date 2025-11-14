#!/usr/bin/env python3
"""
Centralized Question Answering Pipeline with optimizations and caching.

This module provides a unified QAPipeline class that:
- Manages model loading/caching to avoid repeated loads
- Provides intelligent caching of intermediate results
- Optimizes multi-hop question answering
- Centralizes all configuration
"""

import os
import json
import hashlib
import time
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, asdict
import torch
from pathlib import Path
from hgt_reasoning_integration import HGTReasoningIntegrator
from soft_prompting_enhanced import run_soft_prompting_enhanced

@dataclass
class PipelineConfig:
    """Configuration for QA Pipeline."""
    # Paths
    output_dir: str = "outputs"
    cache_dir: str = "outputs/cache"

    # Device
    device: str = "auto"

    # Models
    triple_extraction_model: str = "pat-jj/text2triple-flan-t5"
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    llm_model: str = "google/flan-t5-large"

    # Feature flags
    use_ensemble: bool = True
    use_decomposition: bool = True
    use_reranking: bool = True
    use_verbalization: bool = True
    use_instruction_model: bool = True

    # Wikidata
    wikidata_props: List[str] = None
    wikidata_lang: str = "en"
    wikidata_max_edges_per_qid: int = 10
    wikidata_preferred_only: bool = False

    # HGT training
    hgt_hidden: int = 384
    hgt_layers: int = 2
    hgt_heads: int = 2
    hgt_lr: float = 3e-4
    hgt_epochs: int = 80
    hgt_neg_per_pos: int = 2
    hgt_per_rel: int = 128
    hgt_early_stopping: int = 8
    hgt_clip: float = 1.0

    # Soft prompting
    sp_topk: int = 20
    sp_mix_entity: int = 10
    sp_mix_wd: int = 10
    sp_max_new_tokens: int = 150
    sp_max_facts: int = 25

    # Performance
    enable_caching: bool = True
    cache_embeddings: bool = True
    cache_triples: bool = True
    batch_wikidata_calls: bool = True

    def __post_init__(self):
        if self.wikidata_props is None:
            self.wikidata_props = [
                "spouse", "country of citizenship", "place of birth",
                "instance of", "occupation", "position held",
                "member of", "capital", "continent", "shares border with"
            ]
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)


class ModelCache:
    """Cache for loaded models to avoid repeated loading."""

    def __init__(self):
        self._models = {}

    def get_or_load(self, model_type: str, model_name: str, loader_fn, device: str = "cpu"):
        """Get cached model or load it."""
        cache_key = f"{model_type}:{model_name}:{device}"

        if cache_key not in self._models:
            print(f"[CACHE] Loading {model_type} model: {model_name}")
            self._models[cache_key] = loader_fn(model_name, device)
        else:
            print(f"[CACHE] Using cached {model_type} model: {model_name}")

        return self._models[cache_key]

    def clear(self):
        """Clear all cached models."""
        self._models.clear()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


class ResultCache:
    """Cache for intermediate computation results."""

    def __init__(self, cache_dir: str = "outputs/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_key(self, prefix: str, data: Any) -> str:
        """Generate cache key from data."""
        # Create hash of data
        data_str = json.dumps(data, sort_keys=True)
        data_hash = hashlib.md5(data_str.encode()).hexdigest()
        return f"{prefix}_{data_hash}"

    def get(self, prefix: str, data: Any) -> Optional[Any]:
        """Get cached result."""
        key = self._get_key(prefix, data)
        cache_file = self.cache_dir / f"{key}.json"

        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    print(f"[CACHE] Hit for {prefix}")
                    return json.load(f)
            except Exception as e:
                print(f"[CACHE] Error reading cache: {e}")
                return None
        return None

    def set(self, prefix: str, data: Any, result: Any):
        """Set cached result."""
        key = self._get_key(prefix, data)
        cache_file = self.cache_dir / f"{key}.json"

        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[CACHE] Error writing cache: {e}")


class QAPipeline:
    """
    Centralized Question Answering Pipeline.

    This class manages the entire QA workflow:
    1. Triple extraction from questions
    2. Knowledge graph construction with Wikidata
    3. HGT training for graph embeddings
    4. Answer generation with soft prompting/verbalization
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        """Initialize pipeline with configuration."""
        self.config = config or PipelineConfig()

        # Set device
        if self.config.device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = self.config.device

        print(f"[PIPELINE] Initialized on device: {self.device}")
        print(f"[PIPELINE] Caching enabled: {self.config.enable_caching}")

        # Initialize caches
        self.model_cache = ModelCache()
        self.result_cache = ResultCache(self.config.cache_dir) if self.config.enable_caching else None

        # Lazy loading for heavy imports
        self._triple_extractor = None
        self._kg_builder = None
        self._hgt_trainer = None
        self._generator = None

    def extract_triples(self, question: str) -> List[Dict[str, str]]:
        """
        Extract triples from question with caching.

        Args:
            question: Input question

        Returns:
            List of triples
        """
        # Check cache
        if self.result_cache:
            cached = self.result_cache.get("triples", {
                "question": question,
                "ensemble": self.config.use_ensemble,
                "decomposition": self.config.use_decomposition
            })
            if cached:
                return cached

        # Import and extract
        from relation_extraction import extract_triples

        print(f"[1/4] Extracting triples...")
        print(f"  - Ensemble: {self.config.use_ensemble}")
        print(f"  - Decomposition: {self.config.use_decomposition}")

        triples = extract_triples(
            question,
            model_name=self.config.triple_extraction_model,
            device=self.device,
            use_ensemble=self.config.use_ensemble,
            use_decomposition=self.config.use_decomposition
        )

        print(f"  - Found {len(triples)} triples")

        # Save to outputs
        output_file = os.path.join(self.config.output_dir, "triples.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(triples, f, ensure_ascii=False, indent=2)

        # Cache result
        if self.result_cache:
            self.result_cache.set("triples", {
                "question": question,
                "ensemble": self.config.use_ensemble,
                "decomposition": self.config.use_decomposition
            }, triples)

        return triples

    def build_knowledge_graph(self, triples: List[Dict[str, str]], question: str):
        """
        Build enriched knowledge graph from triples.

        Args:
            triples: Extracted triples
            question: Original question for context

        Returns:
            (HeteroData graph, metadata dict)
        """
        from kg_build import build_enriched_hetero_graph

        print(f"[2/4] Building knowledge graph...")
        print(f"  - Reranking: {self.config.use_reranking}")
        print(f"  - Wikidata props: {len(self.config.wikidata_props)}")

        data, meta = build_enriched_hetero_graph(
            triples,
            embed_model=self.config.embed_model,
            device=self.device,
            wd_props=self.config.wikidata_props,
            wd_lang=self.config.wikidata_lang,
            wd_max_edges_per_qid=self.config.wikidata_max_edges_per_qid,
            wd_preferred_only=self.config.wikidata_preferred_only,
            question_context=question,
            use_reranking=self.config.use_reranking
        )

        print(f"  - Entities: {meta['entity_count']}")
        print(f"  - Wikidata nodes: {meta['wikidata_count']}")

        # Save graph metadata
        meta_file = os.path.join(self.config.output_dir, "graph_meta.json")
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        return data, meta

    def train_hgt(self, graph_data):
        """
        Train HGT model on graph.

        Args:
            graph_data: HeteroData graph

        Returns:
            Dict of node type embeddings
        """
        from hgt_train_utils import train_hgt_all_edges

        print(f"[3/4] Training HGT...")
        print(f"  - Hidden: {self.config.hgt_hidden}")
        print(f"  - Layers: {self.config.hgt_layers}")
        print(f"  - Epochs: {self.config.hgt_epochs}")

        embeddings = train_hgt_all_edges(
            graph_data,
            device=self.device,
            hidden=self.config.hgt_hidden,
            layers=self.config.hgt_layers,
            lr=self.config.hgt_lr,
            epochs=self.config.hgt_epochs,
            neg_per_pos=self.config.hgt_neg_per_pos,
            per_rel=self.config.hgt_per_rel,
            early=self.config.hgt_early_stopping,
            clip=self.config.hgt_clip
        )

        # Save embeddings
        if "entity" in embeddings:
            torch.save(embeddings["entity"], f"{self.config.output_dir}/graph_entity_embs.pt")
        if "wikidata" in embeddings:
            torch.save(embeddings["wikidata"], f"{self.config.output_dir}/graph_wikidata_embs.pt")

        print(f"  - Saved embeddings to {self.config.output_dir}/")

        return embeddings

    def generate_answer(self, question: str) -> Tuple[str, str, List]:
        """
        Generate answer using soft prompting/verbalization.

        Args:
            question: Input question

        Returns:
            (baseline_answer, enriched_answer, retrieved_nodes)
        """
        from soft_prompting import run_soft_prompting

        print(f"[4/4] Generating answer...")
        print(f"  - Verbalization: {self.config.use_verbalization}")
        print(f"  - Instruction model: {self.config.use_instruction_model}")

        baseline, enriched, retrieved = run_soft_prompting(
            text=question,
            device=self.device,
            embed_model=self.config.embed_model,
            llm_name=self.config.llm_model,
            topk=self.config.sp_topk,
            mix_entity=self.config.sp_mix_entity,
            mix_wd=self.config.sp_mix_wd,
            max_new_tokens=self.config.sp_max_new_tokens,
            use_verbalization=self.config.use_verbalization,
            use_instruction_model=self.config.use_instruction_model
        )

        return baseline, enriched, retrieved

    def answer_question(self, question: str, skip_hgt_training: bool = False) -> Dict[str, Any]:
        """
        End-to-end question answering.

        Args:
            question: Input question
            skip_hgt_training: If True, skip HGT training (use existing embeddings)

        Returns:
            Dict with results
        """
        start_time = time.time()

        # Step 1: Extract triples
        triples = self.extract_triples(question)

        if not triples:
            print("[WARN] No triples extracted, using fallback")
            baseline, enriched, retrieved = self.generate_answer(question)
            return {
                "question": question,
                "triples": [],
                "baseline_answer": baseline,
                "enriched_answer": enriched,
                "retrieved_nodes": retrieved,
                "elapsed_time": time.time() - start_time
            }

        # Step 2: Build knowledge graph
        graph_data, meta = self.build_knowledge_graph(triples, question)

        # Step 3: Train HGT (unless skipped)
        if not skip_hgt_training:
            embeddings = self.train_hgt(graph_data)
            # Nuovo step 3.5
            hgt_reasoner = HGTReasoningIntegrator(device=self.config.device)
            relevant_info = hgt_reasoner.extract_relevant_knowledge(
                hgt_embeddings=embeddings,
                question=question,
                triples=triples,
                graph_data=graph_data,
                metadata=meta
            )
        else:
            print("[INFO] Skipping HGT training (using existing embeddings)")

        

        # Step 4: Generate answer
        #baseline, enriched, retrieved = self.generate_answer(question)
        baseline, enriched, retrieved = run_soft_prompting_enhanced(
            question,
            embeddings,
            triples,
            meta.get("qid2label", {}),
            relevant_info=relevant_info,  # NUOVO: passa info da HGT
            use_verbalization=True,
            use_instruction_model=True,
            use_hgt_reasoning=True,  # NUOVO: abilita HGT reasoning
            device=self.config.device
        )
        elapsed = time.time() - start_time

        result = {
            "question": question,
            "triples": triples,
            "graph_meta": meta,
            "baseline_answer": baseline,
            "enriched_answer": enriched,
            "retrieved_nodes": retrieved,
            "elapsed_time": elapsed
        }

        # Save result
        result_file = os.path.join(self.config.output_dir, "last_result.json")
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    def clear_cache(self):
        """Clear all caches."""
        self.model_cache.clear()
        if self.result_cache:
            import shutil
            shutil.rmtree(self.config.cache_dir, ignore_errors=True)
            os.makedirs(self.config.cache_dir, exist_ok=True)
            print("[CACHE] Cleared all caches")


def create_optimized_pipeline() -> QAPipeline:
    """Create pipeline with optimized settings for multi-hop QA."""
    config = PipelineConfig(
        # Enable all enhancements
        use_ensemble=True,
        use_decomposition=True,
        use_reranking=True,
        use_verbalization=True,
        use_instruction_model=True,

        # Increase retrieval and fact limits
        sp_topk=25,
        sp_mix_entity=12,
        sp_mix_wd=13,
        sp_max_facts=30,
        sp_max_new_tokens=200,

        # More Wikidata properties for better coverage
        wikidata_props=[
            "spouse", "country of citizenship", "place of birth",
            "instance of", "occupation", "position held",
            "member of", "capital", "continent", "shares border with",
            "head of government", "head of state", "located in",
            "part of", "religion", "official language"
        ],
        wikidata_max_edges_per_qid=15,

        # Performance optimizations
        enable_caching=True,
        cache_embeddings=True,
        cache_triples=True,
    )

    return QAPipeline(config)


if __name__ == "__main__":
    # Example usage
    pipeline = create_optimized_pipeline()

    question = "Which country has Mohamed Morsi in a government post and is the location of the Giza Pyramids?"

    result = pipeline.answer_question(question)

    print("\n" + "="*80)
    print("RESULT")
    print("="*80)
    print(f"Question: {result['question']}")
    print(f"\nBaseline: {result['baseline_answer']}")
    print(f"\nEnriched: {result['enriched_answer']}")
    print(f"\nElapsed: {result['elapsed_time']:.2f}s")
