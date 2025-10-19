# soft_prompting.py
# -*- coding: utf-8 -*-
from typing import List, Tuple, Dict, Optional
import os, json
import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForSeq2SeqLM
from sentence_transformers import SentenceTransformer
from graph_reasoning import retrieve_relevant_subgraph, extract_subgraph_embeddings


# --------- CARICAMENTO EMBEDDINGS GRAFO + MAPPING ---------
def load_graph_embeddings(entity_path="outputs/graph_entity_embs.pt",
                          wd_path="outputs/graph_wikidata_embs.pt",
                          triples_path="outputs/triples_expanded.json",
                          device: str = "cpu"):
    if not os.path.exists(entity_path) or not os.path.exists(wd_path):
        raise FileNotFoundError("Mancano gli embeddings del grafo (*.pt). Esegui lo Step 3 prima.")
    if not os.path.exists(triples_path):
        raise FileNotFoundError("Manca outputs/triples_expanded.json. Abilitalo nello Step 2.")
    z_ent = torch.load(entity_path, map_location=device)
    z_wd  = torch.load(wd_path, map_location=device)

    with open(triples_path, "r", encoding="utf-8") as f:
        triples = json.load(f)

    ent_names = sorted({t["head"] for t in triples if t.get("source")=="text"} |
                       {t["tail"] for t in triples if t.get("source")=="text"})
    qids = sorted({t["head"] for t in triples if t.get("source") in ("wikidata","bridge") and str(t["head"]).startswith("Q")} |
                  {t["tail"] for t in triples if t.get("source") in ("wikidata","bridge") and str(t["tail"]).startswith("Q")})
    return z_ent, ent_names, z_wd, qids


# --------- RETRIEVAL ---------
def build_retrieval_bank(z_ent: torch.Tensor, ent_names: List[str],
                         z_wd: torch.Tensor, qids: List[str]):
    labels_ent = [f"ENTITY::{n}" for n in ent_names]
    labels_wd  = [f"WIKIDATA::{q}" for q in qids]
    Z = torch.cat([z_ent, z_wd], dim=0)
    labels = labels_ent + labels_wd
    types  = ["entity"] * len(labels_ent) + ["wikidata"] * len(labels_wd)
    return Z, labels, types


def cosine_topk(query_vec: torch.Tensor,
                bank: torch.Tensor, labels: List[str], types: List[str],
                topk: int = 16, mix_entity_wd: Tuple[int,int] = (8,8)):
    q = F.normalize(query_vec, dim=-1)
    B = F.normalize(bank, dim=-1)
    sims = (q @ B.T).squeeze(0)
    idx_ent = [i for i,t in enumerate(types) if t=="entity"]
    idx_wd  = [i for i,t in enumerate(types) if t=="wikidata"]
    s_ent, s_wd = sims[idx_ent], sims[idx_wd]
    k_ent, k_wd = mix_entity_wd
    top_e_vals, top_e_idx = torch.topk(s_ent, k=min(k_ent, s_ent.numel()))
    top_w_vals, top_w_idx = torch.topk(s_wd,  k=min(k_wd,  s_wd.numel()))
    sel_idx = [idx_ent[i.item()] for i in top_e_idx] + [idx_wd[i.item()] for i in top_w_idx]
    sel_scores = torch.cat([top_e_vals, top_w_vals], dim=0)
    order = torch.argsort(sel_scores, descending=True)
    sel_idx = [sel_idx[i.item()] for i in order]
    sel_scores = sel_scores[order]
    out = []
    for i, s in zip(sel_idx[:topk], sel_scores[:topk]):
        out.append((labels[i], types[i], float(s.cpu().item()), bank[i:i+1]))
    return out


# --------- SOFT PROMPT ---------
class SoftPromptProjector(nn.Module):
    def __init__(self, d_src: int, d_tgt: int):
        super().__init__()
        self.lin = nn.Linear(d_src, d_tgt, bias=False)
        nn.init.xavier_uniform_(self.lin.weight)
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.lin(x)


def build_soft_prompt_vectors(retrieved, projector: nn.Module, device: str = "cpu"):
    if len(retrieved) == 0:
        return None
    vecs = [it[3] for it in retrieved]
    V = torch.cat(vecs, dim=0).to(device)
    return projector(V).unsqueeze(0)


# --------- GRAPH VERBALIZATION ---------
def verbalize_graph_facts(
    triples: List[Dict],
    retrieved_nodes: List[Tuple[str, str, float]],
    max_facts: int = 20
) -> str:
    """
    Convert graph knowledge to natural language text.

    Args:
        triples: List of {head, relation, tail, source} dicts
        retrieved_nodes: Retrieved nodes [(label, type, score)]
        max_facts: Maximum facts to include

    Returns:
        Natural language representation of graph facts
    """
    # Extract relevant entity and QID names from retrieved nodes
    relevant_entities = set()
    for label, ntype, _ in retrieved_nodes:
        if ntype == "entity":
            entity_name = label.replace("ENTITY::", "")
            relevant_entities.add(entity_name.lower())
        elif ntype == "wikidata":
            qid = label.replace("WIKIDATA::", "")
            relevant_entities.add(qid.lower())

    # Filter triples to only relevant ones
    relevant_triples = []
    for t in triples:
        head = t.get("head", "").lower()
        tail = t.get("tail", "").lower()

        # Check if triple involves retrieved entities
        if head in relevant_entities or tail in relevant_entities or \
           any(re in head or re in tail for re in relevant_entities):
            relevant_triples.append(t)

    # Build facts text
    facts = []
    for t in relevant_triples[:max_facts]:
        head = t["head"]
        rel = t["relation"]
        tail = t["tail"]
        source = t.get("source", "text")

        # Format based on source
        if source == "wikidata":
            # Wikidata facts: try to make readable
            rel_readable = rel.replace("P", "property_")
            facts.append(f"{head} has {rel_readable} {tail}")
        else:
            # Text triples: use natural format
            rel_lower = rel.lower().replace("_", " ")
            facts.append(f"{head} {rel_lower} {tail}")

    if not facts:
        return "No relevant facts found in knowledge graph."

    return "Knowledge Graph Facts:\n" + "\n".join([f"- {f}" for f in facts])


def verbalize_with_labels(
    triples: List[Dict],
    qid_to_label: Optional[Dict[str, str]] = None,
    max_facts: int = 20
) -> str:
    """
    Enhanced verbalization that replaces QIDs with human-readable labels.

    Args:
        triples: List of triples
        qid_to_label: Mapping from QID to label (e.g., Q76 -> Barack Obama)
        max_facts: Maximum facts

    Returns:
        Readable fact string
    """
    facts = []

    for t in triples[:max_facts]:
        head = t["head"]
        tail = t["tail"]
        rel = t["relation"]

        # Replace QIDs with labels if available
        if qid_to_label:
            if head.startswith("Q") and head in qid_to_label:
                head = qid_to_label[head]
            if tail.startswith("Q") and tail in qid_to_label:
                tail = qid_to_label[tail]

        # Make relation readable
        if rel.startswith("P") and rel[1:].isdigit():
            # It's a Wikidata property - try to load label
            from wikidata_utils import wd_get_property_label
            rel_label = wd_get_property_label(rel, "en")
        else:
            rel_label = rel.replace("_", " ").lower()

        facts.append(f"{head} {rel_label} {tail}")

    return "\n".join([f"- {f}" for f in facts])


def build_llm_prompt_with_graph(
    question: str,
    graph_facts: str,
    use_cot: bool = True
) -> str:
    """
    Build a structured prompt combining question and graph facts.

    Args:
        question: The input question
        graph_facts: Verbalized graph knowledge
        use_cot: If True, add chain-of-thought instruction

    Returns:
        Formatted prompt
    """
    if use_cot:
        prompt = f"""You are a helpful AI assistant. Use the provided knowledge graph facts to answer the question.

{graph_facts}

Question: {question}

Let's think step by step to find the answer:
Answer:"""
    else:
        prompt = f"""Use the following facts to answer the question.

{graph_facts}

Question: {question}
Answer:"""

    return prompt


# --------- LLM GENERATION ---------
def _embeds_from_text(text: str, tokenizer, model, device="cpu"):
    input_ids = tokenizer(text, return_tensors="pt").input_ids.to(device)
    return model.get_input_embeddings()(input_ids)


def generate_with_soft_prompt(model, tokenizer, text: str,
                              soft_embeds=None, device="cpu",
                              max_new_tokens: int = 120):
    model.eval()
    with torch.no_grad():
        txt_emb = _embeds_from_text(text, tokenizer, model, device)
        if soft_embeds is not None:
            inputs_embeds = torch.cat([soft_embeds.to(device), txt_emb], dim=1)
        else:
            inputs_embeds = txt_emb
        attn_mask = torch.ones(inputs_embeds.shape[:-1], dtype=torch.long, device=device)
        try:
            out = model.generate(inputs_embeds=inputs_embeds,
                                 attention_mask=attn_mask,
                                 max_new_tokens=max_new_tokens,
                                 do_sample=False,
                                 pad_token_id=tokenizer.eos_token_id)
            return tokenizer.decode(out[0], skip_special_tokens=True)
        except TypeError:
            ids = tokenizer(text, return_tensors="pt").input_ids.to(device)
            out = model.generate(input_ids=ids, max_new_tokens=max_new_tokens, do_sample=False,
                                 pad_token_id=tokenizer.eos_token_id)
            return tokenizer.decode(out[0], skip_special_tokens=True)


# --------- FUNZIONE INTEGRABILE NEL FLUSSO ---------
def run_soft_prompting(text: str,
                       device: str = "cuda",
                       embed_model: str = "sentence-transformers/all-MiniLM-L6-v2",
                       llm_name: str = "gpt2",
                       topk: int = 16, mix_entity: int = 8, mix_wd: int = 8,
                       max_new_tokens: int = 120,
                       entity_emb_path="outputs/graph_entity_embs.pt",
                       wd_emb_path="outputs/graph_wikidata_embs.pt",
                       triples_path="outputs/triples_expanded.json",
                       use_verbalization: bool = True,
                       use_instruction_model: bool = False):
    """
    Enhanced soft prompting with graph verbalization option.

    Args:
        text: Question text
        device: Device to use
        embed_model: Sentence embedding model
        llm_name: LLM model name (or Flan-T5 if use_instruction_model=True)
        topk: Top-k retrieval
        mix_entity: Entity mix count
        mix_wd: Wikidata mix count
        max_new_tokens: Max generation length
        entity_emb_path: Path to entity embeddings
        wd_emb_path: Path to wikidata embeddings
        triples_path: Path to expanded triples
        use_verbalization: If True, use text facts instead of soft prompt
        use_instruction_model: If True, use Flan-T5 instead of GPT2

    Returns:
        baseline output, enriched output, retrieved nodes
    """
    dev = torch.device(device if (device=="cuda" and torch.cuda.is_available()) else "cpu")

    # Carica embeddings e mapping
    z_ent, ent_names, z_wd, qids = load_graph_embeddings(entity_emb_path, wd_emb_path, triples_path, device=dev)

    # Load triples for verbalization
    with open(triples_path, "r", encoding="utf-8") as f:
        all_triples = json.load(f)

    # Encoda la domanda nello stesso spazio
    st = SentenceTransformer(embed_model, device=str(dev))
    with torch.no_grad():
        q_vec = st.encode([text], convert_to_tensor=True, device=str(dev))

    # Retrieval top-K
    bank, labels, types = build_retrieval_bank(z_ent.to(dev), ent_names, z_wd.to(dev), qids)
    retrieved = cosine_topk(q_vec, bank, labels, types, topk=topk, mix_entity_wd=(mix_entity, mix_wd))

    retrieved_view = [(lab, typ, float(cos)) for (lab, typ, cos, _v) in retrieved]

    # Choose generation approach
    if use_verbalization:
        # ===== VERBALIZATION APPROACH (Recommended) =====
        print("[INFO] Using graph verbalization approach")

        # Build QID to label mapping
        qid_to_label = {}
        for qid in qids:
            from wikidata_utils import wd_get_label_desc
            label, _ = wd_get_label_desc(qid, "en")
            if label:
                qid_to_label[qid] = label

        # Verbalize facts
        graph_facts = verbalize_with_labels(all_triples, qid_to_label, max_facts=20)

        # Build prompts
        prompt_baseline = f"Question: {text}\nAnswer:"
        prompt_enriched = build_llm_prompt_with_graph(text, graph_facts, use_cot=True)

        # Load appropriate model
        if use_instruction_model:
            # Use Flan-T5 or similar instruction-tuned model
            llm_model_name = "google/flan-t5-large" if llm_name == "gpt2" else llm_name
            tokenizer = AutoTokenizer.from_pretrained(llm_model_name)
            model = AutoModelForSeq2SeqLM.from_pretrained(llm_model_name).to(dev)

            # Generate baseline
            inputs = tokenizer(prompt_baseline, return_tensors="pt").to(dev)
            with torch.no_grad():
                outputs = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
            baseline = tokenizer.decode(outputs[0], skip_special_tokens=True)

            # Generate enriched
            inputs = tokenizer(prompt_enriched, return_tensors="pt", max_length=512, truncation=True).to(dev)
            with torch.no_grad():
                outputs = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
            enriched = tokenizer.decode(outputs[0], skip_special_tokens=True)

        else:
            # Use GPT-2 or similar causal LM
            tokenizer = AutoTokenizer.from_pretrained(llm_name)
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token
            model = AutoModelForCausalLM.from_pretrained(llm_name).to(dev)

            # Generate baseline
            inputs = tokenizer(prompt_baseline, return_tensors="pt").to(dev)
            with torch.no_grad():
                outputs = model.generate(**inputs, max_new_tokens=max_new_tokens,
                                        do_sample=False, pad_token_id=tokenizer.eos_token_id)
            baseline = tokenizer.decode(outputs[0], skip_special_tokens=True)

            # Generate enriched
            inputs = tokenizer(prompt_enriched, return_tensors="pt", max_length=512, truncation=True).to(dev)
            with torch.no_grad():
                outputs = model.generate(**inputs, max_new_tokens=max_new_tokens,
                                        do_sample=False, pad_token_id=tokenizer.eos_token_id)
            enriched = tokenizer.decode(outputs[0], skip_special_tokens=True)

    else:
        # ===== SOFT PROMPT APPROACH (Original) =====
        print("[INFO] Using soft prompt embedding approach")

        tok = AutoTokenizer.from_pretrained(llm_name)
        if tok.pad_token is None and tok.eos_token is not None:
            tok.pad_token = tok.eos_token
        model = AutoModelForCausalLM.from_pretrained(llm_name).to(dev)
        hidden_size = model.get_input_embeddings().weight.shape[1]

        # Initialize projector
        projector = SoftPromptProjector(d_src=bank.shape[1], d_tgt=hidden_size).to(dev)

        # Try to load trained projector if exists
        trained_projector_path = "outputs/trained_projector.pt"
        if os.path.exists(trained_projector_path):
            try:
                projector.load_state_dict(torch.load(trained_projector_path, map_location=dev))
                print(f"[INFO] Loaded trained projector from {trained_projector_path}")
            except Exception as e:
                print(f"[WARN] Could not load trained projector: {e}")
                print("[WARN] Using random initialized projector")
        else:
            print(f"[WARN] No trained projector found at {trained_projector_path}")
            print("[WARN] Using random initialized projector (consider running with --train-projector)")

        soft_embeds = build_soft_prompt_vectors(retrieved, projector, device=str(dev))

        # Genera
        baseline = generate_with_soft_prompt(model, tok, text, soft_embeds=None,
                                             device=str(dev), max_new_tokens=max_new_tokens)
        enriched = generate_with_soft_prompt(model, tok, text, soft_embeds=soft_embeds,
                                             device=str(dev), max_new_tokens=max_new_tokens)

    return baseline, enriched, retrieved_view
