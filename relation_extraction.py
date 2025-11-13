
from typing import List, Dict, Tuple
import os, re, torch
from transformers import (
    T5Tokenizer, T5ForConditionalGeneration,
    AutoTokenizer, AutoModelForSeq2SeqLM,
    pipeline
)

# Default: best English candidate
DEFAULT_MODEL = "pat-jj/text2triple-flan-t5"
REBEL_MODEL = "Babelscape/rebel-large"

def _parse_text2triple(output_text: str) -> List[Dict[str, str]]:
    """
    Strict parser for pat-jj/text2triple-flan-t5 format:
      (S> SUBJECT| P> RELATION| O> OBJECT), (S> ...), ...
    No swaps, no normalization. If it doesn't match, it's ignored.
    """
    # collapse whitespace
    txt = re.sub(r"\s+", " ", output_text.strip())
    triples = []
    # Split by '),'
    parts = [p.strip() for p in re.split(r"\)\s*,\s*", txt) if p.strip()]
    for p in parts:
        # ensure leading '(' and trailing ')' (after split the last may keep it)
        if not p.startswith("("):
            p = "(" + p
        if not p.endswith(")"):
            p = p + ")"
        m = re.match(r"^\(\s*S>\s*(.*?)\s*\|\s*P>\s*(.*?)\s*\|\s*O>\s*(.*?)\s*\)$", p, flags=re.IGNORECASE)
        if m:
            head, rel, tail = m.group(1), m.group(2), m.group(3)
            if head and rel and tail:
                triples.append({"head": head, "relation": rel, "tail": tail})
    # de-duplicate mechanically
    seen, out = set(), []
    for t in triples:
        k = (t["head"], t["relation"], t["tail"])
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out

def _parse_text2triple_relaxed(output_text: str) -> List[Dict[str, str]]:
    """
    Relaxed parser that tries multiple patterns to extract triples.
    Fallback for when strict parser fails.
    """
    triples = []
    txt = re.sub(r"\s+", " ", output_text.strip())

    # Pattern 1: Standard format (S> X | P> Y | O> Z)
    pattern1 = r"S>\s*([^|]+?)\s*\|\s*P>\s*([^|]+?)\s*\|\s*O>\s*([^|)]+)"
    matches1 = re.findall(pattern1, txt, flags=re.IGNORECASE)
    for h, r, t in matches1:
        triples.append({"head": h.strip(), "relation": r.strip(), "tail": t.strip()})

    # Pattern 2: Simple format (HEAD, RELATION, TAIL)
    pattern2 = r"\(([^,]+),\s*([^,]+),\s*([^)]+)\)"
    matches2 = re.findall(pattern2, txt)
    for h, r, t in matches2:
        if h.strip() and r.strip() and t.strip():
            triples.append({"head": h.strip(), "relation": r.strip(), "tail": t.strip()})

    # Pattern 3: <triplet> format from REBEL
    pattern3 = r"<triplet>\s*([^<]+?)\s*<subj>\s*([^<]+?)\s*<obj>"
    matches3 = re.findall(pattern3, txt, flags=re.IGNORECASE)
    for h, r in matches3:
        # In REBEL, format is: subj, relation, obj
        parts = h.split()
        if len(parts) >= 2:
            triples.append({"head": parts[0].strip(), "relation": r.strip(), "tail": " ".join(parts[1:]).strip()})

    # Deduplicate
    seen, out = set(), []
    for t in triples:
        k = (t["head"], t["relation"], t["tail"])
        if k not in seen and t["head"] and t["relation"] and t["tail"]:
            seen.add(k)
            out.append(t)

    return out

def _parse_rebel_output(text: str) -> List[Dict[str, str]]:
    """
    Parse REBEL model output format:
    <triplet> subject <subj> relation <obj> object
    """
    triples = []
    # REBEL uses special tokens to delimit triplets
    triplet_pattern = r'<triplet>\s*([^<]+?)\s*<subj>\s*([^<]+?)\s*<obj>\s*([^<]+?)(?=<triplet>|$)'
    matches = re.findall(triplet_pattern, text, flags=re.DOTALL)

    for subj, rel, obj in matches:
        subj = subj.strip()
        rel = rel.strip()
        obj = obj.strip()
        if subj and rel and obj:
            triples.append({"head": subj, "relation": rel, "tail": obj})

    # Deduplicate
    seen, out = set(), []
    for t in triples:
        k = (t["head"], t["relation"], t["tail"])
        if k not in seen:
            seen.add(k)
            out.append(t)

    return out

def decompose_question(text: str) -> List[str]:
    """
    Enhanced question decomposition for complex multihop questions.
    Extracts sub-questions targeting intermediate entities and relations.
    """
    sub_questions = [text]  # Always include original
    text_lower = text.lower()

    # Pattern 1: "Who is the X of the Y that Z?"
    # Example: "Who is the spouse of the president born in Hawaii?"
    pattern1 = r"who\s+is\s+the\s+(\w+)\s+of\s+the\s+(\w+)\s+(.*?)[\?]?"
    match1 = re.search(pattern1, text_lower)
    if match1:
        relation1 = match1.group(1)
        entity_type = match1.group(2)
        constraint = match1.group(3)

        # Focus on finding the intermediate entity
        if constraint:
            sub_questions.append(f"What {entity_type} {constraint}?")
            sub_questions.append(f"Who {constraint}?")

        # Focus on the final relation
        sub_questions.append(f"Who is the {entity_type}?")
        sub_questions.append(f"{entity_type} has {relation1}")

    # Pattern 2: "When did the X that Y do Z?"
    # Example: "When did the team that led by Giuseppe Marotta win the champions league?"
    pattern2 = r"(when|where)\s+did\s+the\s+(\w+)\s+that\s+(.*?)\s+(win|achieve|do|get)\s+(.*?)[\?]?"
    match2 = re.search(pattern2, text_lower)
    if match2:
        wh = match2.group(1)
        entity_type = match2.group(2)
        constraint = match2.group(3)
        action = match2.group(4)
        obj = match2.group(5)

        # Find the entity satisfying constraint
        sub_questions.append(f"What {entity_type} {constraint}?")
        sub_questions.append(f"Which {entity_type} {constraint}?")
        # Find when/where action happened
        sub_questions.append(f"{wh} did {action} {obj}?")
        # Extract relation from constraint
        sub_questions.append(f"{entity_type} {constraint}")

    # Pattern 3: "Which X has Y and is Z?"
    # Example: "Which country has Mohamed Morsi in a government post and is the location of the Giza Pyramids?"
    pattern3 = r"which\s+(\w+)\s+(.*?)\s+and\s+(.*?)[\?]?"
    match3 = re.search(pattern3, text_lower)
    if match3:
        entity_type = match3.group(1)
        constraint1 = match3.group(2)
        constraint2 = match3.group(3)

        # Split into two simpler questions
        sub_questions.append(f"Which {entity_type} {constraint1}?")
        sub_questions.append(f"Which {entity_type} {constraint2}?")
        # Extract key entities
        sub_questions.append(f"{entity_type} {constraint1}")
        sub_questions.append(f"{entity_type} {constraint2}")

    # Pattern 4: "The X that contains Y had what Z?"
    # Example: "The country that contains Balochistan, Pakistan had what President in 1980?"
    pattern4 = r"the\s+(\w+)\s+that\s+(contains|includes|has)\s+(.*?)\s+(?:had|has)\s+what\s+(\w+)"
    match4 = re.search(pattern4, text_lower)
    if match4:
        entity_type = match4.group(1)
        relation = match4.group(2)
        obj = match4.group(3)
        target = match4.group(4)

        # Find entity containing object
        sub_questions.append(f"Which {entity_type} {relation} {obj}?")
        sub_questions.append(f"What {entity_type} has {obj}?")
        # Find the target relation
        sub_questions.append(f"{entity_type} has {target}")
        sub_questions.append(f"What is the {target}?")

    # Pattern 5: "Which X whose Y is Z borders/relates to W?"
    # Example: "Which country whose religious organization is led by the Ukrainian Orthodox Church borders Slovakia?"
    pattern5 = r"which\s+(\w+)\s+whose\s+(.*?)\s+is\s+(.*?)\s+(borders|relates|connects)\s+(.*?)[\?]?"
    match5 = re.search(pattern5, text_lower)
    if match5:
        entity_type = match5.group(1)
        property_path = match5.group(2)
        property_value = match5.group(3)
        relation = match5.group(4)
        target = match5.group(5)

        # Find entity with property
        sub_questions.append(f"Which {entity_type} {property_path} {property_value}?")
        # Find entities related to target
        sub_questions.append(f"Which {entity_type} {relation} {target}?")
        # Extract property and target separately
        sub_questions.append(f"{property_path} is {property_value}")
        sub_questions.append(f"{entity_type} {relation} {target}")

    # Pattern 6: Extract named entities directly
    # Find capitalized phrases (likely named entities)
    import re
    capitalized = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
    for entity in capitalized:
        if len(entity.split()) >= 2:  # Multi-word entities
            sub_questions.append(f"What is {entity}?")
            sub_questions.append(f"{entity}")

    # Deduplicate while preserving order
    seen = set()
    unique_questions = []
    for q in sub_questions:
        q_lower = q.lower().strip()
        if q_lower not in seen:
            seen.add(q_lower)
            unique_questions.append(q)

    print(f"[INFO] Decomposed question into {len(unique_questions)} variants")
    return unique_questions

def _extract_with_rebel(text: str, device: str = "cpu") -> List[Dict[str, str]]:
    """Extract triples using REBEL model."""
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    try:
        tokenizer = AutoTokenizer.from_pretrained(REBEL_MODEL)
        model = AutoModelForSeq2SeqLM.from_pretrained(REBEL_MODEL)

        if device == "cuda" and torch.cuda.is_available():
            model = model.to("cuda")

        # REBEL expects special format
        inputs = tokenizer(text, return_tensors="pt", max_length=512, truncation=True)
        if device == "cuda":
            inputs = {k: v.to("cuda") for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_length=512,
                num_beams=3,
                num_return_sequences=1,
            )

        decoded = tokenizer.decode(outputs[0], skip_special_tokens=False)

        # Save REBEL output
        with open("outputs/rebel_raw.txt", "w", encoding="utf-8") as f:
            f.write(decoded)

        return _parse_rebel_output(decoded)
    except Exception as e:
        print(f"[WARN] REBEL extraction failed: {e}")
        return []

def extract_triples(
    text: str,
    model_name: str = DEFAULT_MODEL,
    device: str = "auto",
    use_ensemble: bool = True,
    use_decomposition: bool = True,
) -> List[Dict[str, str]]:
    """
    Enhanced triple extraction with multi-model ensemble and question decomposition.

    Args:
        text: Input question or text
        model_name: Primary model (default: Flan-T5)
        device: "auto", "cpu", or "cuda"
        use_ensemble: If True, combine Flan-T5 + REBEL outputs
        use_decomposition: If True, decompose complex questions

    Returns:
        List of triples with deduplication
    """
    os.makedirs("outputs", exist_ok=True)
    dev = 0 if (device in ("auto","cuda") and torch.cuda.is_available()) else -1
    device_str = "cuda" if dev != -1 else "cpu"

    all_triples = []

    # Step 1: Question decomposition (optional)
    texts_to_process = [text]
    if use_decomposition:
        sub_questions = decompose_question(text)
        print(f"[INFO] Decomposed into {len(sub_questions)} sub-questions")
        texts_to_process = sub_questions

    # Step 2: Extract from each text with primary model
    for txt in texts_to_process:
        tokenizer = T5Tokenizer.from_pretrained(model_name)
        try:
            model = T5ForConditionalGeneration.from_pretrained(
                model_name,
                device_map="auto" if dev != -1 else None,
                torch_dtype=(torch.bfloat16 if dev != -1 else torch.float32)
            )
        except Exception:
            model = T5ForConditionalGeneration.from_pretrained(model_name)
            if dev != -1:
                model = model.to("cuda")

        inputs = tokenizer(
            txt,
            max_length=512,
            padding="max_length",
            truncation=True,
            return_tensors="pt"
        )
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

        # Try strict parser first
        triples = _parse_text2triple(out_text)

        # Fallback to relaxed parser if strict fails
        if len(triples) == 0:
            print(f"[INFO] Strict parser found 0 triples, trying relaxed parser...")
            triples = _parse_text2triple_relaxed(out_text)

        all_triples.extend(triples)

        # Clean up model to save memory for ensemble
        del model, tokenizer
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # Step 3: Ensemble with REBEL (if enabled)
    if use_ensemble:
        print("[INFO] Running REBEL ensemble...")
        rebel_triples = _extract_with_rebel(text, device=device_str)
        print(f"[INFO] REBEL found {len(rebel_triples)} triples")
        all_triples.extend(rebel_triples)

    # Step 4: Deduplicate and filter
    seen = set()
    unique_triples = []
    for t in all_triples:
        # Normalize for comparison (case-insensitive)
        key = (t["head"].lower().strip(), t["relation"].lower().strip(), t["tail"].lower().strip())
        if key not in seen and all([t["head"], t["relation"], t["tail"]]):
            seen.add(key)
            # Keep original case
            unique_triples.append(t)

    # Save all outputs
    with open("outputs/text2triple_raw.txt", "w", encoding="utf-8") as f:
        f.write(f"Total triples extracted: {len(unique_triples)}\n")
        f.write(f"Ensemble: {use_ensemble}, Decomposition: {use_decomposition}\n\n")
        for t in unique_triples:
            f.write(f"{t['head']} | {t['relation']} | {t['tail']}\n")

    print(f"[INFO] Final: {len(unique_triples)} unique triples")
    return unique_triples
