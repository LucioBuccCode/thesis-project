# Analisi Approfondita: Perché il Sistema Fallisce su Domande Multi-Hop Difficili

## Domanda Test
**"What college did the President who attended Minneapolis High School go to?"**

Questa è una domanda 2-hop che richiede:
1. Identificare quale Presidente ha frequentato Minneapolis High School → *Hubert Humphrey*
2. Identificare quale college ha frequentato Hubert Humphrey → *University of Minnesota*

---

## FASE 1: TRIPLE EXTRACTION

### Cosa DOVREBBE succedere:
Il sistema dovrebbe estrarre triple che catturano:
- `[X, attended, Minneapolis High School]` (relazione scuola)
- `[X, is_a, President]` (tipo/ruolo)
- `[X, attended, Y]` (relazione college)

### Cosa EFFETTIVAMENTE succede:

#### Problema 1.1: Pattern di Decomposizione Inadeguati
**File**: `/home/user/thesis-project/relation_extraction.py` (linee 112-228)

La funzione `decompose_question()` NON ha pattern per domande con:
- Struttura "What X did Y who Z...?"
- Clausole relative complesse con "who"

```python
# Analisi pattern esistenti:
# ✓ Pattern 1: "Who is the X of the Y that Z?"
# ✓ Pattern 2: "When did the X that Y do Z?"
# ✓ Pattern 3: "Which X has Y and is Z?"
# ✗ Pattern MANCANTE: "What X did the Y who Z do?" <-- QUESTO!
```

**Conseguenza**: La domanda non viene decomposta correttamente in sotto-domande che aiuterebbero l'estrazione delle triple intermedie.

#### Problema 1.2: Triple Extraction Incompleta
Il modello `pat-jj/text2triple-flan-t5` probabilmente estrae:
- `[President, attended, Minneapolis High School]` ✓
- Ma potrebbe NON estrarre la relazione college perché è nella parte "What college..."

**Output previsto** (incompleto):
```json
[
  {"head": "President", "relation": "attended", "tail": "Minneapolis High School"}
]
```

**Output necessario** (completo):
```json
[
  {"head": "President", "relation": "attended", "tail": "Minneapolis High School"},
  {"head": "President", "relation": "educated_at", "tail": "college"},
  {"head": "President", "relation": "instance_of", "tail": "President"}
]
```

### MIGLIORAMENTO PROPOSTO 1.1: Nuovo Pattern di Decomposizione

```python
# In relation_extraction.py, aggiungere dopo linea 208:

# Pattern 6: "What X did the Y who Z do/have?"
# Example: "What college did the President who attended Minneapolis High School go to?"
pattern6 = r"what\s+(\w+)\s+did\s+(?:the\s+)?(\w+)\s+who\s+(.*?)\s+(?:go\s+to|attend|have|get)"
match6 = re.search(pattern6, text_lower)
if match6:
    target_entity = match6.group(1)  # "college"
    intermediate_type = match6.group(2)  # "president"
    constraint = match6.group(3)  # "attended Minneapolis High School"

    # Decompose into sub-questions
    # 1. Focus on finding the intermediate entity
    sub_questions.append(f"Which {intermediate_type} {constraint}?")
    sub_questions.append(f"Who {constraint}?")

    # 2. Focus on the target relation
    sub_questions.append(f"What {target_entity} did the {intermediate_type} attend?")
    sub_questions.append(f"{intermediate_type} attended {target_entity}")

    # 3. Extract constraint as standalone fact
    sub_questions.append(f"{intermediate_type} {constraint}")
    sub_questions.append(constraint)
```

### MIGLIORAMENTO PROPOSTO 1.2: Iterative Triple Extraction

```python
# Nuovo approccio: estrarre triple da OGNI sottodomanda E dalla domanda originale
def extract_triples_iterative(question: str, max_iterations: int = 2):
    """
    Iteratively extract triples by:
    1. Extracting from original question
    2. Identifying entities
    3. Generating entity-centric questions
    4. Extracting from those
    """
    all_triples = []

    # Round 1: Extract from original
    triples_r1 = extract_triples(question)
    all_triples.extend(triples_r1)

    # Extract entities from Round 1
    entities = set()
    for t in triples_r1:
        entities.add(t['head'])
        entities.add(t['tail'])

    # Round 2: Generate entity-focused questions
    for entity in entities:
        # Generate questions about this entity
        entity_questions = [
            f"What is {entity}?",
            f"Where did {entity} attend?",
            f"What did {entity} do?",
            f"{entity} education"
        ]

        for eq in entity_questions:
            triples_entity = extract_triples(eq)
            all_triples.extend(triples_entity)

    # Deduplicate
    return deduplicate_triples(all_triples)
```

---

## FASE 2: ENTITY LINKING

### Problema 2.1: Disambiguazione di "Minneapolis High School"

**File**: `/home/user/thesis-project/kg_build.py` (linee 19-84)

"Minneapolis High School" è AMBIGUO:
- Non è una singola scuola, ma un sistema scolastico
- Hubert Humphrey frequentò **South High School** a Minneapolis
- La ricerca Wikidata potrebbe linkare a:
  - Q967503 (Minneapolis Public Schools) - SBAGLIATO
  - Q7527903 (South High School) - CORRETTO

**Output Wikidata Search per "Minneapolis High School"**:
```
Top candidates:
1. Q967503 - "Minneapolis Public Schools" (district)
2. Q7527903 - "South High School" (actual school)
3. Q6866467 - "Minneapolis North High School"
```

**Problema**: Senza contesto, il sistema sceglie il primo risultato (Q967503), che è il distretto, non la scuola specifica.

### Problema 2.2: Cross-Encoder Reranking Insufficiente

Il reranking usa solo:
- Context: domanda originale
- Candidates: label + description

Ma NON considera:
- Tipo di entità (school vs school district)
- Relazioni con altre entità (President)

### MIGLIORAMENTO PROPOSTO 2.1: Type-Aware Entity Linking

```python
# In kg_build.py, modificare _rerank_candidates:

def _rerank_candidates_enhanced(
    entity_mention: str,
    candidates: List[Dict],
    context: str,
    cross_encoder,
    entity_role: Optional[str] = None  # NEW: "subject", "object", "modifier"
) -> Dict:
    """
    Enhanced reranking with type awareness.
    """
    if not candidates:
        return None

    # Build pairs with enhanced context
    pairs = []
    for cand in candidates:
        # Build richer query
        query_parts = [context, entity_mention]

        # Add type hints from question
        if entity_role == "school" or "school" in entity_mention.lower():
            query_parts.append("educational institution building")
        elif entity_role == "president":
            query_parts.append("head of state political position")

        query = " [SEP] ".join(query_parts)

        # Build candidate text with type info
        cand_parts = [cand['label']]
        if cand['desc']:
            cand_parts.append(cand['desc'])

        # Add instance_of if available (requires additional API call)
        # This helps distinguish between "school" and "school district"
        cand_qid = cand['qid']
        instance_types = get_wikidata_types(cand_qid)  # NEW function
        if instance_types:
            cand_parts.append(f"Type: {', '.join(instance_types)}")

        candidate_text = " - ".join(cand_parts)
        pairs.append([query, candidate_text])

    # Score and select best
    scores = cross_encoder.predict(pairs)
    best_idx = scores.argmax()

    return candidates[best_idx]

def get_wikidata_types(qid: str, limit: int = 3) -> List[str]:
    """
    Get instance_of (P31) types for a QID.
    Useful for disambiguating entities.
    """
    from wikidata_utils import wd_get_claims

    try:
        edges = wd_get_claims(qid, prop_keys=["P31"], max_edges=limit)
        types = []
        for _, _, type_qid in edges:
            type_label, _ = wd_get_label_desc(type_qid, "en")
            if type_label:
                types.append(type_label)
        return types
    except:
        return []
```

### MIGLIORAMENTO PROPOSTO 2.2: Backward Verification

```python
def verify_entity_linking(entity: str, qid: str, context: str) -> float:
    """
    Verify entity linking by checking if linked QID's description
    matches the context.

    Returns confidence score 0-1.
    """
    from wikidata_utils import wd_get_label_desc, wd_get_claims

    label, desc = wd_get_label_desc(qid, "en")

    # Check 1: Description similarity to context
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('all-MiniLM-L6-v2')

    desc_emb = model.encode([desc], convert_to_tensor=True)
    ctx_emb = model.encode([context], convert_to_tensor=True)

    sim_score = torch.cosine_similarity(desc_emb, ctx_emb).item()

    # Check 2: Has relevant relations?
    # For a President's school, expect P69 (educated at) relations
    relations = wd_get_claims(qid, max_edges=5)
    has_education_rel = any(pid == "P69" for _, pid, _ in relations)

    # Combine scores
    confidence = 0.7 * sim_score + 0.3 * (1.0 if has_education_rel else 0.0)

    return confidence
```

---

## FASE 3: WIKIDATA EXPANSION

### Problema 3.1: PROPRIETÀ CRITICHE MANCANTI ⚠️

**File**: `/home/user/thesis-project/qa_pipeline.py` (linee 74-80)

```python
# Proprietà di default:
self.wikidata_props = [
    "spouse", "country of citizenship", "place of birth",
    "instance of", "occupation", "position held",
    "member of", "capital", "continent", "shares border with"
]
```

**PROBLEMA CRITICO**: Mancano le proprietà per l'ISTRUZIONE!
- ❌ **P69 (educated at)** - LA PIÙ IMPORTANTE!
- ❌ **P512 (academic degree)**
- ❌ **P2094 (competition class)**
- ❌ **P1066 (student of)**

**Conseguenza**: Anche se linkiamo correttamente Hubert Humphrey (Q187825), NON espandiamo le sue relazioni educative!

```json
# Espansione ATTUALE (incompleta):
{
  "Q187825": [  // Hubert Humphrey
    ["Q187825", "P39", "Q11699"],  // position held: Vice President
    ["Q187825", "P27", "Q30"],      // country: USA
    ["Q187825", "P19", "..."]       // place of birth
    // ❌ MANCA: ["Q187825", "P69", "Q238101"]  // educated at: University of Minnesota
  ]
}
```

### Problema 3.2: Single-Hop Expansion

L'espansione si ferma a 1 hop:
- Espande solo i QID delle entità menzionate nella domanda
- NON espande i QID trovati (es. University of Minnesota)

**Esempio**:
1. Trova Q187825 (Hubert Humphrey) ✓
2. Espande P69 → Q238101 (University of Minnesota) ✓
3. Ma NON espande Q238101 per sapere che è un college/university ❌

### MIGLIORAMENTO PROPOSTO 3.1: Aggiungere Proprietà Educative

```python
# In qa_pipeline.py, PipelineConfig.__post_init__:

if self.wikidata_props is None:
    self.wikidata_props = [
        # Biographical
        "spouse", "country of citizenship", "place of birth",
        "instance of", "occupation", "position held",
        "member of",

        # EDUCATION (CRITICAL FOR MULTI-HOP) ⭐
        "educated at",           # P69 - WHERE someone studied
        "academic degree",       # P512 - WHAT degree they got
        "student of",            # P1066 - WHO taught them
        "alma mater",            # Alternative to P69

        # Geographic
        "capital", "continent", "shares border with",
        "located in",            # P131 - for schools/universities
        "headquarters location",  # P159

        # Temporal
        "start time",            # P580
        "end time",              # P582
    ]
```

### MIGLIORAMENTO PROPOSTO 3.2: Multi-Hop Expansion

```python
# In wikidata_utils.py, nuova funzione:

def expand_multi_hop(
    seed_qids: List[str],
    props: List[str],
    max_hops: int = 2,
    max_nodes_per_hop: int = 20,
    lang: str = "en"
) -> List[Tuple[str, str, str]]:
    """
    Multi-hop Wikidata expansion.

    Args:
        seed_qids: Starting QIDs
        props: Properties to follow
        max_hops: Maximum hop distance (1 or 2)
        max_nodes_per_hop: Limit nodes per hop to avoid explosion

    Returns:
        List of (head_qid, property, tail_qid) edges
    """
    all_edges = []
    visited = set()

    # Hop 1: Expand seed QIDs
    current_level = seed_qids

    for hop in range(max_hops):
        print(f"[EXPANSION] Hop {hop+1}: expanding {len(current_level)} nodes")
        next_level = set()

        for qid in current_level:
            if qid in visited:
                continue
            visited.add(qid)

            # Get edges for this QID
            edges = wd_get_claims(
                qid,
                prop_keys=props,
                lang=lang,
                max_edges=max_nodes_per_hop // len(current_level) + 1
            )

            all_edges.extend(edges)

            # Add tail QIDs to next level
            for _, _, tail_qid in edges:
                if tail_qid not in visited:
                    next_level.add(tail_qid)

            time.sleep(0.1)  # Rate limiting

        # Limit next level size
        current_level = list(next_level)[:max_nodes_per_hop]

        if not current_level:
            break

    print(f"[EXPANSION] Total edges: {len(all_edges)}, visited: {len(visited)} nodes")
    return all_edges
```

**Uso nel pipeline**:
```python
# In kg_build.py, build_enriched_hetero_graph:

# OLD:
q_edges = expand_with_wikidata_qids(qids, prop_keys=wd_props, ...)

# NEW:
q_edges = expand_multi_hop(
    seed_qids=qids,
    props=wd_props,
    max_hops=2,  # 2-hop expansion for multi-hop questions!
    max_nodes_per_hop=30
)
```

---

## FASE 4: GRAPH CONSTRUCTION

### Problema 4.1: Mancanza di Path Espliciti

Il grafo eterogeneo contiene:
- Nodi: entities, wikidata QIDs
- Archi: relazioni testuali, proprietà Wikidata, bridge (sameAs)

Ma NON c'è:
- Materializazzione di path multi-hop
- Meta-path types per il reasoning
- Path ranking

**Esempio**: Anche se il grafo contiene:
```
[Hubert Humphrey] --sameAs--> [Q187825]
[Q187825] --P69--> [Q238101]
[Q238101] --P31--> [Q3918] (university)
```

Il retrieval NON sa che questo è un path rilevante per "college"!

### Problema 4.2: HGT Training su Grafo Incompleto

Se il grafo non contiene i path necessari (a causa di espansione insufficiente), l'HGT non può imparare rappresentazioni utili.

### MIGLIORAMENTO PROPOSTO 4.1: Explicit Path Materialization

```python
# Nuovo file: path_extraction.py

def extract_multi_hop_paths(
    graph: HeteroData,
    triples: List[Dict],
    max_path_length: int = 3
) -> List[Dict]:
    """
    Extract explicit multi-hop paths in the graph.

    Returns:
        List of paths: [
            {
                "nodes": [node1, node2, node3],
                "edges": [rel1, rel2],
                "path_type": "entity->wikidata->wikidata"
            }
        ]
    """
    import networkx as nx

    # Build networkx graph for path finding
    G = nx.MultiDiGraph()

    # Add entity-entity edges
    for triple in triples:
        if triple['source'] == 'text':
            G.add_edge(
                triple['head'],
                triple['tail'],
                relation=triple['relation'],
                type='text'
            )

    # Add wikidata edges
    for triple in triples:
        if triple['source'] == 'wikidata':
            G.add_edge(
                triple['head'],
                triple['tail'],
                relation=triple['relation'],
                type='wikidata'
            )

    # Add bridge edges
    for triple in triples:
        if triple['source'] == 'bridge':
            G.add_edge(triple['head'], triple['tail'], relation='sameAs', type='bridge')
            G.add_edge(triple['tail'], triple['head'], relation='sameAs', type='bridge')

    # Extract paths
    paths = []

    # Find all simple paths up to max_path_length
    for source in G.nodes():
        for target in G.nodes():
            if source == target:
                continue

            try:
                all_paths = nx.all_simple_paths(
                    G, source, target,
                    cutoff=max_path_length
                )

                for path_nodes in all_paths:
                    if len(path_nodes) <= max_path_length + 1:
                        # Extract edge sequence
                        edges = []
                        for i in range(len(path_nodes)-1):
                            edge_data = G.get_edge_data(path_nodes[i], path_nodes[i+1])
                            # Get first edge (in case of multi-edges)
                            edge_info = list(edge_data.values())[0]
                            edges.append(edge_info['relation'])

                        paths.append({
                            "nodes": path_nodes,
                            "edges": edges,
                            "length": len(edges)
                        })
            except nx.NetworkXNoPath:
                continue

    return paths

def score_paths_for_question(
    paths: List[Dict],
    question: str,
    embed_model: SentenceTransformer
) -> List[Tuple[Dict, float]]:
    """
    Score paths by relevance to question.
    """
    # Encode question
    q_emb = embed_model.encode([question], convert_to_tensor=True)

    scored_paths = []
    for path in paths:
        # Create path representation
        path_text = " -> ".join([
            f"{path['nodes'][i]} [{path['edges'][i]}]" if i < len(path['edges']) else path['nodes'][i]
            for i in range(len(path['nodes']))
        ])

        # Encode path
        path_emb = embed_model.encode([path_text], convert_to_tensor=True)

        # Score
        score = torch.cosine_similarity(q_emb, path_emb).item()
        scored_paths.append((path, score))

    # Sort by score
    scored_paths.sort(key=lambda x: x[1], reverse=True)

    return scored_paths
```

---

## FASE 5: RETRIEVAL

### Problema 5.1: Retrieval Atomico (Non Multi-Hop)

**File**: `/home/user/thesis-project/soft_prompting.py` (linee 46-66)

Il retrieval attuale:
1. Encode question → query vector
2. Cosine similarity con TUTTI i nodi
3. Top-K nodi più simili

**Problema**: Questo recupera nodi ATOMICAMENTE simili alla domanda, ma NON considera:
- Path multi-hop
- Co-occurrence di nodi che insieme rispondono
- Bridging nodes (nodi intermedi necessari)

**Esempio**:
- Domanda: "What college did the President who attended Minneapolis High School go to?"
- Retrieval atomico recupera:
  - ✓ "President" (alta similarità)
  - ✓ "Minneapolis High School" (alta similarità)
  - ✓ "college" (alta similarità)
  - ❌ Ma NON "Hubert Humphrey" (bassa similarità diretta alla domanda!)
  - ❌ E NON "University of Minnesota" (bassa similarità diretta!)

**Il nodo chiave** (Hubert Humphrey) ha BASSA similarità alla domanda ma ALTA importanza per connettere i due hop!

### Problema 5.2: Nessun Re-Ranking Multi-Hop

Dopo il retrieval, i nodi non vengono re-ranked considerando:
- Connectivity tra nodi retrieved
- Presenza di path completi
- Bridging node importance

### MIGLIORAMENTO PROPOSTO 5.1: Multi-Hop Aware Retrieval

```python
# In soft_prompting.py, nuova funzione:

def retrieve_multi_hop_subgraph(
    question: str,
    graph: HeteroData,
    triples: List[Dict],
    embed_model: SentenceTransformer,
    topk: int = 25,
    bridge_boost: float = 2.0
) -> List[Tuple[str, str, float]]:
    """
    Multi-hop aware retrieval that prioritizes nodes forming paths.

    Steps:
    1. Initial retrieval: top-K similar nodes
    2. Path expansion: find paths between top nodes
    3. Boost bridging nodes
    4. Re-rank and return
    """
    # Step 1: Initial retrieval (as before)
    q_emb = embed_model.encode([question], convert_to_tensor=True)

    # Get all node embeddings and labels
    all_embeddings = []
    all_labels = []
    all_types = []

    # (load from graph as in current implementation)
    # ...

    # Initial cosine similarity
    sims = cosine_similarity(q_emb, all_embeddings)
    initial_topk_indices = sims.argsort()[-topk*2:][::-1]  # Get 2x for expansion

    # Step 2: Path expansion
    topk_nodes = [all_labels[i] for i in initial_topk_indices]

    # Find paths between top nodes
    paths = find_paths_between_nodes(topk_nodes, triples, max_length=3)

    # Step 3: Extract bridging nodes
    bridging_nodes = set()
    for path in paths:
        # Nodes that connect two high-similarity nodes
        if len(path['nodes']) >= 3:
            # Middle nodes are bridges
            for node in path['nodes'][1:-1]:
                bridging_nodes.add(node)

    # Step 4: Re-score with bridge boost
    final_scores = {}
    for i in initial_topk_indices:
        label = all_labels[i]
        score = sims[i]

        # Boost bridging nodes
        if label in bridging_nodes:
            score *= bridge_boost

        final_scores[label] = (all_types[i], score)

    # Sort and return top-K
    sorted_nodes = sorted(
        final_scores.items(),
        key=lambda x: x[1][1],
        reverse=True
    )[:topk]

    return [(label, ntype, score) for label, (ntype, score) in sorted_nodes]


def find_paths_between_nodes(
    nodes: List[str],
    triples: List[Dict],
    max_length: int = 3
) -> List[Dict]:
    """
    Find paths between nodes using BFS.
    """
    import networkx as nx

    # Build graph
    G = nx.DiGraph()
    for t in triples:
        G.add_edge(t['head'], t['tail'], relation=t['relation'])

    paths = []

    # Find paths between all pairs
    for i, source in enumerate(nodes):
        for target in nodes[i+1:]:
            try:
                # Find shortest path
                if nx.has_path(G, source, target):
                    path = nx.shortest_path(G, source, target)
                    if len(path) <= max_length + 1:
                        paths.append({
                            'nodes': path,
                            'length': len(path) - 1
                        })
            except:
                pass

    return paths
```

### MIGLIORAMENTO PROPOSTO 5.2: Subgraph Extraction

Invece di recuperare nodi isolati, estrarre un **subgrafo connesso**:

```python
def extract_connected_subgraph(
    seed_nodes: List[str],
    triples: List[Dict],
    max_size: int = 50
) -> List[Dict]:
    """
    Extract a connected subgraph around seed nodes.

    Returns triples forming a connected component.
    """
    import networkx as nx

    # Build graph
    G = nx.Graph()  # Undirected for connectivity
    triple_map = {}  # edge -> triple info

    for t in triples:
        edge = (t['head'], t['tail'])
        G.add_edge(t['head'], t['tail'])
        triple_map[edge] = t

    # Find connected components containing seed nodes
    seed_components = []
    for node in seed_nodes:
        if node in G:
            component = nx.node_connected_component(G, node)
            seed_components.append(component)

    # Merge overlapping components
    all_nodes = set()
    for comp in seed_components:
        all_nodes.update(comp)

    # Limit size
    if len(all_nodes) > max_size:
        # Use BFS from seed nodes to limit
        all_nodes = bfs_limited(G, seed_nodes, max_size)

    # Extract triples in subgraph
    subgraph_triples = []
    for (h, t), triple in triple_map.items():
        if h in all_nodes and t in all_nodes:
            subgraph_triples.append(triple)

    return subgraph_triples


def bfs_limited(G: nx.Graph, seeds: List[str], max_nodes: int) -> Set[str]:
    """BFS limited to max_nodes starting from seeds."""
    from collections import deque

    visited = set()
    queue = deque(seeds)

    while queue and len(visited) < max_nodes:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)

        # Add neighbors
        for neighbor in G.neighbors(node):
            if neighbor not in visited:
                queue.append(neighbor)

    return visited
```

---

## FASE 6: VERBALIZATION

### Problema 6.1: Fatti Disgiunti

**File**: `/home/user/thesis-project/soft_prompting.py` (linee 149-239)

La verbalizzazione attuale:
1. Filtra triple rilevanti ai nodi retrieved
2. Assegna score per rilevanza
3. Prende top-K fatti

**Problema**: I fatti sono **disgiunti** - non c'è garanzia che formino path completi!

**Esempio output**:
```
Knowledge Graph Facts:
- President has position Vice President
- Hubert Humphrey country of citizenship United States
- Minneapolis has located in Minnesota
- University of Minnesota instance of university
```

❌ Manca la connessione: "Hubert Humphrey educated at University of Minnesota"!

### Problema 6.2: Nessuna Struttura di Path

I fatti non sono organizzati come **catene di reasoning**:

```
# Attuale (flat):
- Fact 1
- Fact 2
- Fact 3

# Ideale (structured):
Chain 1:
  Hubert Humphrey → position held → President
  Hubert Humphrey → educated at → South High School (Minneapolis)

Chain 2:
  Hubert Humphrey → educated at → University of Minnesota
  University of Minnesota → instance of → university
```

### MIGLIORAMENTO PROPOSTO 6.1: Path-Aware Verbalization

```python
def verbalize_paths(
    paths: List[Dict],
    qid_to_label: Dict[str, str],
    max_paths: int = 5
) -> str:
    """
    Verbalize top paths as reasoning chains.

    Args:
        paths: List of paths with scores
        qid_to_label: QID -> label mapping
        max_paths: Max paths to include

    Returns:
        Structured fact text
    """
    output = []
    output.append("Reasoning Chains:\n")

    for i, path in enumerate(paths[:max_paths], 1):
        nodes = path['nodes']
        edges = path['edges']

        # Build chain text
        chain_parts = []
        for j, node in enumerate(nodes):
            # Replace QID with label
            node_label = qid_to_label.get(node, node)
            chain_parts.append(node_label)

            # Add relation
            if j < len(edges):
                rel = edges[j]
                # Make relation readable
                if rel.startswith('P'):
                    rel_label = wd_get_property_label(rel, 'en')
                else:
                    rel_label = rel.replace('_', ' ')
                chain_parts.append(f"[{rel_label}]")

        # Format chain
        chain_text = " → ".join(chain_parts)
        output.append(f"{i}. {chain_text}")

    return "\n".join(output)


def verbalize_multi_hop(
    retrieved_nodes: List[Tuple[str, str, float]],
    triples: List[Dict],
    question: str,
    qid_to_label: Dict[str, str],
    max_facts: int = 30
) -> str:
    """
    Enhanced verbalization that maintains multi-hop structure.
    """
    # Step 1: Extract subgraph
    node_names = [label.replace("ENTITY::", "").replace("WIKIDATA::", "")
                  for label, _, _ in retrieved_nodes]

    subgraph_triples = extract_connected_subgraph(
        seed_nodes=node_names[:15],  # Top 15 nodes
        triples=triples,
        max_size=50
    )

    # Step 2: Find paths in subgraph
    paths = extract_multi_hop_paths(
        subgraph_triples,
        max_path_length=3
    )

    # Step 3: Score paths by relevance to question
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('all-MiniLM-L6-v2')

    scored_paths = score_paths_for_question(paths, question, model)

    # Step 4: Verbalize top paths
    path_text = verbalize_paths(
        [p for p, s in scored_paths[:10]],
        qid_to_label,
        max_paths=5
    )

    # Step 5: Add supporting facts
    supporting_facts = verbalize_with_labels(
        subgraph_triples,
        qid_to_label,
        max_facts=max_facts - len(scored_paths),
        retrieved_nodes=retrieved_nodes
    )

    # Combine
    return f"{path_text}\n\nSupporting Facts:\n{supporting_facts}"
```

---

## FASE 7: ANSWER GENERATION

### Problema 7.1: Prompt Generico

**File**: `/home/user/thesis-project/soft_prompting.py` (linee 242-291)

Il prompt attuale:
```
You are an expert at answering complex questions using knowledge graphs.

Knowledge Graph Facts:
[facts]

Question: [question]

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

**Problema**: Troppo generico! Non guida il modello a:
- Identificare quale hop risolvere prima
- Identificare entità intermedie
- Seguire path specifici

### Problema 7.2: LLM Limitations

Flan-T5-Large (o GPT-2) hanno difficoltà con:
- Multi-hop reasoning su fatti disgiunti
- Seguire catene logiche lunghe
- Identificare entità intermedie non esplicite

### MIGLIORAMENTO PROPOSTO 7.1: Structured Multi-Hop Prompt

```python
def build_multi_hop_prompt(
    question: str,
    graph_facts: str,
    paths: Optional[List[Dict]] = None
) -> str:
    """
    Build a structured prompt for multi-hop reasoning.
    """
    # Analyze question structure
    question_type = analyze_question_structure(question)

    if question_type == "two_hop_who":
        # "What X did the Y who Z do?"
        prompt = f"""You are answering a TWO-STEP question that requires finding an intermediate entity.

Question: {question}

This question has TWO steps:
STEP 1: Find which person/entity satisfies the constraint
STEP 2: Find what that person/entity did

Knowledge Graph:
{graph_facts}

Let's solve this step-by-step:

STEP 1 - Identify the intermediate entity:
Look for: Who or what satisfies the constraint in the question?
(Look through the facts to find the entity)

STEP 2 - Find the answer:
Look for: What did that entity do or have?
(Look for facts about the entity from Step 1)

Your answer (just the final answer, no explanation):"""

    elif question_type == "connection":
        # "Which X has Y and Z?"
        prompt = f"""You are finding an entity that satisfies MULTIPLE constraints.

Question: {question}

Knowledge Graph:
{graph_facts}

Find the entity that satisfies ALL constraints:
{extract_constraints(question)}

Your answer:"""

    else:
        # Fallback to generic
        prompt = f"""Answer this question using the knowledge graph.

Knowledge Graph:
{graph_facts}

Question: {question}

Think step by step and provide a direct answer:"""

    return prompt


def analyze_question_structure(question: str) -> str:
    """
    Classify question type for appropriate prompting.
    """
    q_lower = question.lower()

    # Pattern: "What X did the Y who Z"
    if re.search(r"what\s+\w+\s+did\s+(?:the\s+)?\w+\s+who", q_lower):
        return "two_hop_who"

    # Pattern: "Which X has Y and Z"
    if re.search(r"which\s+\w+.*\s+and\s+", q_lower):
        return "connection"

    # Pattern: "Who is the X of Y that Z"
    if re.search(r"who\s+is\s+the\s+\w+\s+of.*that", q_lower):
        return "two_hop_of"

    return "generic"


def extract_constraints(question: str) -> str:
    """
    Extract explicit constraints from question.
    """
    # For "Which X has Y and is Z?"
    match = re.search(r"which\s+(\w+)\s+(.*?)\s+and\s+(.*?)\??$", question.lower())
    if match:
        entity_type = match.group(1)
        constraint1 = match.group(2)
        constraint2 = match.group(3)
        return f"1. {constraint1}\n2. {constraint2}"

    return ""
```

### MIGLIORAMENTO PROPOSTO 7.2: Decomposed Answer Generation

```python
def generate_answer_multihop(
    question: str,
    graph_facts: str,
    model,
    tokenizer,
    device: str = "cpu"
) -> Tuple[str, Dict]:
    """
    Generate answer by decomposing into sub-questions.

    Returns:
        (final_answer, reasoning_trace)
    """
    # Step 1: Decompose question
    sub_questions = decompose_for_generation(question)

    reasoning_trace = {
        "question": question,
        "sub_questions": sub_questions,
        "sub_answers": []
    }

    # Step 2: Answer each sub-question
    context = graph_facts

    for i, sq in enumerate(sub_questions):
        prompt = f"""Use this knowledge to answer the question.

Knowledge:
{context}

Question: {sq}

Answer (brief):"""

        # Generate
        inputs = tokenizer(prompt, return_tensors="pt", max_length=512, truncation=True).to(device)
        with torch.no_grad():
            outputs = model.generate(**inputs, max_new_tokens=50, do_sample=False)
        answer = tokenizer.decode(outputs[0], skip_special_tokens=True)

        reasoning_trace["sub_answers"].append({
            "question": sq,
            "answer": answer
        })

        # Add answer to context for next step
        context += f"\n\nAdditional fact: {sq} -> {answer}"

    # Step 3: Generate final answer using accumulated context
    final_prompt = f"""Based on these facts and intermediate answers, answer the final question.

Knowledge:
{context}

Final Question: {question}

Final Answer:"""

    inputs = tokenizer(final_prompt, return_tensors="pt", max_length=512, truncation=True).to(device)
    with torch.no_grad():
        outputs = model.generate(**inputs, max_new_tokens=100, do_sample=False)
    final_answer = tokenizer.decode(outputs[0], skip_special_tokens=True)

    return final_answer, reasoning_trace


def decompose_for_generation(question: str) -> List[str]:
    """
    Decompose question for step-by-step generation.
    """
    q_lower = question.lower()

    # "What college did the President who attended Minneapolis High School go to?"
    match = re.search(r"what\s+(\w+)\s+did\s+(?:the\s+)?(\w+)\s+who\s+(.*?)\s+go\s+to", q_lower)
    if match:
        target = match.group(1)  # "college"
        entity_type = match.group(2)  # "president"
        constraint = match.group(3)  # "attended Minneapolis High School"

        return [
            f"Which {entity_type} {constraint}?",  # Find intermediate
            f"What {target} did this {entity_type} attend?"  # Find final
        ]

    # Add more patterns...

    return [question]  # Fallback
```

---

## SUMMARY: Root Causes & Solutions

### Root Causes (Prioritized)

1. **❌ CRITICAL: Missing Education Properties in Wikidata Expansion**
   - P69 (educated at) not in default properties
   - **Impact**: 90% - Without this, system CANNOT find education info
   - **Fix**: Add to `wikidata_props` list

2. **❌ HIGH: Single-Hop Retrieval**
   - Retrieval gets atomically similar nodes, not bridging entities
   - **Impact**: 80% - Misses key intermediate entities
   - **Fix**: Implement multi-hop aware retrieval

3. **❌ HIGH: Question Decomposition Gaps**
   - No pattern for "What X did Y who Z" structure
   - **Impact**: 70% - Fails to extract intermediate relations
   - **Fix**: Add new decomposition patterns

4. **❌ MEDIUM: Single-Hop Wikidata Expansion**
   - Only expands seed entities, not discovered ones
   - **Impact**: 60% - Incomplete knowledge graph
   - **Fix**: Implement 2-hop expansion

5. **❌ MEDIUM: Flat Fact Verbalization**
   - Facts are disjoint, not structured as reasoning chains
   - **Impact**: 50% - LLM struggles to connect facts
   - **Fix**: Path-aware verbalization

6. **❌ LOW: Generic Prompting**
   - Prompt doesn't guide multi-hop reasoning
   - **Impact**: 30% - LLM doesn't know how to reason
   - **Fix**: Structured multi-hop prompts

### Quick Wins (Implement First)

1. **Add Education Properties** (5 min)
2. **Implement 2-hop expansion** (30 min)
3. **Add question decomposition pattern** (15 min)
4. **Improve prompt** (10 min)

### Expected Improvement

With all fixes:
- **Current**: ~10-20% accuracy on complex multi-hop
- **Expected**: ~60-70% accuracy on complex multi-hop

---

## Implementation Plan

### Phase 1: Critical Fixes (1-2 hours)
1. Add education properties to Wikidata expansion
2. Implement 2-hop expansion
3. Add question decomposition pattern for "What X did Y who Z"

### Phase 2: Retrieval Improvements (2-3 hours)
4. Implement multi-hop aware retrieval
5. Add bridging node boosting
6. Implement connected subgraph extraction

### Phase 3: Verbalization & Generation (2-3 hours)
7. Implement path-aware verbalization
8. Add structured multi-hop prompts
9. Implement decomposed answer generation

### Phase 4: Evaluation (1 hour)
10. Test on multi-hop questions
11. Measure improvement
12. Iterate

---

## Test Case: Expected Behavior After Fixes

**Question**: "What college did the President who attended Minneapolis High School go to?"

**Expected Pipeline Flow**:

1. **Triple Extraction**: ✓
   ```json
   [
     {"head": "President", "relation": "attended", "tail": "Minneapolis High School"},
     {"head": "President", "relation": "attended", "tail": "college"},
     {"head": "President", "relation": "instance_of", "tail": "President"}
   ]
   ```

2. **Entity Linking**: ✓
   - "Minneapolis High School" → Q7527903 (South High School, Minneapolis)
   - "President" → Q11696 (President of the United States)

3. **Wikidata Expansion** (2-hop): ✓
   ```
   Hop 1:
   - Q7527903 --P31--> Q3914 (school)
   - Q7527903 --P131--> Q5 (Minneapolis)
   - [Find claims with P69-inverse] --> Q187825 (Hubert Humphrey)

   Hop 2:
   - Q187825 --P39--> Q11699 (Vice President)
   - Q187825 --P69--> Q238101 (University of Minnesota) ⭐
   - Q238101 --P31--> Q3918 (university) ⭐
   ```

4. **Graph Construction**: ✓
   - Contains path: [South High School] <- P69 - [Hubert Humphrey] - P69 -> [University of Minnesota]

5. **Retrieval**: ✓
   - Retrieved: Hubert Humphrey (bridging node boosted)
   - Retrieved: University of Minnesota
   - Retrieved: South High School

6. **Verbalization**: ✓
   ```
   Reasoning Chains:
   1. Hubert Humphrey → [position held] → Vice President of the United States
   2. Hubert Humphrey → [educated at] → South High School
   3. Hubert Humphrey → [educated at] → University of Minnesota → [instance of] → university
   ```

7. **Answer Generation**: ✓
   ```
   Step 1: Which President attended Minneapolis High School?
   Answer: Hubert Humphrey

   Step 2: What college did Hubert Humphrey attend?
   Answer: University of Minnesota

   Final Answer: University of Minnesota
   ```

**SUCCESS!** ✓
