# Analisi Completa del Flusso di Esecuzione

## Comando Analizzato
```bash
python main_refactored.py --text "What college did the President who attended Minneapolis High School go to?" --device cpu
```

---

## CALL STACK COMPLETO

### 1. main_refactored.py

#### Parametri Passati
- `--text`: "What college did the President who attended Minneapolis High School go to?"
- `--device`: "cpu"

#### Parametri Default Attivi
```python
triple_model = "pat-jj/text2triple-flan-t5"
embed_model = "sentence-transformers/all-MiniLM-L6-v2"
llm = "google/flan-t5-large"
no_ensemble = False          → use_ensemble = True
no_decomposition = False     → use_decomposition = True
no_reranking = False         → use_reranking = True
no_verbalization = False     → use_verbalization = True
no_instruction_model = False → use_instruction_model = True
skip_hgt = False             → HGT training ESEGUITO
hgt_epochs = 80
hgt_hidden = 384
topk = 25
max_facts = 30
max_tokens = 200
no_cache = False             → enable_caching = True
clear_cache = False
quiet = False
```

#### Configurazione Costruita (righe 110-147)
```python
PipelineConfig(
    output_dir = "outputs"
    cache_dir = "outputs/cache"
    device = "cpu"
    triple_extraction_model = "pat-jj/text2triple-flan-t5"
    embed_model = "sentence-transformers/all-MiniLM-L6-v2"
    llm_model = "google/flan-t5-large"
    use_ensemble = True
    use_decomposition = True
    use_reranking = True
    use_verbalization = True
    use_instruction_model = True
    wikidata_props = [
        "spouse", "country of citizenship", "place of birth",
        "instance of", "occupation", "position held",
        "member of", "capital", "continent", "shares border with",
        "head of government", "head of state", "located in", "part of"
    ]
    wikidata_max_edges_per_qid = 15
    hgt_epochs = 80
    hgt_hidden = 384
    sp_topk = 25
    sp_mix_entity = 12
    sp_mix_wd = 12
    sp_max_facts = 30
    sp_max_new_tokens = 200
    enable_caching = True
)
```

#### Chiamate di Funzione
- **Riga 163**: `pipeline = QAPipeline(config)` → inizializza pipeline
- **Riga 172**: `pipeline.answer_question(text, skip_hgt_training=False)` → entry point principale

---

### 2. qa_pipeline.py

#### QAPipeline.__init__() (righe 162-183)
**Eseguito**: Sì
**Parametri**: config
**Azioni**:
- Imposta `self.device = "cpu"` (poiché config.device="cpu")
- Inizializza `ModelCache()` per caching modelli
- Inizializza `ResultCache("outputs/cache")` per caching risultati
- Lazy loading: `_triple_extractor`, `_kg_builder`, `_hgt_trainer`, `_generator` = None

#### answer_question() (righe 347-404)
**Eseguito**: Sì
**Parametri**:
- question = "What college did the President who attended Minneapolis High School go to?"
- skip_hgt_training = False

**Flusso**:
1. **Riga 358**: `start_time = time.time()`
2. **Riga 361**: Chiama `extract_triples(question)` → STEP 1
3. **Riga 376**: Chiama `build_knowledge_graph(triples, question)` → STEP 2
4. **Riga 380**: Chiama `train_hgt(graph_data)` → STEP 3
5. **Riga 385**: Chiama `generate_answer(question)` → STEP 4
6. **Riga 387**: Calcola elapsed time
7. **Riga 389-397**: Costruisce result dict
8. **Riga 400-402**: Salva a "outputs/last_result.json"
9. **Riga 404**: Ritorna result

---

### STEP 1: Triple Extraction

#### qa_pipeline.extract_triples() (righe 185-235)
**Eseguito**: Sì
**Parametri**: question
**Azioni**:
- **Riga 196-203**: Controlla cache (se presente, ritorna cached result)
- **Riga 206**: Importa `from relation_extraction import extract_triples`
- **Riga 212-218**: Chiama:
  ```python
  extract_triples(
      question,
      model_name="pat-jj/text2triple-flan-t5",
      device="cpu",
      use_ensemble=True,
      use_decomposition=True
  )
  ```
- **Riga 220**: Stampa count
- **Riga 223-225**: Salva a "outputs/triples.json"
- **Riga 228-233**: Salva in cache
- **Riga 235**: Ritorna triples

---

### 3. relation_extraction.py

#### extract_triples() (righe 265-375)
**Eseguito**: Sì
**Parametri**:
```python
text = "What college did the President who attended Minneapolis High School go to?"
model_name = "pat-jj/text2triple-flan-t5"
device = "cpu"
use_ensemble = True
use_decomposition = True
```

**Flusso**:

##### 3.1 Inizializzazione (righe 285-289)
- `dev = -1` (CPU)
- `device_str = "cpu"`
- `all_triples = []`

##### 3.2 Question Decomposition (righe 291-296)
**Eseguito**: Sì (perché use_decomposition=True)
- **Riga 294**: Chiama `decompose_question(text)`

#### decompose_question() (righe 112-228)
**Eseguito**: Sì
**Logica**:
- **Riga 117**: Inizia con `sub_questions = [text]` (include sempre domanda originale)
- **Righe 120-207**: Testa 5 pattern regex per estrarre sub-questions:
  - Pattern 1: "Who is the X of the Y that Z?" → **NO MATCH**
  - Pattern 2: "When did the X that Y do Z?" → **NO MATCH**
  - Pattern 3: "Which X has Y and is Z?" → **NO MATCH**
  - Pattern 4: "The X that contains Y had what Z?" → **NO MATCH**
  - Pattern 5: "Which X whose Y is Z borders W?" → **NO MATCH**
- **Righe 209-216**: Pattern 6 - Estrae entità capitalizzate:
  - Trova: "President", "Minneapolis High School"
  - Aggiunge:
    - "What is President?"
    - "President"
    - "What is Minneapolis High School?"
    - "Minneapolis High School"
- **Righe 219-225**: Deduplica
- **Riga 227**: Stampa `[INFO] Decomposed question into N variants`
- **Ritorna**: Lista di sub-questions (circa 5-6 varianti)

##### 3.3 Extract from Primary Model (righe 298-347)
**Eseguito**: Sì
**Per ogni sub-question**:
- **Riga 300**: Carica `T5Tokenizer.from_pretrained("pat-jj/text2triple-flan-t5")`
- **Riga 302-310**: Carica `T5ForConditionalGeneration.from_pretrained(...)`
  - Device map: None (CPU)
  - Dtype: torch.float32 (CPU)
- **Riga 312-320**: Tokenizza input:
  ```python
  inputs = tokenizer(txt, max_length=512, padding="max_length",
                     truncation=True, return_tensors="pt")
  ```
- **Riga 322-331**: Genera output:
  ```python
  model.generate(
      input_ids=input_ids,
      attention_mask=attention_mask,
      max_length=512,
      num_beams=4,
      early_stopping=True,
      length_penalty=0.6,
      use_cache=True
  )
  ```
- **Riga 332**: Decodifica output
- **Riga 335**: Parse con `_parse_text2triple(out_text)` (parser stretto)
- **Riga 338-340**: Se 0 triples, fallback a `_parse_text2triple_relaxed(out_text)`
- **Riga 342**: Estende `all_triples`
- **Riga 344-347**: Cleanup:
  ```python
  del model, tokenizer
  if torch.cuda.is_available():
      torch.cuda.empty_cache()
  ```

##### 3.4 REBEL Ensemble (righe 349-354)
**Eseguito**: Sì (perché use_ensemble=True)
- **Riga 352**: Chiama `_extract_with_rebel(text, device="cpu")`

#### _extract_with_rebel() (righe 230-263)
**Eseguito**: Sì
**Azioni**:
- **Riga 235**: `tokenizer = AutoTokenizer.from_pretrained("Babelscape/rebel-large")`
- **Riga 236**: `model = AutoModelForSeq2SeqLM.from_pretrained("Babelscape/rebel-large")`
- **Riga 238-239**: NO GPU move (device="cpu")
- **Riga 242-252**: Tokenizza e genera:
  ```python
  inputs = tokenizer(text, return_tensors="pt", max_length=512, truncation=True)
  outputs = model.generate(**inputs, max_length=512, num_beams=3, num_return_sequences=1)
  ```
- **Riga 254**: Decodifica (include special tokens)
- **Riga 256-258**: Salva a "outputs/rebel_raw.txt"
- **Riga 260**: Parse con `_parse_rebel_output(decoded)`
- **Ritorna**: Lista di triples REBEL

##### 3.5 Deduplica (righe 356-365)
**Eseguito**: Sì
- Combina Flan-T5 triples + REBEL triples
- Deduplica case-insensitive
- Preserva case originale

##### 3.6 Salvataggio (righe 368-372)
- **Salva**: "outputs/text2triple_raw.txt"
- **Riga 374**: Stampa `[INFO] Final: N unique triples`
- **Riga 375**: Ritorna `unique_triples`

---

### STEP 2: Knowledge Graph Construction

#### qa_pipeline.build_knowledge_graph() (righe 237-274)
**Eseguito**: Sì
**Parametri**: triples, question

**Azioni**:
- **Riga 248**: Importa `from kg_build import build_enriched_hetero_graph`
- **Riga 254-264**: Chiama:
  ```python
  build_enriched_hetero_graph(
      triples,
      embed_model="sentence-transformers/all-MiniLM-L6-v2",
      device="cpu",
      wd_props=[...14 properties...],
      wd_lang="en",
      wd_max_edges_per_qid=15,
      wd_preferred_only=False,
      question_context=question,
      use_reranking=True
  )
  ```
- **Riga 266-267**: Stampa statistiche
- **Riga 270-272**: Salva "outputs/graph_meta.json"
- **Riga 274**: Ritorna (data, meta)

---

### 4. kg_build.py

#### build_enriched_hetero_graph() (righe 156-335)
**Eseguito**: Sì

##### 4.1 Entity Extraction & Embedding (righe 182-203)
**Eseguito**: Sì
- **Riga 182**: Estrae entità uniche da triples
- **Riga 187**: Crea mapping `ent2i = {entity: index}`
- **Riga 190-194**: Costruisce entity texts con contesto:
  ```python
  entity_texts = [f"Question: {question_context} | Entity: {e}" for e in entities]
  ```
- **Riga 196**: Chiama `_embed_texts(entity_texts, embed_model, device="cpu")`

#### _embed_texts() (righe 12-16)
**Eseguito**: Sì (multiple volte)
**Azioni**:
- Carica `SentenceTransformer(model, device=device)`
- Genera embeddings con `st.encode(texts, convert_to_tensor=True, device=device)`
- Ritorna tensor embeddings

**Torna a build_enriched_hetero_graph()**:
- **Riga 202-203**: Crea HeteroData e assegna `data["entity"].x = entity_embs`

##### 4.2 Entity Linking to QIDs (righe 206-212)
**Eseguito**: Sì
- **Riga 206-212**: Chiama:
  ```python
  link_entities_to_qids(
      entities,
      cache_path="outputs/entity2qid.json",
      lang="en",
      question_context=question,
      use_reranking=True
  )
  ```

#### link_entities_to_qids() (righe 19-84)
**Eseguito**: Sì
**Azioni**:
- **Riga 36-40**: Carica cache da "outputs/entity2qid.json" (se esiste)
- **Riga 42-51**: Carica CrossEncoder per reranking:
  ```python
  if use_reranking:
      from sentence_transformers import CrossEncoder
      cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
  ```
- **Riga 53-80**: Per ogni entità:
  - **Riga 60**: Chiama `_get_wikidata_candidates(e, lang="en", limit=5)`
    - Esegue API call a Wikidata per ottenere top-5 candidati
  - **Riga 68-74**: Se use_reranking=True e question_context presente:
    - Chiama `_rerank_candidates(entity_mention, candidates, context, cross_encoder)`
      - Usa cross-encoder per scoring
      - Ritorna best candidate
  - Altrimenti: usa primo candidato
  - **Sleep**: 0.1s tra chiamate
- **Riga 82-83**: Salva cache aggiornata
- **Ritorna**: `e2q` mapping {entity_name: {qid, label, desc}}

##### 4.3 Wikidata Expansion (righe 215-219)
**Eseguito**: Sì
- **Riga 215**: Estrae lista di QIDs da e2q
- **Riga 216-219**: Chiama:
  ```python
  expand_with_wikidata_qids(
      qids,
      prop_keys=wd_props,  # 14 proprietà
      prop_lang="en",
      max_edges_per_qid=15,
      preferred_only=False
  )
  ```
  - Implementata in wikidata_utils.py
  - Espande grafo con relazioni Wikidata
  - Ritorna lista di triple (head_qid, property_id, tail_qid)

##### 4.4 Wikidata Node Embeddings (righe 222-246)
**Eseguito**: Sì
- **Riga 222**: Lista completa QIDs (seed + expansion)
- **Riga 226**: Crea mapping `qid2i = {qid: index}`
- **Riga 227-231**: Per ogni QID:
  - Chiama `wd_get_label_desc(qid, lang="en")` (API Wikidata)
  - Concatena: `label + " — " + description`
- **Riga 232**: Chiama `_embed_texts(wd_texts, embed_model, device="cpu")`
- **Riga 236**: Assegna `data["wikidata"].x = wd_embs`

##### 4.5 Edge Construction (righe 255-283)
**Eseguito**: Sì

**Entity-Entity Edges** (righe 255-261):
```python
for t in triples:
    h, r, o = ent2i[t["head"]], norm_rel(t["relation"]), ent2i[t["tail"]]
    key = ("entity", r, "entity")
    data[key].edge_index = torch.cat([...], dim=1)
```

**Wikidata-Wikidata Edges** (righe 264-272):
```python
for (hq, pid, tq) in q_edges:
    h, t = qid2i[hq], qid2i[tq]
    key = ("wikidata", pid, "wikidata")
    data[key].edge_index = torch.cat([...], dim=1)
```

**Bridge Edges (sameAs)** (righe 275-283):
```python
data[("entity", "sameAs", "wikidata")].edge_index = edge_same
data[("wikidata", "sameAs", "entity")].edge_index = edge_same.flip(0)
```

##### 4.6 Metadata & Salvataggio (righe 292-335)
- **Riga 292-297**: Crea metadata dict
- **Riga 298-333**: Costruisce e salva "outputs/triples_expanded.json":
  - Triple testuali (source="text")
  - Triple Wikidata (source="wikidata")
  - Ponti (source="bridge")
- **Riga 335**: Ritorna (data, meta)

---

### STEP 3: HGT Training

#### qa_pipeline.train_hgt() (righe 276-314)
**Eseguito**: Sì
**Parametri**: graph_data

**Azioni**:
- **Riga 286**: Importa `from hgt_train_utils import train_hgt_all_edges`
- **Riga 293-304**: Chiama:
  ```python
  train_hgt_all_edges(
      graph_data,
      device="cpu",
      hidden=384,
      layers=2,
      lr=3e-4,
      epochs=80,
      neg_per_pos=2,
      per_rel=128,
      early=8,
      clip=1.0
  )
  ```
- **Riga 307-310**: Salva embeddings:
  - "outputs/graph_entity_embs.pt"
  - "outputs/graph_wikidata_embs.pt"
- **Riga 314**: Ritorna embeddings dict

---

### 5. hgt_train_utils.py

#### train_hgt_all_edges() (righe 145-236)
**Eseguito**: Sì

##### 5.1 Inizializzazione (righe 157-177)
- **Riga 157**: `dev = torch.device("cpu")`
- **Riga 158**: `metadata = data.metadata()`
- **Riga 159**: `in_dim = data.x_dict[...].shape[-1]` (dimensione embedding)
- **Riga 161**: Crea `HGTEncoder`:
  ```python
  HGTEncoder(metadata, in_dim=in_dim, hidden=384, heads=2, layers=2)
  ```
- **Riga 163-164**: Sposta dati su CPU:
  ```python
  x_dict = {k: v.detach().clone().to(dev).float() for k, v in data.x_dict.items()}
  edge_index_dict = {et: data[et].edge_index.to(dev) for et in data.edge_types}
  ```
- **Riga 167**: `pos_edges = collect_training_edges(data)` - raccoglie tutti edge types
- **Riga 168**: `rel2id = build_rel2id(pos_edges)` - mappa relazioni a IDs
- **Riga 169**: Crea `RelScorer(num_rels=len(rel2id), dim=384)`
- **Riga 172**: Crea optimizer:
  ```python
  opt = torch.optim.AdamW(parameters, lr=3e-4, weight_decay=5e-4)
  ```
- **Riga 174-177**: Crea scheduler:
  ```python
  scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
      opt, mode='min', factor=0.5, patience=5, verbose=True
  )
  ```

##### 5.2 Training Loop (righe 182-231)
**Eseguito**: Sì (fino a 80 epoch o early stopping)

**Per ogni epoch**:
1. **Riga 184**: Sample batch:
   ```python
   batch = sample_batch(
       pos_edges, rel2id, per_rel=128,
       num_neg=2, filter_negs=True, device="cpu"
   )
   ```
   - Genera positive samples (max 128 per relazione)
   - Genera 2 negative samples per positive (tail corruption)
   - Filtra negativi per evitare false negatives

2. **Riga 188**: Forward pass encoder:
   ```python
   out_x = enc(x_dict, edge_index_dict)
   ```
   - HGTEncoder con 2 layers
   - Layer normalization
   - Residual connections
   - Dropout 0.3

3. **Riga 191-196**: Ottiene embeddings da bank:
   ```python
   bank = z_ent if (z_ent is not None and heads.max() < z_ent.size(0)) else z_wd
   h = bank[heads]
   t = bank[tails]
   ```

4. **Riga 198**: Score con RelScorer:
   ```python
   score = scorer(h, rel_ids, t)  # Bilinear: h^T W_r t
   ```

5. **Riga 201**: Loss principale:
   ```python
   loss = F.binary_cross_entropy_with_logits(score, labels)
   ```

6. **Riga 204**: Regularization:
   ```python
   reg_loss = 0.01 * (h.pow(2).mean() + t.pow(2).mean())
   total_loss = loss + reg_loss
   ```

7. **Riga 207-211**: Backprop + gradient clipping:
   ```python
   opt.zero_grad(set_to_none=True)
   total_loss.backward()
   nn.utils.clip_grad_norm_(parameters, 1.0)
   opt.step()
   ```

8. **Riga 213-214**: Calcola accuracy

9. **Riga 219**: Print epoch stats

10. **Riga 222**: Scheduler step

11. **Riga 225-231**: Early stopping:
    - Se loss migliora (>1e-4): reset wait
    - Altrimenti: wait += 1
    - Se wait >= 8: stop training

##### 5.3 Final Embeddings (righe 233-236)
```python
enc.eval()
with torch.no_grad():
    out_x = enc(x_dict, edge_index_dict)
return {k: v.detach().cpu() for k, v in out_x.items()}
```

**Ritorna**: `{"entity": tensor, "wikidata": tensor}`

---

### STEP 4: Answer Generation

#### qa_pipeline.generate_answer() (righe 316-345)
**Eseguito**: Sì
**Parametri**: question

**Azioni**:
- **Riga 326**: Importa `from soft_prompting import run_soft_prompting`
- **Riga 332-343**: Chiama:
  ```python
  run_soft_prompting(
      text=question,
      device="cpu",
      embed_model="sentence-transformers/all-MiniLM-L6-v2",
      llm_name="google/flan-t5-large",
      topk=25,
      mix_entity=12,
      mix_wd=12,
      max_new_tokens=200,
      use_verbalization=True,
      use_instruction_model=True
  )
  ```
- **Riga 345**: Ritorna (baseline, enriched, retrieved)

---

### 6. soft_prompting.py

#### run_soft_prompting() (righe 326-478)
**Eseguito**: Sì

##### 6.1 Inizializzazione (righe 358-370)
- **Riga 358**: `dev = torch.device("cpu")`
- **Riga 361**: Chiama `load_graph_embeddings()`:
  - Carica "outputs/graph_entity_embs.pt"
  - Carica "outputs/graph_wikidata_embs.pt"
  - Carica "outputs/triples_expanded.json"
  - Estrae ent_names e qids
  - Ritorna: (z_ent, ent_names, z_wd, qids)
- **Riga 364-365**: Carica all_triples da JSON
- **Riga 368-370**: Encode domanda:
  ```python
  st = SentenceTransformer(embed_model, device="cpu")
  q_vec = st.encode([text], convert_to_tensor=True, device="cpu")
  ```

##### 6.2 Retrieval (righe 373-376)
- **Riga 373**: `build_retrieval_bank(z_ent, ent_names, z_wd, qids)`
  - Concatena embeddings: Z = [z_ent; z_wd]
  - Labels: ["ENTITY::name1", ..., "WIKIDATA::Q123", ...]
  - Types: ["entity", ..., "wikidata", ...]
- **Riga 374**: `cosine_topk(q_vec, bank, labels, types, topk=25, mix_entity_wd=(12,12))`
  - Calcola cosine similarity
  - Estrae top-12 entity + top-12 wikidata
  - Ordina per score decrescente
  - Ritorna top-25 complessivi
- **Riga 376**: Costruisce `retrieved_view = [(label, type, score), ...]`

##### 6.3 Verbalization Approach (righe 379-442)
**Eseguito**: Sì (perché use_verbalization=True)

###### Branch: Instruction Model (righe 405-421)
**Eseguito**: Sì (perché use_instruction_model=True)

1. **Riga 384-390**: Costruisce QID→Label mapping:
   ```python
   for qid in qids:
       from wikidata_utils import wd_get_label_desc
       label, _ = wd_get_label_desc(qid, "en")
       qid_to_label[qid] = label
   ```

2. **Riga 393-398**: Verbalize facts:
   ```python
   graph_facts = verbalize_with_labels(
       all_triples,
       qid_to_label,
       max_facts=200//5,  # 40 facts
       retrieved_nodes=retrieved_view
   )
   ```
   - Funzione `verbalize_with_labels()` (righe 149-239):
     - Estrae relevant_entities da retrieved_nodes
     - Calcola relevance score per ogni triple
     - Ordina per score decrescente
     - Prende top-40 triples
     - Sostituisce QIDs con labels
     - Rende relazioni leggibili (P123 → property label)
     - Ritorna string con facts formattati

3. **Riga 401**: Prompt baseline:
   ```python
   prompt_baseline = "Question: {text}\nAnswer:"
   ```

4. **Riga 402**: Prompt enriched:
   ```python
   prompt_enriched = build_llm_prompt_with_graph(text, graph_facts, use_cot=True)
   ```
   - Funzione `build_llm_prompt_with_graph()` (righe 242-291):
     - Costruisce prompt strutturato
     - Include istruzioni chain-of-thought
     - Include knowledge graph facts
     - Formato:
       ```
       You are an expert at answering complex questions using knowledge graphs.

       Knowledge Graph Facts:
       {graph_facts}

       Question: {question}

       Instructions:
       1. Read the question carefully...
       2. Look through the knowledge graph facts...
       3. Connect multiple facts if needed...
       4. Provide a concise, direct answer

       Think step-by-step:
       1. What is being asked?
       2. Which facts are relevant?
       3. How do these facts connect?
       4. What is the final answer?

       Answer:
       ```

5. **Riga 407**: `llm_model_name = "google/flan-t5-large"`
6. **Riga 408**: `tokenizer = AutoTokenizer.from_pretrained("google/flan-t5-large")`
7. **Riga 409**: `model = AutoModelForSeq2SeqLM.from_pretrained("google/flan-t5-large").to("cpu")`

8. **Riga 412-415**: Genera baseline:
   ```python
   inputs = tokenizer(prompt_baseline, return_tensors="pt").to("cpu")
   with torch.no_grad():
       outputs = model.generate(**inputs, max_new_tokens=200, do_sample=False)
   baseline = tokenizer.decode(outputs[0], skip_special_tokens=True)
   ```

9. **Riga 418-421**: Genera enriched:
   ```python
   inputs = tokenizer(prompt_enriched, return_tensors="pt",
                      max_length=512, truncation=True).to("cpu")
   with torch.no_grad():
       outputs = model.generate(**inputs, max_new_tokens=200, do_sample=False)
   enriched = tokenizer.decode(outputs[0], skip_special_tokens=True)
   ```

10. **Riga 478**: Ritorna `(baseline, enriched, retrieved_view)`

---

## FEATURE FLAGS

### Flags ATTIVI (usati nell'esecuzione)
```python
✓ use_ensemble = True
  → Esegue REBEL + Flan-T5 per triple extraction
  → Codice eseguito: relation_extraction.py righe 349-354

✓ use_decomposition = True
  → Decompone domanda in sub-questions
  → Codice eseguito: relation_extraction.py righe 291-296

✓ use_reranking = True
  → Usa CrossEncoder per entity linking
  → Codice eseguito: kg_build.py righe 42-74

✓ use_verbalization = True
  → Usa verbalization invece di soft prompts
  → Codice eseguito: soft_prompting.py righe 379-442
  → BLOCCA: soft prompt approach (righe 444-477)

✓ use_instruction_model = True
  → Usa Flan-T5 invece di GPT-2
  → Codice eseguito: soft_prompting.py righe 405-421
  → BLOCCA: GPT-2 branch (righe 423-442)

✓ enable_caching = True
  → Cache per triples, embeddings, entity2qid
  → Codice eseguito: qa_pipeline.py righe 196-203, 228-233
```

### Flags INATTIVI (non attivi ma potrebbero essere abilitati)
```python
✗ skip_hgt_training = False
  → HGT training VIENE eseguito (non skippato)
  → Se fosse True, skipperebbe righe 379-382 di qa_pipeline.py

✗ clear_cache = False
  → Cache NON viene pulita all'inizio
  → Se fosse True, eseguirebbe riga 168 di main_refactored.py

✗ wikidata_preferred_only = False
  → Include tutti i rank di claims (non solo preferred)
  → Se fosse True, filtrerebbe in wikidata_utils.py riga 99
```

---

## CODICE MORTO (Dead Code)

### 1. soft_prompting.py

#### SoftPromptProjector class (righe 69-77)
**NON USATA** - Solo se use_verbalization=False
```python
class SoftPromptProjector(nn.Module):
    def __init__(self, d_src: int, d_tgt: int):
        super().__init__()
        self.lin = nn.Linear(d_src, d_tgt, bias=False)
        nn.init.xavier_uniform_(self.lin.weight)
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.lin(x)
```

#### build_soft_prompt_vectors() (righe 79-84)
**NON USATA** - Solo se use_verbalization=False
```python
def build_soft_prompt_vectors(retrieved, projector: nn.Module, device: str = "cpu"):
    if len(retrieved) == 0:
        return None
    vecs = [it[3] for it in retrieved]
    V = torch.cat(vecs, dim=0).to(device)
    return projector(V).unsqueeze(0)
```

#### _embeds_from_text() (righe 294-298)
**NON USATA** - Solo se use_verbalization=False
```python
def _embeds_from_text(text: str, tokenizer, model, device="cpu"):
    input_ids = tokenizer(text, return_tensors="pt").input_ids.to(device)
    return model.get_input_embeddings()(input_ids)
```

#### generate_with_soft_prompt() (righe 300-322)
**NON USATA** - Solo se use_verbalization=False
```python
def generate_with_soft_prompt(model, tokenizer, text: str,
                              soft_embeds=None, device="cpu",
                              max_new_tokens: int = 120):
    # ... 23 righe di codice ...
```

#### Soft Prompt Approach (righe 444-477)
**NON ESEGUITO** - Entire else branch
```python
else:
    # ===== SOFT PROMPT APPROACH (Original) =====
    print("[INFO] Using soft prompt embedding approach")

    tok = AutoTokenizer.from_pretrained(llm_name)
    # ... caricamento GPT-2 ...
    # ... projector initialization ...
    # ... soft prompt generation ...
```
**Motivo**: use_verbalization=True bypassa questo branch

#### verbalize_graph_facts() (righe 87-146)
**RARAMENTE USATA** - Funzione alternativa a verbalize_with_labels
```python
def verbalize_graph_facts(
    triples: List[Dict],
    retrieved_nodes: List[Tuple[str, str, float]],
    max_facts: int = 20
) -> str:
    # ... 60 righe ...
```
**Motivo**: verbalize_with_labels() è preferita (più avanzata)

#### GPT-2 Branch in Verbalization (righe 423-442)
**NON ESEGUITO** - Solo se use_instruction_model=False
```python
else:
    # Use GPT-2 or similar causal LM
    tokenizer = AutoTokenizer.from_pretrained(llm_name)
    # ... GPT-2 loading e generation ...
```

---

### 2. qa_pipeline.py

#### create_optimized_pipeline() (righe 416-449)
**NON CHIAMATA** da main_refactored.py
```python
def create_optimized_pipeline() -> QAPipeline:
    """Create pipeline with optimized settings for multi-hop QA."""
    config = PipelineConfig(
        # ... 30 righe di configurazione ...
    )
    return QAPipeline(config)
```
**Motivo**: main_refactored.py costruisce config manualmente

#### __main__ block (righe 452-466)
**NON ESEGUITO** - Solo se run come script standalone
```python
if __name__ == "__main__":
    pipeline = create_optimized_pipeline()
    question = "Which country has Mohamed Morsi in a government post and is the location of the Giza Pyramids?"
    result = pipeline.answer_question(question)
    # ... printing ...
```

---

### 3. graph_reasoning.py

#### Import Inutilizzato in soft_prompting.py (riga 10)
```python
from graph_reasoning import retrieve_relevant_subgraph, extract_subgraph_embeddings
```
**NON USATE** - Funzioni importate ma mai chiamate nel codice

---

### 4. relation_extraction.py

**Nessun dead code significativo** - Tutti i branch sono raggiungibili con diversi flag

---

### 5. kg_build.py

**Nessun dead code significativo** - Codice ben utilizzato

---

### 6. hgt_train_utils.py

**Nessun dead code** - Tutto eseguito durante training

---

## DIPENDENZE

### Dipendenze CARICATE (Used)

#### transformers
```python
✓ T5Tokenizer                    # relation_extraction.py:5
✓ T5ForConditionalGeneration     # relation_extraction.py:5
✓ AutoTokenizer                  # relation_extraction.py:6, soft_prompting.py:8
✓ AutoModelForSeq2SeqLM          # relation_extraction.py:6, soft_prompting.py:8
✗ AutoModelForCausalLM           # soft_prompting.py:8 (solo se use_instruction_model=False)
✓ pipeline                       # relation_extraction.py:7 (import ma non usato direttamente)
```

#### sentence_transformers
```python
✓ SentenceTransformer            # kg_build.py:6, soft_prompting.py:9
✓ CrossEncoder                   # kg_build.py:46 (solo se use_reranking=True)
```

#### torch
```python
✓ torch                          # Tutti i file
✓ torch.nn                       # hgt_train_utils.py:3, soft_prompting.py:6
✓ torch.nn.functional            # hgt_train_utils.py:3, soft_prompting.py:7
```

#### torch_geometric
```python
✓ HGTConv                        # hgt_train_utils.py:4
✓ HeteroData                     # kg_build.py:5, hgt_train_utils.py:5
```

#### requests
```python
✓ requests                       # wikidata_utils.py:3, kg_build.py (indiretto)
```

#### Standard Library
```python
✓ os, json, time, re, hashlib    # Vari file
✓ typing (List, Dict, Tuple, Optional, Any)
✓ pathlib.Path                   # qa_pipeline.py:19
✓ dataclasses (dataclass, asdict) # qa_pipeline.py:17
✓ argparse                       # main_refactored.py:11
✓ sys                            # main_refactored.py:13
✓ traceback                      # main_refactored.py:206
✓ random                         # hgt_train_utils.py:121
```

---

### Dipendenze NON Utilizzate in Questo Flusso

#### AutoModelForCausalLM (GPT-2)
**Importato**: soft_prompting.py:8
**Usato**: NO (solo se use_instruction_model=False)
**Righe dead**: 424-442, 444-477

#### graph_reasoning module
**Importato**: soft_prompting.py:10
**Funzioni**: retrieve_relevant_subgraph, extract_subgraph_embeddings
**Usato**: NO - import presente ma funzioni mai chiamate

---

## FILE DI OUTPUT GENERATI

Durante l'esecuzione, vengono creati i seguenti file:

### Outputs Directory
```
outputs/
├── triples.json                # Step 1: Triple extraction result
├── text2triple_raw.txt         # Step 1: Raw extraction output
├── rebel_raw.txt               # Step 1: REBEL model output
├── entity2qid.json             # Step 2: Entity linking cache
├── triples_expanded.json       # Step 2: Expanded graph triples
├── graph_meta.json             # Step 2: Graph metadata
├── graph_entity_embs.pt        # Step 3: Entity embeddings
├── graph_wikidata_embs.pt      # Step 3: Wikidata embeddings
└── last_result.json            # Step 4: Final result
```

### Cache Directory (se caching enabled)
```
outputs/cache/
├── triples_<hash>.json         # Cached triple extraction results
└── ...
```

---

## PERFORMANCE CONSIDERATIONS

### Colli di Bottiglia Identificati

1. **Wikidata API Calls**
   - Entity linking: ~0.1s per entità (con sleep)
   - Label fetching: ~0.1s per QID
   - Wikidata expansion: multipli calls
   - **Soluzione**: Cache in entity2qid.json

2. **Model Loading**
   - T5 model: ~1-2s
   - REBEL model: ~2-3s
   - Flan-T5-large: ~3-5s
   - SentenceTransformer: ~1s
   - **Soluzione**: ModelCache (evita ricaricamenti)

3. **HGT Training**
   - 80 epochs (o early stopping)
   - Per epoch: ~1-5s su CPU
   - Totale: ~80-400s (1-7 minuti)
   - **Soluzione**: --skip-hgt flag

4. **Question Decomposition**
   - Multiple model forwards per sub-question
   - Se 5 sub-questions: 5x il tempo di inference
   - **Soluzione**: --no-decomposition flag

5. **Ensemble REBEL**
   - Carica secondo modello large
   - Double inference time
   - **Soluzione**: --no-ensemble flag

---

## OTTIMIZZAZIONI POSSIBILI

### 1. Rimuovere Dead Code
```bash
# File da pulire:
- soft_prompting.py: righe 69-84, 87-146, 294-322, 444-477
- qa_pipeline.py: righe 416-466
- graph_reasoning import in soft_prompting.py
```

### 2. Lazy Import Ottimizzati
Spostare import pesanti solo quando necessari:
```python
# Invece di:
from transformers import AutoModelForCausalLM  # Sempre importato

# Meglio:
if not use_instruction_model:
    from transformers import AutoModelForCausalLM  # Solo se necessario
```

### 3. Batch Wikidata Calls
Invece di chiamare wd_get_label_desc() per ogni QID:
```python
# Attuale: N chiamate API
for qid in qids:
    label, desc = wd_get_label_desc(qid, "en")

# Ottimizzato: 1 chiamata API
labels = wd_batch_get_labels(qids, "en")  # Wikidata supporta batch
```

### 4. Model Quantization
```python
model = T5ForConditionalGeneration.from_pretrained(
    model_name,
    torch_dtype=torch.float16,  # Half precision
    load_in_8bit=True            # 8-bit quantization
)
```

### 5. Skip Features per Fast Mode
```python
# Fast preset:
--no-ensemble --no-decomposition --skip-hgt --topk 10
# Riduce tempo da ~10 min a ~2 min
```

---

## SUMMARY EXECUTION METRICS

### Steps Timing (approssimativo su CPU)
```
STEP 1: Triple Extraction
  - Question decomposition: ~5-10s
  - Flan-T5 extraction (5 sub-questions): ~15-25s
  - REBEL ensemble: ~10-15s
  - Total: ~30-50s

STEP 2: Knowledge Graph
  - Entity linking (con cache): ~5-10s
  - Wikidata expansion: ~10-20s
  - Embedding generation: ~5-10s
  - Total: ~20-40s

STEP 3: HGT Training
  - Training 80 epochs: ~80-400s (1-7 min)
  - Total: ~80-400s

STEP 4: Answer Generation
  - Retrieval: ~1-2s
  - Label fetching: ~10-20s
  - Verbalization: ~1s
  - Flan-T5 generation (2 passes): ~10-20s
  - Total: ~20-40s

GRAND TOTAL: ~150-530s (2.5-9 minuti)
```

### Memory Footprint (approssimativo)
```
- T5 models: ~500MB-2GB each
- Flan-T5-large: ~3GB
- REBEL: ~1.5GB
- SentenceTransformer: ~100MB
- CrossEncoder: ~100MB
- HGT model: ~50-100MB
- Graph data: ~10-100MB

Peak Memory: ~6-8GB
```

---

## CONCLUSIONI

### Feature Usage
- **use_verbalization=True**: CRITICO per qualità risposta
- **use_instruction_model=True**: Flan-T5 > GPT-2 per QA
- **use_ensemble=True**: Migliora recall triple extraction
- **use_decomposition=True**: Fondamentale per multi-hop
- **use_reranking=True**: Migliora accuracy entity linking

### Codice da Rimuovere
1. Soft prompt approach completo (non competitivo con verbalization)
2. GPT-2 support (Flan-T5 è superiore)
3. graph_reasoning import inutilizzato
4. create_optimized_pipeline() (duplicato)

### Ottimizzazioni Prioritarie
1. Batch Wikidata API calls
2. Model quantization/distillation
3. Cache più aggressivo (graph embeddings)
4. Fast mode preset
