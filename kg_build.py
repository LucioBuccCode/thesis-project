# kg_build.py
from typing import List, Dict, Tuple, Optional
import os, json, time, re
import torch
from torch_geometric.data import HeteroData
from sentence_transformers import SentenceTransformer
from wikidata_utils import (
    wd_search_qid, wd_get_label_desc, expand_with_wikidata_qids
)


def _embed_texts(texts: List[str], model: str, device: str) -> torch.Tensor:
    st = SentenceTransformer(model, device=device)
    with torch.no_grad():
        embs = st.encode(texts, convert_to_tensor=True, device=device, show_progress_bar=False)
    return embs


def link_entities_to_qids(entities: List[str],
                          cache_path: str = "outputs/entity2qid.json",
                          lang: str = "en",
                          sleep_s: float = 0.1,
                          question_context: Optional[str] = None,
                          use_reranking: bool = True):
    """
    Enhanced entity linking with cross-encoder reranking.

    Args:
        entities: List of entity mentions to link
        cache_path: Cache file for QID mappings
        lang: Language code
        sleep_s: Sleep between API calls
        question_context: Original question for disambiguation
        use_reranking: If True, use cross-encoder to rerank candidates
    """
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)

    # Load cross-encoder if reranking enabled
    cross_encoder = None
    if use_reranking:
        try:
            from sentence_transformers import CrossEncoder
            cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
            print("[INFO] Cross-encoder loaded for entity linking")
        except Exception as e:
            print(f"[WARN] Could not load cross-encoder: {e}")
            use_reranking = False

    out = {}
    for e in entities:
        if e in cache and cache[e] is not None:
            out[e] = cache[e]
            continue

        # Get multiple candidates instead of just top-1
        candidates = _get_wikidata_candidates(e, lang=lang, limit=5)

        if not candidates:
            out[e] = None
            time.sleep(sleep_s)
            continue

        # Rerank candidates using cross-encoder with question context
        if use_reranking and cross_encoder and question_context:
            best_candidate = _rerank_candidates(
                entity_mention=e,
                candidates=candidates,
                context=question_context,
                cross_encoder=cross_encoder
            )
        else:
            # Fallback: use first candidate
            best_candidate = candidates[0]

        out[e] = best_candidate
        time.sleep(sleep_s)

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out

def _get_wikidata_candidates(name: str, lang: str = "en", limit: int = 5) -> List[Dict]:
    """Get top-K candidates from Wikidata search."""
    import requests
    WD_API = "https://www.wikidata.org/w/api.php"
    USER_AGENT = "IE-HGT-Research/1.0 (your_email@example.com)"
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    params = {
        "action": "wbsearchentities",
        "search": name,
        "language": lang,
        "format": "json",
        "type": "item",
        "limit": limit
    }
    try:
        r = session.get(WD_API, params=params, timeout=15)
        r.raise_for_status()
        results = r.json().get("search", [])

        candidates = []
        for item in results:
            candidates.append({
                "qid": item["id"],
                "label": item.get("label", ""),
                "desc": item.get("description", "")
            })
        return candidates
    except Exception as e:
        print(f"[WARN] Wikidata search failed for '{name}': {e}")
        return []

def _rerank_candidates(entity_mention: str,
                       candidates: List[Dict],
                       context: str,
                       cross_encoder) -> Dict:
    """
    Rerank candidates using cross-encoder with question context.

    Args:
        entity_mention: Original entity string
        candidates: List of {qid, label, desc} dicts
        context: Question or surrounding text
        cross_encoder: Loaded CrossEncoder model

    Returns:
        Best candidate dict
    """
    if not candidates:
        return None

    # Build pairs for cross-encoder: (context + entity, candidate description)
    pairs = []
    for cand in candidates:
        query = f"{context} [SEP] {entity_mention}"
        candidate_text = f"{cand['label']} - {cand['desc']}" if cand['desc'] else cand['label']
        pairs.append([query, candidate_text])

    # Score all pairs
    scores = cross_encoder.predict(pairs)

    # Get best
    best_idx = scores.argmax()
    best_candidate = candidates[best_idx]

    print(f"[INFO] Linked '{entity_mention}' -> {best_candidate['qid']} ({best_candidate['label']}) [score: {scores[best_idx]:.3f}]")

    return best_candidate


def build_enriched_hetero_graph(
        triples: List[Dict[str,str]],
        embed_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str = "cpu",
        # wikidata expansion policy:
        wd_props: Optional[List[str]] = None,   # es. ["P26","P27"] o ["spouse","country of citizenship"]
        wd_lang: str = "en",
        wd_max_edges_per_qid: int = 8,
        wd_preferred_only: bool = False,
        # enhanced entity linking:
        question_context: Optional[str] = None,
        use_reranking: bool = True,
):
    """
    Costruisce un HeteroData con:
    - node types: 'entity' (testo), 'wikidata' (QID)
    - edge types: (entity,R,entity), (wikidata,PID,wikidata), PONTI (entity,'sameAs','wikidata') (+ inverso)
    - features: entity.x = embedding mention-level; wikidata.x = embedding label+desc

    Enhanced with:
    - Context-aware entity embeddings
    - Cross-encoder entity linking
    """
    os.makedirs("outputs", exist_ok=True)

    # 1) nodi entity - with context-aware embeddings
    entities = sorted(set([t["head"] for t in triples] + [t["tail"] for t in triples]))

    if not entities:
        raise ValueError("No entities found in triples. Cannot build graph.")

    ent2i = {e:i for i,e in enumerate(entities)}

    # Build context-aware entity texts
    if question_context:
        # Embed as: "Question: {q} | Entity: {e}"
        entity_texts = [f"Question: {question_context} | Entity: {e}" for e in entities]
    else:
        entity_texts = entities[:]

    entity_embs = _embed_texts(entity_texts, embed_model, device=device)

    # Validate embeddings
    if entity_embs.numel() == 0 or entity_embs.shape[0] == 0:
        raise ValueError(f"Entity embeddings are empty. Got shape: {entity_embs.shape}")

    data = HeteroData()
    data["entity"].x = entity_embs  # [N_ent, d]

    # 2) entity linking -> QID (with reranking)
    e2q = link_entities_to_qids(
        entities,
        cache_path="outputs/entity2qid.json",
        lang=wd_lang,
        question_context=question_context,
        use_reranking=use_reranking
    )

    # 3) espansione WD
    qids = [row["qid"] for row in e2q.values() if row and row.get("qid")]
    q_edges = expand_with_wikidata_qids(qids,
                                        prop_keys=wd_props, prop_lang=wd_lang,
                                        max_edges_per_qid=wd_max_edges_per_qid,
                                        preferred_only=wd_preferred_only)

    # 4) lista completa di QID (seed + expansion)
    qids_all = sorted(set(qids + [h for (h,_,_) in q_edges] + [t for (_,_,t) in q_edges]))

    # 5) feature nodi wikidata = embed(label + ' — ' + desc)
    if qids_all:
        qid2i = {q:i for i,q in enumerate(qids_all)}
        wd_texts = []
        for q in qids_all:
            lab, des = wd_get_label_desc(q, lang=wd_lang)
            text = (lab + (" — " + des if des else "")).strip()
            wd_texts.append(text if text else q)
        wd_embs = _embed_texts(wd_texts, embed_model, device=device)

        # Validate wikidata embeddings
        if wd_embs.numel() > 0 and wd_embs.shape[0] > 0:
            data["wikidata"].x = wd_embs  # [N_qid, d]
        else:
            print(f"[WARN] Wikidata embeddings are empty, creating dummy node")
            # Create a single dummy wikidata node
            qid2i = {"DUMMY": 0}
            qids_all = ["DUMMY"]
            data["wikidata"].x = entity_embs[:1]  # Use first entity embedding as dummy
    else:
        print(f"[WARN] No Wikidata QIDs found, skipping wikidata node creation")
        qid2i = {}
        qids_all = []

    # helper normalizzazione relazioni testuali
    def norm_rel(r: str) -> str:
        r = r.strip().replace(" ", "_")
        r = re.sub(r"[^0-9A-Za-z_]+", "", r)
        return r

    # 6) archi entity-entity dal testo
    for t in triples:
        h, r, o = ent2i[t["head"]], norm_rel(t["relation"]), ent2i[t["tail"]]
        key = ("entity", r, "entity")
        if key not in data.edge_types or data[key].edge_index is None:
            data[key].edge_index = torch.tensor([[h],[o]], dtype=torch.long)
        else:
            data[key].edge_index = torch.cat([data[key].edge_index, torch.tensor([[h],[o]])], dim=1)

    # 7) archi wikidata-wikidata (PID)
    if qid2i:  # Only if we have wikidata nodes
        for (hq, pid, tq) in q_edges:
            if hq in qid2i and tq in qid2i:  # Check both QIDs exist
                h, t = qid2i[hq], qid2i[tq]
                key = ("wikidata", pid, "wikidata")
                if key not in data.edge_types or data[key].edge_index is None:
                    data[key].edge_index = torch.tensor([[h],[t]], dtype=torch.long)
                else:
                    data[key].edge_index = torch.cat([data[key].edge_index, torch.tensor([[h],[t]])], dim=1)

    # 8) PONTI entity↔wikidata (sameAs)
    if qid2i:  # Only if we have wikidata nodes
        same_h, same_t = [], []
        for name, row in e2q.items():
            if row and row.get("qid") in qid2i and name in ent2i:
                same_h.append(ent2i[name]); same_t.append(qid2i[row["qid"]])
        if same_h:
            edge_same = torch.tensor([same_h, same_t], dtype=torch.long)
            data[("entity", "sameAs", "wikidata")].edge_index = edge_same
            data[("wikidata", "sameAs", "entity")].edge_index = edge_same.flip(0)

    # Ensure graph has at least both node types for HGT
    if "wikidata" not in data.node_types:
        print("[WARN] No wikidata nodes, creating minimal dummy node")
        # Create a single dummy wikidata node
        data["wikidata"].x = entity_embs[:1].clone()
        qids_all = ["DUMMY_QID"]

    meta = {
        "entity_count": len(entities),
        "wikidata_count": len(qids_all) if qids_all else 1,
        "entity_examples": entities[:5],
        "wikidata_examples": qids_all[:5] if qids_all else ["DUMMY_QID"]
    }
        # === salvataggio triplette arricchite ===
    expanded_triples = []

    # 1. triple testuali
    for t in triples:
        expanded_triples.append({
            "head": t["head"],
            "relation": t["relation"],
            "tail": t["tail"],
            "source": "text"
        })

    # 2. triple da Wikidata
    for (hq, pid, tq) in q_edges:
        expanded_triples.append({
            "head": hq,
            "relation": pid,
            "tail": tq,
            "source": "wikidata"
        })

    # 3. ponti entity↔wikidata
    for name, row in e2q.items():
        if row and row.get("qid"):
            expanded_triples.append({
                "head": name,
                "relation": "sameAs",
                "tail": row["qid"],
                "source": "bridge"
            })

    # salva
    with open("outputs/triples_expanded.json", "w", encoding="utf-8") as f:
        import json
        json.dump(expanded_triples, f, ensure_ascii=False, indent=2)
    print(f"[+] Saved enriched triples → outputs/triples_expanded.json")

    return data, meta
