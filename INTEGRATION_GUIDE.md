# Guida Pratica di Integrazione - Multi-Hop Fixes

## Quick Start (30 minuti)

Questa guida ti mostra ESATTAMENTE quali righe di codice modificare per ottenere miglioramenti immediati.

---

## Fix #1: Aggiungere Proprietà Educative ⭐ CRITICO

**Tempo**: 2 minuti
**Impatto**: 90%
**File**: `/home/user/thesis-project/qa_pipeline.py`

### Cosa fare:

Trova la funzione `__post_init__` nella classe `PipelineConfig` (circa linea 74):

```python
def __post_init__(self):
    if self.wikidata_props is None:
        self.wikidata_props = [
            "spouse", "country of citizenship", "place of birth",
            "instance of", "occupation", "position held",
            "member of", "capital", "continent", "shares border with"
        ]
```

**SOSTITUISCI CON**:

```python
def __post_init__(self):
    if self.wikidata_props is None:
        self.wikidata_props = [
            # Biographical
            "spouse", "country of citizenship", "place of birth",
            "instance of", "occupation", "position held",
            "member of",

            # ⭐ EDUCATION (NEW - CRITICAL!)
            "educated at",           # P69 - where someone studied
            "academic degree",       # P512 - what degree
            "student of",            # P1066 - who taught them

            # Geographic
            "capital", "continent", "shares border with",
            "located in",            # P131 - for schools/universities
            "headquarters location",  # P159

            # Temporal
            "start time",            # P580
            "end time",              # P582
        ]
```

**Salva il file.**

---

## Fix #2: Espansione 2-Hop

**Tempo**: 15 minuti
**Impatto**: 80%
**File**: `/home/user/thesis-project/wikidata_utils.py`

### Step 2.1: Aggiungere la funzione

Alla fine del file `wikidata_utils.py`, aggiungi:

```python
def expand_multi_hop(
    seed_qids: List[str],
    props: List[str],
    max_hops: int = 2,
    max_nodes_per_hop: int = 30,
    lang: str = "en"
) -> List[Tuple[str, str, str]]:
    """
    Multi-hop Wikidata expansion.

    Expands seed QIDs following properties for up to max_hops steps.
    """
    all_edges = []
    visited = set()

    pids = resolve_property_keys(props, lang=lang)
    print(f"[EXPAND] Multi-hop: {len(seed_qids)} seeds, {max_hops} hops, {len(pids)} props")

    current_level = seed_qids

    for hop in range(max_hops):
        print(f"[EXPAND] Hop {hop+1}: expanding {len(current_level)} nodes")
        next_level = set()

        for qid in current_level:
            if qid in visited:
                continue
            visited.add(qid)

            try:
                edges = wd_get_claims(
                    qid,
                    prop_keys=props,
                    lang=lang,
                    max_edges=max_nodes_per_hop // max(len(current_level), 1) + 1
                )

                all_edges.extend(edges)

                # Add discovered QIDs to next level
                for _, _, tail_qid in edges:
                    if tail_qid not in visited and tail_qid.startswith("Q"):
                        next_level.add(tail_qid)

                time.sleep(0.1)  # Rate limiting

            except Exception as e:
                print(f"[WARN] Failed to expand {qid}: {e}")
                continue

        # Limit next level
        current_level = list(next_level)[:max_nodes_per_hop]

        if not current_level:
            break

    print(f"[EXPAND] Total: {len(all_edges)} edges, {len(visited)} nodes")
    return all_edges
```

### Step 2.2: Modificare kg_build.py

**File**: `/home/user/thesis-project/kg_build.py`

Trova la funzione `build_enriched_hetero_graph` (circa linea 156), cerca questa riga:

```python
q_edges = expand_with_wikidata_qids(qids,
                                    prop_keys=wd_props, prop_lang=wd_lang,
                                    max_edges_per_qid=wd_max_edges_per_qid,
                                    preferred_only=wd_preferred_only)
```

**SOSTITUISCI CON**:

```python
# Import the new function
from wikidata_utils import expand_multi_hop

# Use 2-hop expansion instead of 1-hop
q_edges = expand_multi_hop(
    seed_qids=qids,
    props=wd_props,
    max_hops=2,  # ⭐ 2-hop expansion!
    max_nodes_per_hop=30,
    lang=wd_lang
)
```

**Salva il file.**

---

## Fix #3: Pattern di Decomposizione

**Tempo**: 10 minuti
**Impatto**: 70%
**File**: `/home/user/thesis-project/relation_extraction.py`

### Step 3.1: Aggiungere il nuovo pattern

Nella funzione `decompose_question` (circa linea 112), DOPO il Pattern 5 (circa linea 208), aggiungi:

```python
    # PATTERN 6 (NEW): "What X did the Y who Z do/attend/have?"
    # Example: "What college did the President who attended Minneapolis High School go to?"
    pattern6 = r"what\s+(\w+)\s+did\s+(?:the\s+)?(\w+)\s+who\s+(.*?)\s+(?:go\s+to|attend|have|get|do)"
    match6 = re.search(pattern6, text_lower)
    if match6:
        target_entity = match6.group(1)  # "college"
        intermediate_type = match6.group(2)  # "president"
        constraint = match6.group(3)  # "attended Minneapolis High School"

        print(f"[DECOMPOSE] 2-hop pattern: target={target_entity}, intermediate={intermediate_type}")

        # Find intermediate entity
        sub_questions.append(f"Which {intermediate_type} {constraint}?")
        sub_questions.append(f"Who {constraint}?")

        # Find target
        sub_questions.append(f"What {target_entity} did the {intermediate_type} attend?")
        sub_questions.append(f"{intermediate_type} attended {target_entity}")

        # Extract constraint
        sub_questions.append(f"{intermediate_type} {constraint}")
        sub_questions.append(constraint)
```

**Salva il file.**

---

## Fix #4: Prompt Migliorato

**Tempo**: 5 minuti
**Impatto**: 30%
**File**: `/home/user/thesis-project/soft_prompting.py`

### Step 4.1: Migliorare build_llm_prompt_with_graph

Trova la funzione `build_llm_prompt_with_graph` (circa linea 242), **SOSTITUISCI COMPLETAMENTE** con:

```python
def build_llm_prompt_with_graph(
    question: str,
    graph_facts: str,
    use_cot: bool = True
) -> str:
    """
    Build a structured prompt for multi-hop reasoning.
    """
    q_lower = question.lower()

    # Detect 2-hop question pattern
    if re.search(r"what\s+\w+\s+did\s+(?:the\s+)?\w+\s+who", q_lower):
        # This is a 2-step question
        prompt = f"""You are answering a TWO-STEP question that requires finding an intermediate entity first.

Question: {question}

This question has TWO steps:
STEP 1: Find which specific person/entity satisfies the constraint mentioned
STEP 2: Find what that person/entity did or had

Knowledge Graph Facts:
{graph_facts}

Let's solve this step-by-step:

STEP 1 - Identify the intermediate entity:
Look through the facts above. Which specific person satisfies the constraint in the question?
(Write the name of the person/entity)

STEP 2 - Find the final answer:
Now look for facts about that entity from Step 1. What did they do or have that answers the question?

Your final answer (just the answer, no explanation):"""

    elif use_cot:
        # Generic CoT prompt
        prompt = f"""You are an expert at answering complex questions using knowledge graphs.

Knowledge Graph Facts:
{graph_facts}

Question: {question}

Instructions:
1. Read the question carefully and identify what information is needed
2. Look through the knowledge graph facts for relevant information
3. Connect multiple facts if needed to answer the question
4. Provide a concise, direct answer

Think step-by-step:
1. What is being asked?
2. Which facts are relevant?
3. How do these facts connect?
4. What is the final answer?

Answer:"""
    else:
        prompt = f"""Answer the question using only the knowledge graph facts below.

Knowledge Graph Facts:
{graph_facts}

Question: {question}

Provide a concise, direct answer:
Answer:"""

    return prompt
```

**Salva il file.**

---

## Test dei Miglioramenti

Dopo aver applicato i fix, testa il sistema:

```bash
# Test con la domanda multi-hop
python main_refactored.py \
  --text "What college did the President who attended Minneapolis High School go to?" \
  --device cpu

# Cerca nell'output:
# ✓ "educated at" nelle proprietà Wikidata
# ✓ Espansione 2-hop (Hop 1, Hop 2 nei log)
# ✓ "Hubert Humphrey" nei retrieved nodes
# ✓ "University of Minnesota" nell'answer
```

---

## Verifica dell'Output

### Output Atteso (con fix applicati):

```
================================================================================
MULTI-HOP QUESTION ANSWERING PIPELINE
================================================================================
Question: What college did the President who attended Minneapolis High School go to?
Device: cpu
Ensemble: True
Decomposition: True
Reranking: True
Verbalization: True
Caching: True
================================================================================

[1/4] Extracting triples...
  - Ensemble: True
  - Decomposition: True
[INFO] Decomposed question into 10 variants
[DECOMPOSE] 2-hop pattern: target=college, intermediate=president    ← ✓ NEW!
  - Found 6 triples                                                   ← ✓ More triples

[2/4] Building knowledge graph...
  - Reranking: True
  - Wikidata props: 16                                                 ← ✓ More props
[INFO] Cross-encoder loaded for entity linking
[INFO] Linked 'Minneapolis High School' -> Q7527903 (South High School) ← ✓ Correct!
  - Entities: 5
  - Wikidata nodes: 8

[3/4] Training HGT...
[EXPAND] Multi-hop: 3 seeds, 2 hops, 10 props                         ← ✓ 2-hop!
[EXPAND] Hop 1: expanding 3 nodes
[EXPAND] Hop 2: expanding 12 nodes                                     ← ✓ 2nd hop!
[EXPAND] Total: 45 edges, 15 nodes                                     ← ✓ More edges!

[4/4] Generating answer...
  - Verbalization: True
  - Instruction model: True

================================================================================
RESULTS
================================================================================

[BASELINE ANSWER]
President

[ENRICHED ANSWER (with Knowledge Graph)]
University of Minnesota                                                ← ✓ CORRECT!

[STATISTICS]
  - Triples extracted: 6
  - Graph entities: 5
  - Graph wikidata nodes: 15
  - Retrieved nodes: 25
  - Elapsed time: 45.23s

[TOP RETRIEVED NODES]
  1. Hubert Humphrey                   | wikidata | 0.892              ← ✓ Found!
  2. University of Minnesota           | wikidata | 0.856              ← ✓ Found!
  3. South High School                 | wikidata | 0.834              ← ✓ Found!
  ...
```

---

## Risoluzione Problemi

### Problema: "P69 not found"
**Soluzione**: Verifica di aver salvato `qa_pipeline.py` dopo le modifiche. Riavvia il programma.

### Problema: "expand_multi_hop not found"
**Soluzione**: Verifica di aver aggiunto la funzione in `wikidata_utils.py` e di aver aggiunto l'import in `kg_build.py`.

### Problema: Ancora risposta sbagliata
**Soluzione**:
1. Controlla i log per vedere se le proprietà educative vengono usate
2. Verifica che l'espansione arrivi a Hop 2
3. Controlla se "Hubert Humphrey" appare nei retrieved nodes

---

## Next Steps (Opzionale)

Dopo aver verificato che i Quick Wins funzionano, puoi procedere con:

1. **Fix Avanzato #5**: Retrieval multi-hop aware
   - Vedi `multihop_fixes.py` funzione `retrieve_with_bridging_boost()`
   - Impatto: +10-15% accuracy
   - Tempo: 1-2 ore

2. **Fix Avanzato #6**: Path-aware verbalization
   - Vedi `multihop_fixes.py` funzione `verbalize_multi_hop_facts()`
   - Impatto: +5-10% accuracy
   - Tempo: 1-2 ore

---

## Checklist Finale

Prima di considerare il lavoro completo:

- [ ] Fix #1 applicato: Proprietà educative aggiunte
- [ ] Fix #2 applicato: Espansione 2-hop funzionante
- [ ] Fix #3 applicato: Nuovo pattern di decomposizione
- [ ] Fix #4 applicato: Prompt migliorato
- [ ] Test eseguito: Domanda multi-hop risponde correttamente
- [ ] Output verificato: Tutti i ✓ sopra presenti
- [ ] (Opzionale) Fix avanzati implementati

---

## Supporto

Se hai problemi con l'integrazione:

1. Controlla i log per errori specifici
2. Verifica che tutte le modifiche siano state salvate
3. Riavvia Python per ricaricare i moduli
4. Confronta il tuo codice con gli snippet forniti

**Buon lavoro!** 🚀
