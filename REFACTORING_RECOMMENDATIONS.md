# Raccomandazioni per Refactoring e Ottimizzazione

## Executive Summary

L'analisi del flusso di esecuzione ha rivelato:
- **Dead Code**: ~500 linee (principalmente soft prompt approach obsoleto)
- **Feature Flags**: 6 attivi, 3 inattivi ma disponibili
- **Bottleneck Principale**: HGT training (60-70% del tempo totale)
- **API Overhead**: Wikidata calls non batched (10-15% del tempo)
- **Codice Ridondante**: Dual approach (verbalization vs soft prompt) con soft prompt mai usato

---

## PRIORITY 1: Rimuovere Dead Code (Immediato)

### 1.1 Eliminare Soft Prompt Approach

**File**: `soft_prompting.py`

**Codice da rimuovere**:
```python
# Righe 69-77: class SoftPromptProjector
# Righe 79-84: build_soft_prompt_vectors()
# Righe 294-298: _embeds_from_text()
# Righe 300-322: generate_with_soft_prompt()
# Righe 444-477: Entire else branch (Soft Prompt Approach)
```

**Motivazione**:
- `use_verbalization=True` è SEMPRE attivo nei test
- Verbalization produce risultati superiori
- Soft prompt richiede projector training aggiuntivo
- Riduce complexity e maintenance burden

**Impatto**:
- ✓ -200 linee di codice
- ✓ Elimina dipendenza da trained_projector.pt
- ✓ Semplifica logica in run_soft_prompting()
- ✓ Riduce confusione per sviluppatori

**Refactoring**:
```python
# PRIMA (soft_prompting.py):
def run_soft_prompting(..., use_verbalization: bool = True, ...):
    if use_verbalization:
        # ... verbalization code ...
    else:
        # ... soft prompt code ...  ← DA RIMUOVERE

# DOPO:
def run_verbalized_prompting(...):
    """Generate answer using graph verbalization (recommended approach)."""
    # ... solo verbalization code ...
```

---

### 1.2 Eliminare GPT-2 Support

**File**: `soft_prompting.py`

**Codice da rimuovere**:
```python
# Righe 423-442: GPT-2 branch in verbalization
# Import: AutoModelForCausalLM (riga 8)
```

**Motivazione**:
- `use_instruction_model=True` è SEMPRE attivo
- Flan-T5 è superiore per QA tasks
- GPT-2 richiede decoder-only handling diverso
- Nessun use case per GPT-2 nei test

**Impatto**:
- ✓ -50 linee di codice
- ✓ Elimina import AutoModelForCausalLM
- ✓ Semplifica logica model loading
- ✓ Un solo path di generazione

**Refactoring**:
```python
# PRIMA:
if use_instruction_model:
    # Flan-T5 code
else:
    # GPT-2 code  ← DA RIMUOVERE

# DOPO:
# Solo Flan-T5 code
tokenizer = AutoTokenizer.from_pretrained(llm_model_name)
model = AutoModelForSeq2SeqLM.from_pretrained(llm_model_name).to(dev)
# ...
```

---

### 1.3 Rimuovere Funzioni Helper Inutilizzate

**File**: `soft_prompting.py`

**Funzioni da rimuovere**:
```python
# Riga 87-146: verbalize_graph_facts()
# Motivazione: verbalize_with_labels() è superiore e sempre usata
```

**File**: `qa_pipeline.py`

**Funzioni da rimuovere**:
```python
# Righe 416-449: create_optimized_pipeline()
# Righe 452-466: if __name__ == "__main__" block
# Motivazione: main_refactored.py costruisce config esplicitamente
```

**Impatto**:
- ✓ -80 linee di codice
- ✓ Elimina duplicazione logica
- ✓ Un solo entry point (main_refactored.py)

---

### 1.4 Rimuovere Import Inutilizzato

**File**: `soft_prompting.py`

```python
# Riga 10: DA RIMUOVERE
from graph_reasoning import retrieve_relevant_subgraph, extract_subgraph_embeddings

# Motivazione: Mai chiamate in soft_prompting.py
# Le funzioni esistono in graph_reasoning.py ma non sono integrate nel flusso
```

**File**: `relation_extraction.py`

```python
# Riga 7: VERIFICARE SE USATO
from transformers import pipeline

# Sembra importato ma non utilizzato direttamente
# Se non serve, rimuovere
```

---

## PRIORITY 2: Batch Wikidata API Calls (Alto Impatto)

### 2.1 Problema Attuale

**File**: `soft_prompting.py` righe 384-390

```python
# INEFFICIENTE: N chiamate API sequenziali
for qid in qids:  # Può essere 50-100 QIDs
    from wikidata_utils import wd_get_label_desc
    label, _ = wd_get_label_desc(qid, "en")  # API call singola
    if label:
        qid_to_label[qid] = label
```

**Costo**: ~0.1s * N QIDs = 5-10 secondi sprecati

---

### 2.2 Soluzione: Batch API

**File**: `wikidata_utils.py`

Aggiungere nuova funzione:

```python
def wd_batch_get_labels(qids: List[str], lang: str = "en") -> Dict[str, str]:
    """
    Batch fetch labels for multiple QIDs in single API call.

    Wikidata API supports up to 50 entities per request.
    """
    if not qids:
        return {}

    qid_to_label = {}

    # Process in chunks of 50 (Wikidata limit)
    for i in range(0, len(qids), 50):
        chunk = qids[i:i+50]

        params = {
            "action": "wbgetentities",
            "ids": "|".join(chunk),  # Batch: Q1|Q2|Q3|...
            "languages": lang,
            "props": "labels",
            "format": "json"
        }

        try:
            r = session.get(WD_API, params=params, timeout=20)
            r.raise_for_status()
            entities = r.json().get("entities", {})

            for qid, data in entities.items():
                label = data.get("labels", {}).get(lang, {}).get("value", "")
                if label:
                    qid_to_label[qid] = label
        except Exception as e:
            print(f"[WARN] Batch label fetch failed for chunk: {e}")
            # Fallback to individual calls for this chunk
            for qid in chunk:
                try:
                    label, _ = wd_get_label_desc(qid, lang)
                    if label:
                        qid_to_label[qid] = label
                except:
                    pass

        time.sleep(0.1)  # Rate limiting between batches

    return qid_to_label
```

**File**: `soft_prompting.py`

Refactoring righe 384-390:

```python
# PRIMA: N chiamate singole
for qid in qids:
    from wikidata_utils import wd_get_label_desc
    label, _ = wd_get_label_desc(qid, "en")
    if label:
        qid_to_label[qid] = label

# DOPO: 1 chiamata batch
from wikidata_utils import wd_batch_get_labels
qid_to_label = wd_batch_get_labels(qids, "en")
```

**Impatto**:
- ✓ 10s → 1s per 100 QIDs
- ✓ ~90% riduzione tempo Wikidata API
- ✓ Meno stress sul server Wikidata
- ✓ Cache-friendly (batch result cacheable)

---

## PRIORITY 3: Fast Mode Preset (Quick Win)

### 3.1 Aggiungere Preset Configuration

**File**: `main_refactored.py`

Aggiungere opzione:

```python
# Dopo riga 99 (--clear-cache)
parser.add_argument("--fast", action="store_true",
                    help="Fast mode: disable ensemble, decomposition; use smaller models")
```

Processing dopo parse_args():

```python
# Dopo riga 107
args = parser.parse_args()

# Fast mode overrides
if args.fast:
    print("[INFO] Fast mode enabled: disabling ensemble, decomposition, and reducing topk")
    args.no_ensemble = True
    args.no_decomposition = True
    args.skip_hgt = True
    args.topk = 10
    args.max_facts = 15
    # Optional: use smaller model
    if args.llm == "google/flan-t5-large":
        args.llm = "google/flan-t5-base"
```

**Usage**:
```bash
# Full pipeline: ~10 minutes
python main_refactored.py --text "question"

# Fast mode: ~2 minutes
python main_refactored.py --text "question" --fast
```

**Impatto**:
- ✓ 80% time reduction
- ✓ User-friendly single flag
- ✓ Mantiene quality accettabile per development/testing

---

## PRIORITY 4: Model Quantization (Medium Effort)

### 4.1 Int8 Quantization

**File**: `soft_prompting.py` righe 407-409

```python
# PRIMA: Full precision (FP32 o FP16)
tokenizer = AutoTokenizer.from_pretrained(llm_model_name)
model = AutoModelForSeq2SeqLM.from_pretrained(llm_model_name).to(dev)

# DOPO: 8-bit quantization
tokenizer = AutoTokenizer.from_pretrained(llm_model_name)
model = AutoModelForSeq2SeqLM.from_pretrained(
    llm_model_name,
    load_in_8bit=True,           # ✓ 4x memory reduction
    device_map="auto"             # ✓ Automatic device placement
)
```

**File**: `relation_extraction.py` righe 302-310

```python
# DOPO: Quantized loading
try:
    model = T5ForConditionalGeneration.from_pretrained(
        model_name,
        load_in_8bit=True if dev != -1 else False,  # Only on GPU
        device_map="auto" if dev != -1 else None,
        torch_dtype=torch.bfloat16 if dev != -1 else torch.float32
    )
except Exception:
    # Fallback to standard loading
    model = T5ForConditionalGeneration.from_pretrained(model_name)
    if dev != -1:
        model = model.to("cuda")
```

**Dependencies**:
```bash
pip install bitsandbytes accelerate
```

**Impatto**:
- ✓ ~4x memoria reduction
- ✓ ~20-30% faster inference (GPU)
- ✓ Minimal accuracy loss (<1%)
- ✗ Requires bitsandbytes package

---

## PRIORITY 5: Cache Graph Embeddings (Medium Effort)

### 5.1 Problema Attuale

HGT training richiede 1-7 minuti anche se il grafo non è cambiato.

---

### 5.2 Soluzione: Graph Hash + Cache

**File**: `qa_pipeline.py`

Aggiungere funzione:

```python
def _graph_hash(self, graph_data) -> str:
    """Generate deterministic hash of graph structure."""
    import hashlib

    # Serialize graph structure
    structure = {
        "node_types": sorted(graph_data.node_types),
        "edge_types": sorted([str(et) for et in graph_data.edge_types]),
        "node_counts": {nt: graph_data[nt].x.shape[0] for nt in graph_data.node_types},
        "edge_counts": {str(et): graph_data[et].edge_index.shape[1]
                       for et in graph_data.edge_types}
    }

    # Hash
    structure_str = json.dumps(structure, sort_keys=True)
    return hashlib.md5(structure_str.encode()).hexdigest()
```

Modificare `train_hgt()`:

```python
def train_hgt(self, graph_data):
    """Train HGT model on graph with caching."""
    from hgt_train_utils import train_hgt_all_edges

    # Generate graph hash
    graph_hash = self._graph_hash(graph_data)
    cache_path = os.path.join(self.config.cache_dir, f"hgt_embs_{graph_hash}.pkl")

    # Check cache
    if os.path.exists(cache_path):
        print(f"[CACHE] Loading cached HGT embeddings (hash: {graph_hash[:8]})")
        import pickle
        with open(cache_path, "rb") as f:
            embeddings = pickle.load(f)
        return embeddings

    # Train
    print(f"[3/4] Training HGT...")
    embeddings = train_hgt_all_edges(
        graph_data,
        device=self.device,
        hidden=self.config.hgt_hidden,
        # ... other params ...
    )

    # Cache embeddings
    import pickle
    with open(cache_path, "wb") as f:
        pickle.dump(embeddings, f)
    print(f"[CACHE] Saved HGT embeddings (hash: {graph_hash[:8]})")

    # Also save to outputs/ for compatibility
    if "entity" in embeddings:
        torch.save(embeddings["entity"], f"{self.config.output_dir}/graph_entity_embs.pt")
    if "wikidata" in embeddings:
        torch.save(embeddings["wikidata"], f"{self.config.output_dir}/graph_wikidata_embs.pt")

    return embeddings
```

**Impatto**:
- ✓ Skip HGT training on re-runs (same graph)
- ✓ 1-7 minutes → instant on cache hit
- ✓ Automatic invalidation on graph change
- ✓ Disk space: ~10-50MB per cached graph

---

## PRIORITY 6: Parallel Triple Extraction (Advanced)

### 6.1 Problema Attuale

Decomposition genera 5-6 sub-questions, processate sequenzialmente:
```
sub_q1 → model → parse → (3s)
sub_q2 → model → parse → (3s)
sub_q3 → model → parse → (3s)
...
Total: ~15-18s
```

---

### 6.2 Soluzione: Parallel Processing

**File**: `relation_extraction.py`

Refactoring righe 298-347:

```python
# DOPO: Parallel processing
import concurrent.futures
from typing import List
import copy

def _extract_single_text(txt: str, model_name: str, device_str: str) -> List[Dict[str, str]]:
    """Extract triples from single text (worker function)."""
    tokenizer = T5Tokenizer.from_pretrained(model_name)
    try:
        model = T5ForConditionalGeneration.from_pretrained(
            model_name,
            device_map="auto" if device_str == "cuda" else None,
            torch_dtype=torch.bfloat16 if device_str == "cuda" else torch.float32
        )
    except Exception:
        model = T5ForConditionalGeneration.from_pretrained(model_name)
        if device_str == "cuda":
            model = model.to("cuda")

    inputs = tokenizer(txt, max_length=512, padding="max_length",
                      truncation=True, return_tensors="pt")
    input_ids = inputs["input_ids"].to(model.device)
    attention_mask = inputs["attention_mask"].to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            input_ids=input_ids,
            attention_mask=attention_mask,
            max_length=512,
            num_beams=4,
            early_stopping=True,
            length_penalty=0.6,
            use_cache=True
        )
    out_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

    # Parse
    triples = _parse_text2triple(out_text)
    if len(triples) == 0:
        triples = _parse_text2triple_relaxed(out_text)

    # Cleanup
    del model, tokenizer
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return triples

# In extract_triples():
# Step 2: Extract from each text with primary model (PARALLEL)
max_workers = min(len(texts_to_process), 3)  # Max 3 parallel to avoid OOM
with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
    # Submit all tasks
    futures = [
        executor.submit(_extract_single_text, txt, model_name, device_str)
        for txt in texts_to_process
    ]

    # Collect results
    for future in concurrent.futures.as_completed(futures):
        try:
            triples = future.result()
            all_triples.extend(triples)
        except Exception as e:
            print(f"[WARN] Parallel extraction failed: {e}")
```

**Attenzione**:
- Richiede memoria sufficiente per multipli modelli (o serializzare con lock)
- CPU: ThreadPoolExecutor OK
- GPU: Può causare OOM, usare max_workers=1 o ProcessPoolExecutor

**Impatto**:
- ✓ ~40% reduction in extraction time (5 sub-q: 15s → 9s)
- ✗ Increased memory usage (~2-3x)
- ✗ Complexity increase

**Alternativa più semplice**: Cache model between sub-questions (evita reload)

---

## PRIORITY 7: Configuration File Support

### 7.1 Problema Attuale

Troppi flag da passare:
```bash
python main_refactored.py \
  --text "question" \
  --no-ensemble \
  --no-decomposition \
  --hgt-epochs 50 \
  --topk 20 \
  --max-facts 25 \
  # ... 15+ flags ...
```

---

### 7.2 Soluzione: Config File

**File**: `config.yaml` (esempio)

```yaml
# Default configuration
model:
  triple_extraction: "pat-jj/text2triple-flan-t5"
  embedding: "sentence-transformers/all-MiniLM-L6-v2"
  llm: "google/flan-t5-large"

features:
  use_ensemble: true
  use_decomposition: true
  use_reranking: true
  use_verbalization: true
  use_instruction_model: true

wikidata:
  props:
    - spouse
    - country of citizenship
    - place of birth
    - instance of
    - occupation
    - position held
    - member of
    - capital
    - continent
    - shares border with
    - head of government
    - head of state
    - located in
    - part of
  max_edges_per_qid: 15

hgt:
  epochs: 80
  hidden: 384
  layers: 2
  lr: 0.0003

retrieval:
  topk: 25
  mix_entity: 12
  mix_wd: 12
  max_facts: 30
  max_tokens: 200

performance:
  enable_caching: true
  device: "auto"

# Fast preset
presets:
  fast:
    features:
      use_ensemble: false
      use_decomposition: false
    hgt:
      skip_training: true
    retrieval:
      topk: 10
      max_facts: 15
    model:
      llm: "google/flan-t5-base"
```

**File**: `main_refactored.py`

```python
import yaml

# Add argument
parser.add_argument("--config", type=str, default=None,
                    help="Path to YAML config file")
parser.add_argument("--preset", type=str, default=None,
                    choices=["fast", "balanced", "accurate"],
                    help="Use preset configuration")

args = parser.parse_args()

# Load config
if args.config:
    with open(args.config) as f:
        config_dict = yaml.safe_load(f)
    # Merge with args (args override config)
    # ... merge logic ...
elif args.preset:
    # Load preset
    config_dict = load_preset(args.preset)
else:
    # Use defaults from argparse
    config_dict = build_config_from_args(args)

config = PipelineConfig(**config_dict)
```

**Usage**:
```bash
# Use config file
python main_refactored.py --text "question" --config myconfig.yaml

# Use preset
python main_refactored.py --text "question" --preset fast

# Override specific values
python main_refactored.py --text "question" --preset fast --hgt-epochs 100
```

**Impatto**:
- ✓ Reusable configurations
- ✓ Easier experimentation
- ✓ Version-controllable configs
- ✓ Cleaner command lines

---

## SUMMARY: Implementation Roadmap

### Week 1: Quick Wins
```
Day 1-2: Remove dead code
  - soft_prompting.py cleanup
  - qa_pipeline.py cleanup
  - Remove unused imports
  - Test suite still passes

  Impact: -500 lines, cleaner codebase
```

### Week 2: Performance
```
Day 3-4: Batch Wikidata API
  - Implement wd_batch_get_labels()
  - Refactor soft_prompting.py
  - Add unit tests

  Impact: ~90% API time reduction

Day 5: Fast mode preset
  - Add --fast flag
  - Document usage

  Impact: User-friendly quick mode
```

### Week 3: Caching
```
Day 6-7: Graph embedding cache
  - Implement graph hashing
  - Modify train_hgt()
  - Test cache invalidation

  Impact: Skip HGT on re-runs
```

### Week 4: Advanced (Optional)
```
Day 8-9: Model quantization
  - Test int8 quantization
  - Measure accuracy impact
  - Update docs

  Impact: ~4x memory, ~20% faster

Day 10: Config file support
  - YAML parsing
  - Preset definitions
  - Migration guide

  Impact: Better UX
```

---

## Testing Checklist

Prima di ogni commit:

```bash
# 1. Test funzionalità base
python main_refactored.py --text "Which country has Mohamed Morsi in a government post?" --device cpu

# 2. Test fast mode
python main_refactored.py --text "..." --fast

# 3. Test con cache
python main_refactored.py --text "..." --device cpu  # Run 2x, secondo deve essere faster

# 4. Test senza features
python main_refactored.py --text "..." --no-ensemble --no-decomposition

# 5. Verify outputs
ls -la outputs/
# Deve contenere: triples.json, graph_meta.json, *_embs.pt, last_result.json
```

---

## Metrics to Track

Prima e dopo ogni ottimizzazione:

```python
# Tempo esecuzione
- Total pipeline time
- Time per step (extraction, KG, HGT, generation)

# Memoria
- Peak memory usage
- Model loading memory

# Quality
- Number of triples extracted
- Graph size (nodes, edges)
- Answer quality (manual evaluation)

# Cache efficiency
- Cache hit rate
- Disk space used
```

---

## Long-term Architecture Recommendations

### 1. Separate Concerns
```
current: main_refactored.py (250 lines, tutto insieme)
proposed:
  - cli.py (argparse, config loading)
  - pipeline.py (orchestration)
  - models.py (model loading, caching)
  - wikidata.py (API calls, batching)
```

### 2. Dependency Injection
```python
# Instead of hardcoded model names
class TripleExtractor:
    def __init__(self, model_name: str, device: str):
        self.model = load_model(model_name, device)

    def extract(self, text: str) -> List[Triple]:
        ...

# Usage
extractor = TripleExtractor("pat-jj/text2triple-flan-t5", "cpu")
pipeline = QAPipeline(extractor=extractor, ...)
```

### 3. Async API Calls
```python
# Instead of sequential Wikidata calls
import asyncio
import aiohttp

async def batch_fetch_labels(qids: List[str]) -> Dict[str, str]:
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_label(qid, session) for qid in qids]
        results = await asyncio.gather(*tasks)
    return dict(results)
```

### 4. Plugin System
```python
# Allow custom components
class Pipeline:
    def __init__(self):
        self.extractors = []
        self.enrichers = []
        self.generators = []

    def register_extractor(self, extractor):
        self.extractors.append(extractor)

    # Usage
    pipeline = Pipeline()
    pipeline.register_extractor(FlanT5Extractor())
    pipeline.register_extractor(REBELExtractor())
    pipeline.register_enricher(WikidataEnricher())
```

### 5. Observability
```python
# Add logging and metrics
import logging
from prometheus_client import Counter, Histogram

triple_extraction_time = Histogram('triple_extraction_seconds',
                                   'Time spent in triple extraction')
api_calls = Counter('wikidata_api_calls', 'Number of Wikidata API calls')

@triple_extraction_time.time()
def extract_triples(...):
    ...
```

---

## Conclusion

**Immediate Actions** (Do Now):
1. Remove dead code (~2 hours)
2. Batch Wikidata API (~4 hours)
3. Add --fast preset (~1 hour)

**Quick Wins** (This Week):
4. Cache graph embeddings (~6 hours)
5. Model quantization (~4 hours)

**Future Work** (Next Sprint):
6. Config file support
7. Parallel extraction
8. Architecture refactoring

**Expected Improvements**:
- Code: -500 lines, cleaner structure
- Speed: 10min → 2min (fast mode), 10min → 3min (full mode with optimizations)
- Memory: ~50% reduction with quantization
- Developer Experience: Better UX with presets and config files
