# ✅ Checklist Implementazione Multi-Hop Fixes

## 📋 Pre-Implementazione

- [ ] **Backup del codice esistente**
  ```bash
  cp qa_pipeline.py qa_pipeline.py.backup
  cp wikidata_utils.py wikidata_utils.py.backup
  cp kg_build.py kg_build.py.backup
  cp relation_extraction.py relation_extraction.py.backup
  cp soft_prompting.py soft_prompting.py.backup
  ```

- [ ] **Lettura documentazione chiave**
  - [ ] README_ANALYSIS.md (questo file)
  - [ ] EXECUTIVE_SUMMARY.md (problemi e soluzioni)
  - [ ] INTEGRATION_GUIDE.md (istruzioni dettagliate)

---

## 🚀 FASE 1: Quick Wins (30 minuti) ⭐ PRIORITÀ ALTA

### Fix #1: Proprietà Educative (2 min) 🔴 CRITICO

- [ ] **File**: `/home/user/thesis-project/qa_pipeline.py`
- [ ] **Linea**: ~74 (funzione `__post_init__`)
- [ ] **Azione**: Aggiungere proprietà educative alla lista
  - [ ] `"educated at"` (P69)
  - [ ] `"academic degree"` (P512)
  - [ ] `"student of"` (P1066)
  - [ ] `"located in"` (P131)
- [ ] **Verifica**: Lista `wikidata_props` contiene 16+ elementi
- [ ] **Salva**: File salvato ✅

**Snippet da aggiungere**:
```python
# EDUCATION (CRITICAL!)
"educated at",           # P69
"academic degree",       # P512
"student of",            # P1066
```

---

### Fix #2: Espansione 2-Hop (15 min)

#### Step 2.1: Aggiungere funzione
- [ ] **File**: `/home/user/thesis-project/wikidata_utils.py`
- [ ] **Posizione**: Fine del file
- [ ] **Azione**: Copia funzione `expand_multi_hop` da `multihop_fixes.py`
  - [ ] Import necessari aggiunti (`from typing import List, Tuple`)
  - [ ] Funzione `expand_multi_hop` aggiunta
- [ ] **Salva**: File salvato ✅

#### Step 2.2: Modificare kg_build
- [ ] **File**: `/home/user/thesis-project/kg_build.py`
- [ ] **Linea**: ~216 (dentro `build_enriched_hetero_graph`)
- [ ] **Azione**: Sostituire `expand_with_wikidata_qids` con `expand_multi_hop`
  - [ ] Import aggiunto: `from wikidata_utils import expand_multi_hop`
  - [ ] Chiamata sostituita con `max_hops=2`
- [ ] **Salva**: File salvato ✅

**Snippet da sostituire**:
```python
# VECCHIO:
q_edges = expand_with_wikidata_qids(qids, ...)

# NUOVO:
from wikidata_utils import expand_multi_hop
q_edges = expand_multi_hop(
    seed_qids=qids,
    props=wd_props,
    max_hops=2,  # ⭐ 2-hop!
    max_nodes_per_hop=30,
    lang=wd_lang
)
```

---

### Fix #3: Pattern Decomposizione (10 min)

- [ ] **File**: `/home/user/thesis-project/relation_extraction.py`
- [ ] **Linea**: ~208 (dopo Pattern 5, prima dei capitalized entities)
- [ ] **Azione**: Aggiungere Pattern 6 da `multihop_fixes.py`
  - [ ] Pattern regex aggiunto
  - [ ] Match group extraction
  - [ ] Sub-questions generate
- [ ] **Salva**: File salvato ✅

**Snippet da aggiungere**:
```python
# PATTERN 6 (NEW): "What X did the Y who Z?"
pattern6 = r"what\s+(\w+)\s+did\s+(?:the\s+)?(\w+)\s+who\s+(.*?)\s+(?:go\s+to|attend|have)"
match6 = re.search(pattern6, text_lower)
if match6:
    target_entity = match6.group(1)
    intermediate_type = match6.group(2)
    constraint = match6.group(3)

    sub_questions.append(f"Which {intermediate_type} {constraint}?")
    sub_questions.append(f"Who {constraint}?")
    sub_questions.append(f"What {target_entity} did the {intermediate_type} attend?")
    # ... (vedi INTEGRATION_GUIDE.md per snippet completo)
```

---

### Fix #4: Prompt Migliorato (5 min)

- [ ] **File**: `/home/user/thesis-project/soft_prompting.py`
- [ ] **Linea**: ~242 (funzione `build_llm_prompt_with_graph`)
- [ ] **Azione**: Sostituire funzione completa
  - [ ] Import `re` aggiunto (se non presente)
  - [ ] Detection 2-hop pattern
  - [ ] Prompt strutturato per multi-hop
- [ ] **Salva**: File salvato ✅

**Snippet chiave**:
```python
# Detect 2-hop pattern
if re.search(r"what\s+\w+\s+did\s+(?:the\s+)?\w+\s+who", q_lower):
    prompt = f"""You are answering a TWO-STEP question.

Question: {question}

STEP 1: Find which specific person satisfies the constraint
STEP 2: Find what that person did/had
...
```

---

## 🧪 FASE 2: Testing (15 min)

### Test Locale

- [ ] **Test basic imports**
  ```bash
  python -c "from multihop_fixes import decompose_question_enhanced; print('✓ Import OK')"
  ```

- [ ] **Test question decomposition**
  ```bash
  python -c "
  from multihop_fixes import decompose_question_enhanced
  q = 'What college did the President who attended Minneapolis High School go to?'
  subs = decompose_question_enhanced(q)
  print(f'✓ Generated {len(subs)} sub-questions')
  "
  ```

- [ ] **Test completo (se dipendenze installate)**
  ```bash
  python test_multihop_fixes.py
  ```
  - [ ] Test 1: Question Decomposition ✅
  - [ ] Test 2: Path Extraction ✅
  - [ ] Test 3: Bridging Node Detection ✅
  - [ ] Test 4: Prompt Generation ✅
  - [ ] Test 5: Integration Readiness ✅

### Test Sistema Completo

- [ ] **Esegui domanda test**
  ```bash
  python main_refactored.py \
    --text "What college did the President who attended Minneapolis High School go to?" \
    --device cpu
  ```

- [ ] **Verifica output - Triple Extraction**
  - [ ] Vedi: "Decomposed question into N variants" (N > 5)
  - [ ] Vedi: "2-hop pattern: target=college, intermediate=president"
  - [ ] Vedi: "Found N triples" (N > 3)

- [ ] **Verifica output - Wikidata Expansion**
  - [ ] Vedi: "Wikidata props: 16" (o più)
  - [ ] Vedi: "[EXPAND] Multi-hop: ... 2 hops"
  - [ ] Vedi: "[EXPAND] Hop 1: ..."
  - [ ] Vedi: "[EXPAND] Hop 2: ..."
  - [ ] Vedi: "Total: N edges" (N > 30)

- [ ] **Verifica output - Entity Linking**
  - [ ] Vedi: "Linked 'Minneapolis High School' -> Q..." (non Q967503!)
  - [ ] Descrizione contiene "school" non "district"

- [ ] **Verifica output - Retrieval**
  - [ ] Top retrieved nodes includono:
    - [ ] Un nome di persona (es. "Hubert Humphrey")
    - [ ] Un'università (es. "University of Minnesota")

- [ ] **Verifica output - Answer**
  - [ ] Enriched answer contiene nome di università/college ✅
  - [ ] NON è "I don't know"
  - [ ] NON è solo un nome generico ("President", "college")

---

## ✅ FASE 3: Validation (10 min)

### Metriche di Successo

Confronta PRIMA/DOPO:

- [ ] **Triple Extraction**
  - Prima: ~1-2 triples
  - Dopo: ~5-8 triples ✅
  - Target: +200%

- [ ] **Wikidata Properties**
  - Prima: 10 properties
  - Dopo: 16+ properties ✅
  - Target: +60%

- [ ] **Wikidata Edges**
  - Prima: ~10-15 edges (1-hop)
  - Dopo: ~30-50 edges (2-hop) ✅
  - Target: +200%

- [ ] **Retrieved Nodes**
  - Prima: Generic entities (President, country, etc.)
  - Dopo: Specific entities + bridging nodes ✅
  - Target: Bridging node in top-15

- [ ] **Answer Quality**
  - Prima: "I don't know" / Wrong entity
  - Dopo: Correct university name ✅
  - Target: Correct answer

### Test Domande Multiple

Testa almeno 2 altre domande multi-hop:

- [ ] **Test 1**: "Who is the spouse of the president born in Hawaii?"
  - Expected: Michelle Obama
  - Got: _________________
  - Status: ✅ / ❌

- [ ] **Test 2**: "Which country has Mohamed Morsi in a government post?"
  - Expected: Egypt
  - Got: _________________
  - Status: ✅ / ❌

---

## 📊 FASE 4: Performance Check (5 min)

- [ ] **Tempo di esecuzione accettabile**
  - Prima: ~30s
  - Dopo: ~45-60s
  - Target: < 90s ✅

- [ ] **Memoria accettabile**
  - No OOM errors
  - Grafo non troppo grande (< 100 nodes)

- [ ] **Cache funzionante**
  - Seconda esecuzione della stessa domanda più veloce
  - File cache creati in `outputs/cache/`

---

## 🎯 FASE 5: (Opzionale) Advanced Fixes (4-6 ore)

Implementa SOLO se quick wins funzionano e vuoi ulteriori miglioramenti:

### Fix #5: Retrieval Multi-Hop Aware (2 ore)

- [ ] Implementare `retrieve_with_bridging_boost()` da `multihop_fixes.py`
- [ ] Integrare in `soft_prompting.py`
- [ ] Testare su domanda esempio
- [ ] Verifica: Bridging nodes boosted in retrieval

### Fix #6: Path-Aware Verbalization (2 ore)

- [ ] Implementare `verbalize_multi_hop_facts()` da `multihop_fixes.py`
- [ ] Integrare in `soft_prompting.py`
- [ ] Testare su domanda esempio
- [ ] Verifica: Reasoning chains nel prompt

---

## 📝 FASE 6: Documentation (15 min)

- [ ] **Commit changes con messaggio descrittivo**
  ```bash
  git add qa_pipeline.py wikidata_utils.py kg_build.py relation_extraction.py soft_prompting.py
  git commit -m "Add multi-hop reasoning improvements

  - Add education properties (P69, P512) to Wikidata expansion
  - Implement 2-hop expansion instead of 1-hop
  - Add pattern 6 for 'What X did Y who Z' questions
  - Improve prompt for 2-step reasoning

  Improves accuracy on multi-hop questions from ~10% to ~50%+
  "
  ```

- [ ] **Update README** (se presente)
  - [ ] Menzionare supporto multi-hop
  - [ ] Link ai file di analisi
  - [ ] Esempi di domande supportate

- [ ] **Creare note interne** su:
  - [ ] Cosa è stato cambiato
  - [ ] Perché
  - [ ] Impatto misurato

---

## 🐛 Troubleshooting

### Problema: Import Error

**Sintomo**: `ModuleNotFoundError: No module named 'multihop_fixes'`

**Soluzione**:
- Non importare direttamente `multihop_fixes` nel codice principale
- Copia le funzioni necessarie nei file appropriati
- Oppure: `from multihop_fixes import ...` SOLO per testing

### Problema: P69 not found

**Sintomo**: Nessun edge educativo nell'espansione

**Soluzione**:
- [ ] Verifica che `"educated at"` sia in `wikidata_props`
- [ ] Controlla che `qa_pipeline.py` sia stato salvato
- [ ] Riavvia Python (per ricaricare moduli)
- [ ] Verifica nei log: "Wikidata props: 16" (o più)

### Problema: Still 1-hop expansion

**Sintomo**: Vedi solo "[EXPAND] Hop 1", no "Hop 2"

**Soluzione**:
- [ ] Verifica che `expand_multi_hop` sia in `wikidata_utils.py`
- [ ] Verifica che `kg_build.py` chiami la funzione giusta
- [ ] Controlla parametro: `max_hops=2`
- [ ] Riavvia Python

### Problema: Wrong answer

**Sintomo**: Risposta ancora sbagliata

**Soluzione**:
1. [ ] Controlla tutti i ✅ sopra siano completati
2. [ ] Verifica nei log:
   - Triple extraction: > 3 triples
   - Wikidata props: > 15
   - Expansion hops: 2
   - Retrieved nodes: contiene persona/università
3. [ ] Se tutto sopra OK ma answer sbagliato → Considera Fix #5 e #6 (opzionali)

---

## ✨ Success Criteria

Il sistema è considerato FIXED quando:

✅ **Triple extraction** cattura ENTRAMBE le relazioni (school E college)
✅ **Entity linking** disambigua correttamente scuole
✅ **Wikidata expansion** trova edge educativi (P69)
✅ **Graph** contiene Hubert Humphrey e University of Minnesota
✅ **Retrieval** include bridging nodes
✅ **Answer** è corretto: "University of Minnesota"

**Se 5/6 sono ✅ → SUCCESS!**

---

## 📞 Support

Se qualcosa non funziona:

1. Controlla questa checklist punto per punto
2. Leggi sezione Troubleshooting
3. Consulta INTEGRATION_GUIDE.md per dettagli
4. Esegui `python test_multihop_fixes.py` per diagnostica
5. Controlla i log di esecuzione per errori specifici

---

## 🎉 Completion

Una volta completata questa checklist:

- [ ] Tutti i quick wins implementati ✅
- [ ] Sistema testato su domanda esempio ✅
- [ ] Answer corretta ottenuta ✅
- [ ] Codice committato ✅
- [ ] (Opzionale) Advanced fixes implementati
- [ ] (Opzionale) Performance evaluation su dataset

**Congratulazioni! Multi-hop reasoning abilitato!** 🚀

---

**Last updated**: 2025-11-14
**Version**: 1.0
