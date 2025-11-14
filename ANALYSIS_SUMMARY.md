# Analisi del Flusso di Esecuzione - Riepilogo Esecutivo

## Comando Analizzato
```bash
python main_refactored.py --text "What college did the President who attended Minneapolis High School go to?" --device cpu
```

---

## Documenti Generati

1. **EXECUTION_FLOW_ANALYSIS.md** (15,000+ parole)
   - Call stack completo con ogni chiamata di funzione
   - Parametri passati a ogni livello
   - Feature flags attivi/inattivi
   - Dead code identificato
   - Dipendenze utilizzate/inutilizzate

2. **EXECUTION_FLOW_DIAGRAM.md** (2,500+ parole)
   - Diagramma visuale del call stack
   - Decision tree dei feature flags
   - Mappa del dead code
   - Matrice di utilizzo dipendenze
   - Ranking dei bottleneck

3. **REFACTORING_RECOMMENDATIONS.md** (3,500+ parole)
   - Raccomandazioni prioritizzate
   - Codice di esempio per refactoring
   - Roadmap implementazione
   - Testing checklist
   - Long-term architecture

---

## Tracciamento del Flusso

### Pipeline Steps (4 fasi)

```
┌─────────────────────────────────────────────────────────────────┐
│ STEP 1: TRIPLE EXTRACTION                          (~30-50s)    │
├─────────────────────────────────────────────────────────────────┤
│ main_refactored.py → qa_pipeline.py → relation_extraction.py   │
│                                                                 │
│ 1. decompose_question(text)         [use_decomposition=True]   │
│    └─> Genera 5-6 sub-questions                                │
│                                                                 │
│ 2. Per ogni sub-question:                                       │
│    ├─> Carica T5ForConditionalGeneration                       │
│    ├─> Genera triples con num_beams=4                          │
│    └─> Parse output (strict → relaxed fallback)                │
│                                                                 │
│ 3. _extract_with_rebel(text)        [use_ensemble=True]        │
│    ├─> Carica Babelscape/rebel-large                           │
│    └─> Aggiunge triples REBEL al pool                          │
│                                                                 │
│ 4. Deduplica (case-insensitive)                                │
│    └─> Output: ~10-20 triples unique                           │
│                                                                 │
│ Output files:                                                   │
│ - outputs/triples.json                                          │
│ - outputs/text2triple_raw.txt                                   │
│ - outputs/rebel_raw.txt                                         │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ STEP 2: KNOWLEDGE GRAPH CONSTRUCTION               (~20-40s)    │
├─────────────────────────────────────────────────────────────────┤
│ qa_pipeline.py → kg_build.py                                    │
│                                                                 │
│ 1. Estrae entità uniche da triples                             │
│                                                                 │
│ 2. Genera embeddings context-aware:                            │
│    └─> "Question: {q} | Entity: {e}"                           │
│    └─> SentenceTransformer all-MiniLM-L6-v2                    │
│                                                                 │
│ 3. Entity Linking (con reranking)  [use_reranking=True]        │
│    Per ogni entità:                                             │
│    ├─> API: wbsearchentities (top-5 candidates)                │
│    ├─> CrossEncoder reranking con question context             │
│    └─> Sleep 0.1s (rate limiting)                              │
│                                                                 │
│ 4. Wikidata Expansion:                                          │
│    └─> expand_with_wikidata_qids(14 properties, max_edges=15)  │
│        └─> API: wbgetclaims per ogni QID                       │
│                                                                 │
│ 5. Genera wikidata embeddings:                                 │
│    Per ogni QID:                                                │
│    ├─> API: wd_get_label_desc()                                │
│    └─> Embed: "label — description"                            │
│                                                                 │
│ 6. Costruisce HeteroData:                                       │
│    ├─> Node types: entity, wikidata                            │
│    ├─> Edge types: (entity,rel,entity), (wd,pid,wd), sameAs   │
│    └─> Features: embeddings 384-dim                            │
│                                                                 │
│ Output files:                                                   │
│ - outputs/entity2qid.json (cache)                               │
│ - outputs/triples_expanded.json                                 │
│ - outputs/graph_meta.json                                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ STEP 3: HGT TRAINING                               (~80-400s)   │
├─────────────────────────────────────────────────────────────────┤
│ qa_pipeline.py → hgt_train_utils.py                            │
│                                                                 │
│ 1. Inizializza HGTEncoder:                                      │
│    ├─> Input dim: 384 → Hidden: 384                            │
│    ├─> Layers: 2 (HGTConv)                                     │
│    ├─> Heads: 2 per layer                                      │
│    ├─> LayerNorm + ReLU + Dropout(0.3) + Residual             │
│    └─> RelScorer bilinear: h^T W_r t                           │
│                                                                 │
│ 2. Optimizer:                                                   │
│    ├─> AdamW (lr=3e-4, weight_decay=5e-4)                     │
│    └─> ReduceLROnPlateau scheduler                             │
│                                                                 │
│ 3. Training Loop (max 80 epochs):                               │
│    Per epoch:                                                   │
│    ├─> sample_batch(per_rel=128, num_neg=2, filter_negs=True) │
│    ├─> Forward: encoder + scorer                               │
│    ├─> Loss: BCE + L2 regularization (0.01)                    │
│    ├─> Backward: gradient clipping (1.0)                       │
│    ├─> Metrics: accuracy                                       │
│    └─> Early stopping (patience=8)                             │
│                                                                 │
│ 4. Output embeddings (eval mode):                               │
│    └─> {"entity": tensor, "wikidata": tensor}                  │
│                                                                 │
│ Output files:                                                   │
│ - outputs/graph_entity_embs.pt                                  │
│ - outputs/graph_wikidata_embs.pt                                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ STEP 4: ANSWER GENERATION                          (~20-40s)    │
├─────────────────────────────────────────────────────────────────┤
│ qa_pipeline.py → soft_prompting.py                             │
│                                                                 │
│ 1. Carica embeddings:                                           │
│    ├─> graph_entity_embs.pt                                    │
│    ├─> graph_wikidata_embs.pt                                  │
│    └─> triples_expanded.json                                   │
│                                                                 │
│ 2. Encode question:                                             │
│    └─> SentenceTransformer all-MiniLM-L6-v2                    │
│                                                                 │
│ 3. Retrieval (cosine similarity):                               │
│    ├─> Build bank: concat(entity_embs, wd_embs)                │
│    ├─> Top-12 entity nodes                                     │
│    ├─> Top-12 wikidata nodes                                   │
│    └─> Total: top-25 nodi rilevanti                            │
│                                                                 │
│ 4. VERBALIZATION APPROACH      [use_verbalization=True]        │
│                                                                 │
│    A. Fetch labels:                                             │
│       Per ogni QID:                                             │
│       └─> API: wd_get_label_desc()  ⚠️ BOTTLENECK             │
│                                                                 │
│    B. verbalize_with_labels():                                  │
│       ├─> Filtra triples rilevanti ai nodi retrieved           │
│       ├─> Calcola relevance score per triple                   │
│       ├─> Ordina per score, prende top-40                      │
│       ├─> Sostituisce QIDs con labels                          │
│       ├─> Rende relazioni leggibili                            │
│       └─> Output: "- fact1\n- fact2\n..."                      │
│                                                                 │
│    C. Build prompts:                                            │
│       ├─> Baseline: "Question: {q}\nAnswer:"                   │
│       └─> Enriched: Chain-of-thought + graph facts             │
│           """                                                   │
│           You are an expert...                                  │
│           Knowledge Graph Facts: {facts}                        │
│           Question: {q}                                         │
│           Think step-by-step:                                   │
│           1. What is being asked?                               │
│           2. Which facts are relevant?                          │
│           3. How do these facts connect?                        │
│           4. What is the final answer?                          │
│           Answer:                                               │
│           """                                                   │
│                                                                 │
│ 5. INSTRUCTION MODEL           [use_instruction_model=True]    │
│    ├─> Carica google/flan-t5-large                             │
│    ├─> Generate baseline (no graph)                            │
│    └─> Generate enriched (with graph)                          │
│                                                                 │
│ Output files:                                                   │
│ - outputs/last_result.json                                      │
└─────────────────────────────────────────────────────────────────┘

Total Time: ~150-530 secondi (2.5-9 minuti)
Peak Memory: ~6-8GB
```

---

## Feature Flags Attivi

| Flag                     | Valore | Impatto                                    |
|--------------------------|--------|--------------------------------------------|
| use_ensemble             | TRUE   | REBEL + Flan-T5 per triple extraction      |
| use_decomposition        | TRUE   | Genera 5-6 sub-questions                   |
| use_reranking            | TRUE   | CrossEncoder per entity linking            |
| use_verbalization        | TRUE   | Verbalization invece di soft prompts       |
| use_instruction_model    | TRUE   | Flan-T5 invece di GPT-2                    |
| enable_caching           | TRUE   | Cache per triples, entity2qid              |
| skip_hgt_training        | FALSE  | HGT training ESEGUITO (non skippato)       |

---

## Dead Code Identificato

### soft_prompting.py (~330 linee inutilizzate)

```python
# NON USATE perché use_verbalization=True:
- class SoftPromptProjector (L69-77)
- build_soft_prompt_vectors() (L79-84)
- _embeds_from_text() (L294-298)
- generate_with_soft_prompt() (L300-322)
- Soft Prompt Approach branch (L444-477)

# NON USATA perché use_instruction_model=True:
- GPT-2 branch in verbalization (L423-442)

# RARAMENTE USATA:
- verbalize_graph_facts() (L87-146)
  → verbalize_with_labels() è preferita
```

### qa_pipeline.py (~50 linee)

```python
# NON CHIAMATE da main_refactored.py:
- create_optimized_pipeline() (L416-449)
- if __name__ == "__main__" block (L452-466)
```

### Import Inutilizzati

```python
# soft_prompting.py L10:
from graph_reasoning import retrieve_relevant_subgraph, extract_subgraph_embeddings
# ↑ MAI USATE nel codice
```

**Totale Dead Code**: ~500 linee

---

## Dipendenze Utilizzate

### Sempre Caricate
```python
✓ transformers.T5Tokenizer
✓ transformers.T5ForConditionalGeneration
✓ transformers.AutoTokenizer
✓ sentence_transformers.SentenceTransformer
✓ torch + torch_geometric
```

### Caricate Condizionalmente
```python
✓ transformers.AutoModelForSeq2SeqLM         [use_ensemble OR use_instruction_model]
✓ sentence_transformers.CrossEncoder         [use_reranking=True]
✗ transformers.AutoModelForCausalLM          [use_instruction_model=False] ← MAI
```

---

## Bottleneck Performance

```
┌────────────────────────────────────────────────────────────────┐
│ PERFORMANCE BOTTLENECKS                                        │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│ 1. HGT Training                     60-70% del tempo totale    │
│    └─ 80 epochs * 1-5s = 80-400s                              │
│    └─ Soluzione: --skip-hgt flag                              │
│                                                                │
│ 2. Model Loading                    10-15% del tempo           │
│    ├─ T5: ~2s                                                 │
│    ├─ REBEL: ~3s                                              │
│    ├─ Flan-T5-large: ~5s                                      │
│    └─ Soluzione: ModelCache (già implementato ✓)              │
│                                                                │
│ 3. Wikidata API Calls               10-15% del tempo           │
│    ├─ Entity linking: N * 0.1s                                │
│    ├─ Label fetching: M * 0.1s  ⚠️ NON BATCHED                │
│    └─ Soluzione: Batch API calls                              │
│                                                                │
│ 4. Triple Extraction                10-15% del tempo           │
│    ├─ Decomposition: 5-6 variants                             │
│    ├─ Flan-T5: ~3s per variant                                │
│    └─ REBEL: ~10s                                             │
│    └─ Soluzione: --no-decomposition, --no-ensemble            │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

---

## Raccomandazioni Immediate (Top 3)

### 1. Rimuovere Dead Code (~2 ore)
```bash
# File da modificare:
- soft_prompting.py: rimuovere L69-84, L294-322, L444-477
- qa_pipeline.py: rimuovere L416-466
- Rimuovere import graph_reasoning

# Impatto:
- Codice: -500 linee
- Manutenibilità: ++
- Confusione: --
```

### 2. Batch Wikidata API Calls (~4 ore)
```python
# PRIMA (soft_prompting.py L384-390):
for qid in qids:  # 100 QIDs
    label, _ = wd_get_label_desc(qid, "en")  # 100 API calls
    # Total: ~10 secondi

# DOPO:
from wikidata_utils import wd_batch_get_labels
qid_to_label = wd_batch_get_labels(qids, "en")  # 2 API calls
# Total: ~1 secondo

# Impatto:
- Tempo: -90% su label fetching
- API stress: -98%
```

### 3. Fast Mode Preset (~1 ora)
```python
# main_refactored.py: aggiungere
parser.add_argument("--fast", action="store_true")

if args.fast:
    args.no_ensemble = True
    args.no_decomposition = True
    args.skip_hgt = True
    args.topk = 10

# Usage:
python main_refactored.py --text "..." --fast

# Impatto:
- Tempo: 10min → 2min
- UX: flag singolo invece di 5+
```

---

## Quick Wins vs Long-term

### Quick Wins (1 settimana)
```
Priority 1: Remove dead code         [2h]  → -500 linee
Priority 2: Batch Wikidata API        [4h]  → -90% API time
Priority 3: Fast mode preset          [1h]  → 80% time reduction
Priority 4: Cache graph embeddings    [6h]  → Skip HGT re-runs

Total effort: ~13 ore
Total impact: Codice più pulito + 5-10x speedup in dev mode
```

### Long-term (1 mese)
```
- Model quantization (int8)           → -50% memory
- Parallel triple extraction          → -40% extraction time
- Config file support (YAML)          → Better UX
- Architecture refactoring            → Modularity
- Async Wikidata calls                → -95% API time
```

---

## Metriche di Successo

### Pre-Ottimizzazione
```
Codebase:
- Dead code: ~500 linee
- Total lines: ~3000

Performance (CPU):
- Total time: 150-530s (2.5-9 min)
- HGT training: 80-400s
- Wikidata API: 15-30s
- Triple extraction: 20-40s

Memory:
- Peak: ~6-8GB
```

### Target Post-Ottimizzazione
```
Codebase:
- Dead code: 0 linee
- Total lines: ~2500 (-17%)

Performance (CPU):
- Total time (fast): 60-120s (1-2 min)  [-80%]
- Total time (full): 100-200s (2-3 min) [-60%]
- Wikidata API: 2-5s                     [-90%]

Memory:
- Peak: ~3-4GB                           [-50%]
```

---

## Next Steps

1. **Leggi i 3 documenti dettagliati**:
   - EXECUTION_FLOW_ANALYSIS.md (tracciamento completo)
   - EXECUTION_FLOW_DIAGRAM.md (diagrammi visuali)
   - REFACTORING_RECOMMENDATIONS.md (codice di esempio)

2. **Inizia con Quick Wins**:
   - Week 1: Remove dead code
   - Week 2: Batch Wikidata + Fast mode
   - Week 3: Cache embeddings

3. **Testa dopo ogni modifica**:
   ```bash
   # Baseline test
   python main_refactored.py --text "Which country has Mohamed Morsi in a government post?" --device cpu

   # Fast mode test
   python main_refactored.py --text "..." --fast

   # Cache test (run 2x)
   python main_refactored.py --text "..." --device cpu
   ```

4. **Misura miglioramenti**:
   - Tempo esecuzione
   - Memoria utilizzata
   - Lines of code
   - Cache hit rate

---

## Conclusione

L'analisi ha rivelato un codice ben strutturato ma con:
- **Dead code significativo** (~500 linee) da soft prompt approach obsoleto
- **Bottleneck identificabili** (HGT training 60-70%, Wikidata API 10-15%)
- **Quick wins disponibili** (batch API, fast mode, cache)
- **Architettura solida** con spazio per ottimizzazioni mirate

**Priorità**: Rimuovere dead code → Ottimizzare API calls → Migliorare UX

Con le ottimizzazioni proposte, il tempo di esecuzione può ridursi da **9 minuti a 2 minuti** in fast mode e da **9 minuti a 3 minuti** in full mode, mantenendo la qualità dei risultati.
