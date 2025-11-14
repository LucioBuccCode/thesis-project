# Diagramma Flusso di Esecuzione

## Call Stack Visuale

```
main_refactored.py::main()
│
├─> parser.parse_args()
├─> PipelineConfig(...)
├─> QAPipeline.__init__(config)
│   ├─> ModelCache()
│   └─> ResultCache("outputs/cache")
│
└─> pipeline.answer_question(text, skip_hgt_training=False)
    │
    ├─────────────────────────────────────────────────────────────────────
    │ STEP 1: TRIPLE EXTRACTION (~30-50s)
    ├─────────────────────────────────────────────────────────────────────
    │
    ├─> extract_triples(question)
    │   ├─> [CACHE CHECK] ResultCache.get("triples", ...)
    │   │   └─> Cache HIT? → return cached
    │   │
    │   └─> relation_extraction.extract_triples(...)
    │       │
    │       ├─> decompose_question(text)  [use_decomposition=True]
    │       │   ├─> Pattern 1: "Who is X of Y that Z?" → NO MATCH
    │       │   ├─> Pattern 2: "When did X that Y do Z?" → NO MATCH
    │       │   ├─> Pattern 3: "Which X has Y and is Z?" → NO MATCH
    │       │   ├─> Pattern 4: "The X that contains Y had what Z?" → NO MATCH
    │       │   ├─> Pattern 5: "Which X whose Y is Z borders W?" → NO MATCH
    │       │   └─> Pattern 6: Extract capitalized entities
    │       │       └─> Returns: [original, "President", "Minneapolis High School", ...]
    │       │
    │       ├─> FOR EACH sub_question:
    │       │   ├─> T5Tokenizer.from_pretrained("pat-jj/text2triple-flan-t5")
    │       │   ├─> T5ForConditionalGeneration.from_pretrained(...)
    │       │   ├─> tokenizer(sub_question, max_length=512, ...)
    │       │   ├─> model.generate(num_beams=4, max_length=512, ...)
    │       │   ├─> tokenizer.decode(outputs)
    │       │   ├─> _parse_text2triple(output)  # Strict parser
    │       │   │   └─> If 0 triples → _parse_text2triple_relaxed(output)
    │       │   └─> all_triples.extend(triples)
    │       │
    │       ├─> [ENSEMBLE] _extract_with_rebel(text)  [use_ensemble=True]
    │       │   ├─> AutoTokenizer.from_pretrained("Babelscape/rebel-large")
    │       │   ├─> AutoModelForSeq2SeqLM.from_pretrained("Babelscape/rebel-large")
    │       │   ├─> model.generate(num_beams=3, max_length=512, ...)
    │       │   ├─> _parse_rebel_output(decoded)
    │       │   └─> Returns: rebel_triples
    │       │
    │       ├─> Deduplicate all_triples (case-insensitive)
    │       ├─> SAVE: "outputs/text2triple_raw.txt"
    │       └─> Returns: unique_triples
    │
    ├─> SAVE: "outputs/triples.json"
    ├─> [CACHE] ResultCache.set("triples", ...)
    │
    ├─────────────────────────────────────────────────────────────────────
    │ STEP 2: KNOWLEDGE GRAPH CONSTRUCTION (~20-40s)
    ├─────────────────────────────────────────────────────────────────────
    │
    ├─> build_knowledge_graph(triples, question)
    │   └─> kg_build.build_enriched_hetero_graph(...)
    │       │
    │       ├─> Extract unique entities from triples
    │       ├─> Create ent2i mapping {entity: index}
    │       │
    │       ├─> Build context-aware entity texts:
    │       │   └─> [f"Question: {question} | Entity: {e}" for e in entities]
    │       │
    │       ├─> _embed_texts(entity_texts, "all-MiniLM-L6-v2", "cpu")
    │       │   ├─> SentenceTransformer.from_pretrained(...)
    │       │   └─> st.encode(texts, convert_to_tensor=True)
    │       │
    │       ├─> data["entity"].x = entity_embs
    │       │
    │       ├─> link_entities_to_qids(entities, use_reranking=True)
    │       │   ├─> LOAD CACHE: "outputs/entity2qid.json"
    │       │   ├─> CrossEncoder.from_pretrained('ms-marco-MiniLM-L-6-v2')  [use_reranking=True]
    │       │   │
    │       │   ├─> FOR EACH entity:
    │       │   │   ├─> _get_wikidata_candidates(entity, limit=5)
    │       │   │   │   └─> API: wbsearchentities → returns top-5 candidates
    │       │   │   │
    │       │   │   ├─> _rerank_candidates(entity, candidates, question, cross_encoder)
    │       │   │   │   ├─> Build pairs: [(context + entity, candidate_desc), ...]
    │       │   │   │   ├─> scores = cross_encoder.predict(pairs)
    │       │   │   │   └─> Returns: best_candidate
    │       │   │   │
    │       │   │   └─> sleep(0.1s)
    │       │   │
    │       │   └─> SAVE CACHE: "outputs/entity2qid.json"
    │       │
    │       ├─> expand_with_wikidata_qids(qids, prop_keys=[14 properties], max_edges=15)
    │       │   └─> wikidata_utils.wd_get_claims() for each QID
    │       │       └─> API: wbgetclaims → returns (qid, property, tail_qid) triples
    │       │
    │       ├─> Build wikidata embeddings:
    │       │   ├─> FOR EACH qid:
    │       │   │   └─> wd_get_label_desc(qid, "en")  # API call
    │       │   │       └─> text = label + " — " + description
    │       │   │
    │       │   └─> _embed_texts(wd_texts, "all-MiniLM-L6-v2", "cpu")
    │       │
    │       ├─> data["wikidata"].x = wd_embs
    │       │
    │       ├─> Construct edges:
    │       │   ├─> Entity-Entity edges: data[("entity", rel, "entity")].edge_index
    │       │   ├─> Wikidata-Wikidata edges: data[("wikidata", pid, "wikidata")].edge_index
    │       │   └─> Bridge edges: data[("entity", "sameAs", "wikidata")].edge_index
    │       │
    │       ├─> SAVE: "outputs/triples_expanded.json"
    │       └─> Returns: (HeteroData, metadata)
    │
    ├─> SAVE: "outputs/graph_meta.json"
    │
    ├─────────────────────────────────────────────────────────────────────
    │ STEP 3: HGT TRAINING (~80-400s, 1-7 min)
    ├─────────────────────────────────────────────────────────────────────
    │
    ├─> train_hgt(graph_data)  [if not skip_hgt_training]
    │   └─> hgt_train_utils.train_hgt_all_edges(...)
    │       │
    │       ├─> HGTEncoder(metadata, in_dim, hidden=384, layers=2, heads=2)
    │       │   ├─> Linear projection: in_dim → 384
    │       │   ├─> HGTConv layer 1 (384 → 384, 2 heads)
    │       │   │   └─> LayerNorm + ReLU + Dropout(0.3) + Residual
    │       │   └─> HGTConv layer 2 (384 → 384, 2 heads)
    │       │       └─> LayerNorm + ReLU + Dropout(0.3) + Residual
    │       │
    │       ├─> RelScorer(num_rels, dim=384)
    │       │   └─> Bilinear: score = h^T W_r t
    │       │
    │       ├─> collect_training_edges(data) → pos_edges
    │       ├─> build_rel2id(pos_edges) → rel2id mapping
    │       │
    │       ├─> Optimizer: AdamW(lr=3e-4, weight_decay=5e-4)
    │       ├─> Scheduler: ReduceLROnPlateau(patience=5, factor=0.5)
    │       │
    │       ├─> FOR epoch in 1..80:
    │       │   │
    │       │   ├─> sample_batch(pos_edges, per_rel=128, num_neg=2, filter_negs=True)
    │       │   │   ├─> Sample max 128 edges per relation type
    │       │   │   ├─> For each positive (h, r, t):
    │       │   │   │   └─> Generate 2 negative samples (h, r, t') with tail corruption
    │       │   │   └─> Filter negatives to avoid false negatives
    │       │   │
    │       │   ├─> Forward:
    │       │   │   ├─> out_x = encoder(x_dict, edge_index_dict)
    │       │   │   ├─> h = bank[heads], t = bank[tails]
    │       │   │   └─> scores = scorer(h, rel_ids, t)  # Bilinear
    │       │   │
    │       │   ├─> Loss:
    │       │   │   ├─> loss = BCE_with_logits(scores, labels)
    │       │   │   └─> reg_loss = 0.01 * (h^2 + t^2).mean()  # L2 reg
    │       │   │
    │       │   ├─> Backward:
    │       │   │   ├─> total_loss = loss + reg_loss
    │       │   │   ├─> total_loss.backward()
    │       │   │   ├─> clip_grad_norm_(params, 1.0)
    │       │   │   └─> optimizer.step()
    │       │   │
    │       │   ├─> Metrics:
    │       │   │   └─> acc = ((sigmoid(scores) > 0.5) == labels).mean()
    │       │   │
    │       │   ├─> Scheduler: scheduler.step(loss)
    │       │   │
    │       │   └─> Early Stopping:
    │       │       ├─> If loss improves (>1e-4): reset wait
    │       │       └─> Else: wait += 1; if wait >= 8: STOP
    │       │
    │       ├─> Final forward (eval mode):
    │       │   └─> out_x = encoder(x_dict, edge_index_dict)
    │       │
    │       └─> Returns: {"entity": tensor, "wikidata": tensor}
    │
    ├─> SAVE: "outputs/graph_entity_embs.pt"
    ├─> SAVE: "outputs/graph_wikidata_embs.pt"
    │
    ├─────────────────────────────────────────────────────────────────────
    │ STEP 4: ANSWER GENERATION (~20-40s)
    ├─────────────────────────────────────────────────────────────────────
    │
    └─> generate_answer(question)
        └─> soft_prompting.run_soft_prompting(...)
            │
            ├─> load_graph_embeddings()
            │   ├─> LOAD: "outputs/graph_entity_embs.pt"
            │   ├─> LOAD: "outputs/graph_wikidata_embs.pt"
            │   ├─> LOAD: "outputs/triples_expanded.json"
            │   ├─> Extract: ent_names (from text triples)
            │   ├─> Extract: qids (from wikidata/bridge triples)
            │   └─> Returns: (z_ent, ent_names, z_wd, qids)
            │
            ├─> Encode question:
            │   ├─> SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
            │   └─> q_vec = st.encode([question], convert_to_tensor=True)
            │
            ├─> build_retrieval_bank(z_ent, ent_names, z_wd, qids)
            │   ├─> Z = concat([z_ent, z_wd])  # Combined embeddings
            │   ├─> labels = ["ENTITY::...", "WIKIDATA::Q..."]
            │   └─> types = ["entity", ..., "wikidata", ...]
            │
            ├─> cosine_topk(q_vec, Z, labels, types, topk=25, mix=(12,12))
            │   ├─> similarities = cosine(q_vec, Z)
            │   ├─> top_entity = top-12 entity nodes by similarity
            │   ├─> top_wd = top-12 wikidata nodes by similarity
            │   ├─> combined = top_entity + top_wd
            │   ├─> sorted by score descending
            │   └─> Returns: top-25 overall [(label, type, score, embedding), ...]
            │
            ├─> ┌──────────────────────────────────────────────────────────┐
            │   │ VERBALIZATION APPROACH [use_verbalization=True]         │
            │   └──────────────────────────────────────────────────────────┘
            │
            ├─> Build QID→Label mapping:
            │   └─> FOR EACH qid in qids:
            │       └─> label, _ = wd_get_label_desc(qid, "en")  # API call
            │
            ├─> verbalize_with_labels(triples, qid_to_label, max_facts=40, retrieved_nodes)
            │   ├─> Extract relevant_entities from retrieved_nodes
            │   ├─> FOR EACH triple:
            │   │   ├─> Calculate relevance score:
            │   │   │   ├─> +2 if head in retrieved entities
            │   │   │   ├─> +2 if tail in retrieved entities
            │   │   │   ├─> +1 if source == "wikidata"
            │   │   │   └─> +1 if relation is important (country, president, etc.)
            │   │   └─> Add to scored_triples
            │   ├─> Sort by score descending
            │   ├─> Take top-40 triples
            │   ├─> FOR EACH triple:
            │   │   ├─> Replace QIDs with labels if available
            │   │   ├─> Make relation readable (P123 → property label)
            │   │   └─> Format: "head relation tail"
            │   └─> Returns: "- fact1\n- fact2\n..."
            │
            ├─> Build prompts:
            │   ├─> prompt_baseline = "Question: {question}\nAnswer:"
            │   │
            │   └─> prompt_enriched = build_llm_prompt_with_graph(question, facts, use_cot=True)
            │       └─> """
            │           You are an expert at answering complex questions using knowledge graphs.
            │
            │           Knowledge Graph Facts:
            │           {graph_facts}
            │
            │           Question: {question}
            │
            │           Instructions:
            │           1. Read the question carefully and identify what information is needed
            │           2. Look through the knowledge graph facts for relevant information
            │           3. Connect multiple facts if needed to answer the question
            │           4. Provide a concise, direct answer
            │
            │           Think step-by-step:
            │           1. What is being asked?
            │           2. Which facts are relevant?
            │           3. How do these facts connect?
            │           4. What is the final answer?
            │
            │           Answer:
            │           """
            │
            ├─> ┌──────────────────────────────────────────────────────────┐
            │   │ INSTRUCTION MODEL [use_instruction_model=True]          │
            │   └──────────────────────────────────────────────────────────┘
            │
            ├─> Load Flan-T5:
            │   ├─> llm_model_name = "google/flan-t5-large"
            │   ├─> tokenizer = AutoTokenizer.from_pretrained(llm_model_name)
            │   └─> model = AutoModelForSeq2SeqLM.from_pretrained(llm_model_name).to("cpu")
            │
            ├─> Generate BASELINE answer:
            │   ├─> inputs = tokenizer(prompt_baseline, return_tensors="pt").to("cpu")
            │   ├─> outputs = model.generate(**inputs, max_new_tokens=200, do_sample=False)
            │   └─> baseline = tokenizer.decode(outputs[0], skip_special_tokens=True)
            │
            ├─> Generate ENRICHED answer:
            │   ├─> inputs = tokenizer(prompt_enriched, return_tensors="pt",
            │   │                      max_length=512, truncation=True).to("cpu")
            │   ├─> outputs = model.generate(**inputs, max_new_tokens=200, do_sample=False)
            │   └─> enriched = tokenizer.decode(outputs[0], skip_special_tokens=True)
            │
            └─> Returns: (baseline, enriched, retrieved_view)

    ├─> elapsed = time.time() - start_time
    ├─> Build result dict
    ├─> SAVE: "outputs/last_result.json"
    └─> Returns: result


main_refactored.py::main()
├─> Print results (if not quiet)
└─> Returns: 0
```

---

## Feature Flag Decision Tree

```
┌─────────────────────────────────────┐
│  Triple Extraction                  │
└─────────────────────────────────────┘
            │
            ├─> use_decomposition = True?
            │   ├─ YES → decompose_question()
            │   │        ├─> Extract sub-questions (5-6 variants)
            │   │        └─> Process each variant
            │   └─ NO  → Process only original question
            │
            ├─> FOR EACH question variant:
            │   └─> Extract with Flan-T5 model
            │
            └─> use_ensemble = True?
                ├─ YES → _extract_with_rebel()
                │        └─> Add REBEL triples to pool
                └─ NO  → Skip REBEL

┌─────────────────────────────────────┐
│  Entity Linking                     │
└─────────────────────────────────────┘
            │
            └─> use_reranking = True?
                ├─ YES → Load CrossEncoder
                │        ├─> Get top-5 candidates per entity
                │        ├─> Rerank with cross-encoder + question context
                │        └─> Select best candidate
                └─ NO  → Use first candidate only

┌─────────────────────────────────────┐
│  HGT Training                       │
└─────────────────────────────────────┘
            │
            └─> skip_hgt_training = False?
                ├─ YES → Train HGT for 80 epochs (or early stop)
                │        └─> Save embeddings to .pt files
                └─ NO  → Skip training, use existing embeddings

┌─────────────────────────────────────┐
│  Answer Generation                  │
└─────────────────────────────────────┘
            │
            ├─> use_verbalization = True?
            │   ├─ YES → ┌────────────────────────────────────┐
            │   │        │ VERBALIZATION APPROACH             │
            │   │        ├────────────────────────────────────┤
            │   │        ├─> Fetch QID labels from Wikidata  │
            │   │        ├─> Convert triples to natural text │
            │   │        ├─> Score facts by relevance        │
            │   │        └─> Build structured prompt         │
            │   │        └────────────────────────────────────┘
            │   │                     │
            │   │                     ├─> use_instruction_model = True?
            │   │                     │   ├─ YES → Use Flan-T5-large
            │   │                     │   └─ NO  → Use GPT-2
            │   │                     │
            │   │                     └─> Generate with verbalized facts
            │   │
            │   └─ NO  → ┌────────────────────────────────────┐
            │            │ SOFT PROMPT APPROACH               │
            │            ├────────────────────────────────────┤
            │            ├─> Load/init SoftPromptProjector   │
            │            ├─> Project graph embeddings        │
            │            ├─> Prepend soft vectors to input   │
            │            └─> Generate with GPT-2             │
            │            └────────────────────────────────────┘
            │                     │
            │                     └─> Generate with soft embeddings
            │
            └─> Baseline vs Enriched
                ├─> Baseline: "Question: {q}\nAnswer:"
                └─> Enriched: Includes graph knowledge
```

---

## Dead Code Map

```
soft_prompting.py
├─ [DEAD] class SoftPromptProjector (L69-77)
│  └─ Reason: use_verbalization=True bypasses soft prompt approach
│
├─ [DEAD] build_soft_prompt_vectors() (L79-84)
│  └─ Reason: use_verbalization=True bypasses soft prompt approach
│
├─ [DEAD] _embeds_from_text() (L294-298)
│  └─ Reason: use_verbalization=True bypasses soft prompt approach
│
├─ [DEAD] generate_with_soft_prompt() (L300-322)
│  └─ Reason: use_verbalization=True bypasses soft prompt approach
│
├─ [RARELY USED] verbalize_graph_facts() (L87-146)
│  └─ Reason: verbalize_with_labels() is preferred (more advanced)
│
├─ [DEAD BRANCH] Soft Prompt Approach (L444-477)
│  └─ Reason: use_verbalization=True → entire else branch not executed
│
└─ [DEAD BRANCH] GPT-2 in Verbalization (L423-442)
   └─ Reason: use_instruction_model=True → Flan-T5 branch always taken

qa_pipeline.py
├─ [DEAD] create_optimized_pipeline() (L416-449)
│  └─ Reason: main_refactored.py builds config manually
│
└─ [DEAD] if __name__ == "__main__" block (L452-466)
   └─ Reason: Never run as standalone script

graph_reasoning.py
└─ [DEAD IMPORT] retrieve_relevant_subgraph, extract_subgraph_embeddings
   └─ Reason: Imported in soft_prompting.py L10 but never called
```

---

## Dependencies Usage Matrix

| Package                  | Module                      | Used | Condition                  |
|-------------------------|----------------------------|------|----------------------------|
| transformers            | T5Tokenizer                | ✓    | Always                     |
| transformers            | T5ForConditionalGeneration | ✓    | Always                     |
| transformers            | AutoTokenizer              | ✓    | Always                     |
| transformers            | AutoModelForSeq2SeqLM      | ✓    | use_ensemble OR use_instruction_model |
| transformers            | AutoModelForCausalLM       | ✗    | use_instruction_model=False |
| transformers            | pipeline                   | ✗    | Never used                 |
| sentence_transformers   | SentenceTransformer        | ✓    | Always                     |
| sentence_transformers   | CrossEncoder               | ✓    | use_reranking=True         |
| torch                   | torch.*                    | ✓    | Always                     |
| torch.nn                | nn.*                       | ✓    | Always (HGT)               |
| torch.nn.functional     | F.*                        | ✓    | Always (HGT)               |
| torch_geometric         | HGTConv                    | ✓    | !skip_hgt_training         |
| torch_geometric         | HeteroData                 | ✓    | Always                     |
| requests                | requests.Session           | ✓    | Always (Wikidata)          |

---

## Performance Bottleneck Ranking

```
┌────────────────────────────────────────────────────────────────────────┐
│ BOTTLENECK ANALYSIS                                                    │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  1. HGT Training (80-400s)          ████████████████████████ 60-70%  │
│     └─ Mitigation: --skip-hgt flag                                   │
│                                                                        │
│  2. Model Loading (15-30s)          ████████ 10-15%                   │
│     ├─ T5: ~2s                                                        │
│     ├─ REBEL: ~3s (if ensemble)                                       │
│     ├─ Flan-T5-large: ~5s                                             │
│     └─ Mitigation: ModelCache (already implemented)                   │
│                                                                        │
│  3. Wikidata API Calls (15-30s)     ███████ 10-15%                    │
│     ├─ Entity linking: N * 0.1s                                       │
│     ├─ Label fetching: M * 0.1s                                       │
│     └─ Mitigation: Cache + Batch API calls                            │
│                                                                        │
│  4. Triple Extraction (20-40s)      ██████ 10-15%                     │
│     ├─ Decomposition: 5-6 variants                                    │
│     ├─ Flan-T5: ~3-5s per variant                                     │
│     └─ REBEL: ~10s (if ensemble)                                      │
│     └─ Mitigation: --no-decomposition, --no-ensemble                  │
│                                                                        │
│  5. Answer Generation (10-20s)      ███ 5-10%                         │
│     ├─ Label fetching: ~10s                                           │
│     ├─ Flan-T5 inference: ~5s * 2                                     │
│     └─ Mitigation: Batch label fetching                               │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘

TOTAL PIPELINE: ~150-530s (2.5-9 minutes)
```

---

## Optimization Roadmap

### Quick Wins (Low effort, High impact)
```
1. Remove dead code (~500 lines)
   - soft_prompting.py: L69-84, L294-322, L444-477
   - qa_pipeline.py: L416-466
   - Impact: Cleaner codebase, faster imports

2. Batch Wikidata API calls
   - Current: N individual calls
   - Optimized: 1 batch call
   - Impact: ~50% reduction in API time

3. Fast mode preset
   - Flags: --no-ensemble --no-decomposition --skip-hgt --topk 10
   - Impact: ~80% time reduction (10min → 2min)
```

### Medium Effort (Moderate complexity)
```
4. Model quantization
   - torch_dtype=float16
   - load_in_8bit=True
   - Impact: ~50% memory reduction, ~20% faster inference

5. Cache graph embeddings
   - Hash graph structure
   - Reuse embeddings if graph unchanged
   - Impact: Skip HGT training on re-runs

6. Parallel triple extraction
   - Process sub-questions in parallel
   - Impact: ~40% reduction in extraction time
```

### Long-term (High complexity)
```
7. Distilled models
   - Flan-T5-base instead of -large
   - DistilBERT for embeddings
   - Impact: ~60% faster, ~40% less memory

8. Pre-computed Wikidata index
   - Local cache of common entities
   - Avoid API calls entirely
   - Impact: ~90% reduction in entity linking time

9. GPU optimization
   - Batch processing
   - Mixed precision training
   - Impact: ~10x faster HGT training
```
