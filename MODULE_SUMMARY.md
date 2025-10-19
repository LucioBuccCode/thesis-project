# 📦 Moduli del Sistema - Riferimento Rapido

## 🎯 Moduli Core (Usati nella Pipeline)

| File | Funzione | Input | Output |
|------|----------|-------|--------|
| **main.py** | Entry point, orchestrazione pipeline | CLI args + question | Risposta finale |
| **relation_extraction.py** | Estrazione triple da testo | Question text | List[{head, relation, tail}] |
| **kg_build.py** | Costruzione grafo eterogeneo | Triples list | HeteroData graph |
| **hgt_train_utils.py** | Training HGT su grafo | HeteroData | Learned embeddings |
| **soft_prompting.py** | LLM generation con grafo | Question + embeddings | Answer text |
| **wikidata_utils.py** | API Wikidata utilities | Entity names / QIDs | QID info, labels, edges |

---

## 🔬 Moduli Avanzati (Opzionali)

| File | Funzione | Quando Usarlo |
|------|----------|---------------|
| **graph_reasoning.py** | Path finding, subgraph extraction | Domande multihop complesse |
| **train_projector.py** | Training contrastive del projector | Se usi soft prompts invece di verbalization |

---

## 📄 Documentazione

| File | Contenuto |
|------|-----------|
| **README.md** | Documentazione completa del sistema |
| **IMPROVEMENTS.md** | Lista miglioramenti implementati + benchmark |
| **MODULE_SUMMARY.md** | Questo file (quick reference) |

---

## 🔗 Dipendenze tra Moduli

```
main.py
  ├── relation_extraction.py
  │     └── (transformers, torch)
  ├── kg_build.py
  │     ├── wikidata_utils.py
  │     │     └── (requests)
  │     └── (sentence_transformers, torch_geometric)
  ├── hgt_train_utils.py
  │     └── (torch_geometric, torch)
  └── soft_prompting.py
        ├── graph_reasoning.py (optional)
        └── (transformers, sentence_transformers)
```

---

## 🎬 Flusso Esecuzione Tipico

```python
# 1. Extract triples (relation_extraction.py)
triples = extract_triples(
    "Who is spouse of president born in Hawaii?",
    use_ensemble=True,        # Flan-T5 + REBEL
    use_decomposition=True    # Split complex question
)
# Output: 8-15 triples

# 2. Build graph (kg_build.py + wikidata_utils.py)
data, meta = build_enriched_hetero_graph(
    triples,
    question_context="Who is spouse...",
    use_reranking=True        # Cross-encoder entity linking
)
# Output: HeteroData(entity=[N,384], wikidata=[M,384])

# 3. Train HGT (hgt_train_utils.py)
embeddings = train_hgt_all_edges(
    data,
    epochs=80,
    hidden=384,
    layers=2
)
# Output: {entity: Tensor[N,384], wikidata: Tensor[M,384]}

# 4. Generate answer (soft_prompting.py)
baseline, enriched, retrieved = run_soft_prompting(
    "Who is spouse of president born in Hawaii?",
    use_verbalization=True,      # Graph → Text
    use_instruction_model=True   # Flan-T5-Large
)
# Output: "Michelle Obama"
```

---

## 🚀 Comandi Comuni

### Baseline (Sistema Originale)
```bash
python main.py --text "Your question" --device cuda
```

### Con Tutti i Miglioramenti
```bash
python main.py \
  --text "Your question" \
  --use-ensemble \
  --use-decomposition \
  --use-reranking \
  --use-verbalization \
  --use-instruction-model \
  --device cuda
```

### CPU Mode (No GPU)
```bash
python main.py \
  --text "Your question" \
  --use-verbalization \
  --use-instruction-model \
  --device cpu
```

---

## 📊 Dimensioni Tipiche

| Componente | Dimensione | Note |
|------------|------------|------|
| Entity embeddings | [N, 384] | N = numero entità nel testo |
| Wikidata embeddings | [M, 384] | M = QID trovati + expansion |
| HGT hidden | 384 | Fisso (default) |
| Flan-T5 hidden | 1024 | Interno al modello |
| GPT-2 hidden | 768 | Se usi soft prompts |

---

## 🔥 Hotspots di Performance

**Operazioni Lente:**
1. 🐌 REBEL model loading (~2-3 sec) - usa `--use-ensemble` solo se necessario
2. 🐌 Wikidata API calls (~0.1 sec per entity) - usa cache in `outputs/entity2qid.json`
3. 🐌 Cross-encoder reranking (~0.5 sec per entity) - salta con `--use-reranking` omesso
4. 🐌 Flan-T5-Large generation (~1-2 sec) - usa GPT-2 se serve velocità

**Operazioni Veloci:**
- ✅ Triple extraction con Flan-T5 (~0.5 sec)
- ✅ HGT forward pass (~0.1 sec)
- ✅ Sentence embeddings (~0.2 sec)

---

## 💾 File Salvati

### Durante Esecuzione
```
outputs/
├── triples.json              # Step 1: Triple estratte
├── text2triple_raw.txt       # Step 1: Output raw Flan-T5
├── rebel_raw.txt             # Step 1: Output raw REBEL
├── entity2qid.json          # Step 2: Cache entity linking
├── triples_expanded.json     # Step 2: Triple + Wikidata
├── graph_entity_embs.pt     # Step 3: Entity embeddings HGT
├── graph_wikidata_embs.pt   # Step 3: Wikidata embeddings HGT
└── graph_meta.json          # Step 3: Metadata grafo
```

### Se Usi train_projector.py
```
outputs/
└── trained_projector.pt      # Projector trainato (per soft prompts)
```

---

## 🆘 Quick Debug

**Problema: Poche triple estratte (1-2)**
→ Usa `--use-ensemble --use-decomposition`

**Problema: Entity linking sbagliato**
→ Usa `--use-reranking`

**Problema: Risposta LLM non usa il grafo**
→ Usa `--use-verbalization --use-instruction-model`

**Problema: CUDA OOM**
→ Usa `--device cpu` o chiudi altri processi GPU

**Problema: 403 Wikidata**
→ Già fixato in `wikidata_utils.py` (usa User-Agent header)

---

## 📚 Risorse Esterne

- **Flan-T5 model**: https://huggingface.co/google/flan-t5-large
- **REBEL model**: https://huggingface.co/Babelscape/rebel-large
- **Cross-encoder**: https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2
- **Wikidata API docs**: https://www.wikidata.org/wiki/Wikidata:Data_access
- **PyTorch Geometric**: https://pytorch-geometric.readthedocs.io/

---

## 🎓 Per Sviluppatori

### Aggiungere un Nuovo Modulo

1. Crea file `my_module.py`
2. Importa in `main.py`: `from my_module import my_function`
3. Chiama nella pipeline: `result = my_function(...)`
4. Documenta in questo file

### Testare un Componente Isolato

```python
# Test relation_extraction.py standalone
from relation_extraction import extract_triples
triples = extract_triples("Obama was born in Hawaii", use_ensemble=True)
print(triples)

# Test kg_build.py standalone
from kg_build import build_enriched_hetero_graph
data, meta = build_enriched_hetero_graph(triples, question_context="...")
print(data)
```

---

Ultimo aggiornamento: 2025-10-19
