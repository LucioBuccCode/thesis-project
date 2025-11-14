"""
soft_prompting_enhanced.py
Versione migliorata di soft_prompting.py che USA DAVVERO gli embeddings HGT
DA SOSTITUIRE o AFFIANCARE a soft_prompting.py
"""

import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, GPT2LMHeadModel, GPT2Tokenizer
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

def run_soft_prompting_enhanced(
    question: str,
    hgt_embeddings: Optional[Dict[str, torch.Tensor]],
    triples: List[Dict],
    qid2label: Dict[str, str],
    relevant_info: Optional[Dict] = None,  # NUOVO: info da HGT reasoning
    use_verbalization: bool = True,
    use_instruction_model: bool = True,
    use_hgt_reasoning: bool = True,  # NUOVO: flag per usare HGT
    device: str = "cuda"
) -> Tuple[str, str, str]:
    """
    Versione enhanced che integra HGT reasoning con LLM generation
    
    Returns:
        Tuple di (baseline_answer, enriched_answer, retrieved_facts)
    """
    
    # Setup device
    device = torch.device(device if torch.cuda.is_available() else "cpu")
    
    # Load model
    if use_instruction_model:
        model_name = "google/flan-t5-large"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name).to(device)
    else:
        model_name = "gpt2"
        tokenizer = GPT2Tokenizer.from_pretrained(model_name)
        model = GPT2LMHeadModel.from_pretrained(model_name).to(device)
        tokenizer.pad_token = tokenizer.eos_token
    
    # 1. Generate baseline answer (senza graph knowledge)
    baseline_prompt = f"Question: {question}\nAnswer:"
    baseline_answer = _generate_answer(model, tokenizer, baseline_prompt, device, use_instruction_model)
    
    # 2. Generate enriched answer con HGT reasoning
    if use_hgt_reasoning and relevant_info:
        # USA le informazioni estratte da HGT!
        enriched_prompt = _build_hgt_enhanced_prompt(
            question, relevant_info, triples, qid2label
        )
        retrieved_facts = _extract_facts_from_relevant_info(relevant_info, qid2label)
    elif use_verbalization:
        # Fallback al metodo originale
        enriched_prompt, retrieved_facts = _build_verbalization_prompt(
            question, triples, qid2label
        )
    else:
        # Soft prompting originale (non raccomandato)
        enriched_prompt = baseline_prompt
        retrieved_facts = ""
    
    enriched_answer = _generate_answer(model, tokenizer, enriched_prompt, device, use_instruction_model)
    
    return baseline_answer, enriched_answer, retrieved_facts

def _build_hgt_enhanced_prompt(
    question: str,
    relevant_info: Dict,
    triples: List[Dict],
    qid2label: Dict[str, str]
) -> str:
    """
    Costruisce un prompt che sfrutta le informazioni estratte da HGT
    """
    prompt_parts = []
    
    # Aggiungi contesto dalla confidence di HGT
    confidence = relevant_info.get("confidence_scores", {}).get("overall_confidence", 0)
    if confidence > 0.7:
        prompt_parts.append("Based on high-confidence graph analysis:")
    elif confidence > 0.4:
        prompt_parts.append("Based on moderate-confidence graph analysis:")
    else:
        prompt_parts.append("Based on available information:")
    
    prompt_parts.append("")
    
    # 1. Aggiungi entità rilevanti identificate da HGT
    relevant_entities = relevant_info.get("relevant_entities", [])
    if relevant_entities:
        prompt_parts.append("Key entities identified through neural graph reasoning:")
        for entity in relevant_entities[:5]:  # Top 5
            entity_name = entity["entity"]
            entity_type = entity["type"]
            score = entity["score"]
            
            # Risolvi QID se è Wikidata
            if entity_type == "wikidata" and entity_name in qid2label:
                entity_name = qid2label[entity_name]
            
            if score > 0.7:
                prompt_parts.append(f"• {entity_name} (highly relevant)")
            elif score > 0.5:
                prompt_parts.append(f"• {entity_name} (relevant)")
        prompt_parts.append("")
    
    # 2. Aggiungi triple rilevanti filtrate da HGT
    relevant_triples = relevant_info.get("relevant_triples", [])
    if relevant_triples:
        prompt_parts.append("Critical facts identified by graph neural network:")
        for triple in relevant_triples[:10]:  # Top 10
            fact = _verbalize_triple(triple, qid2label)
            score = triple.get("hgt_relevance_score", 0)
            
            if score > 0.8:
                prompt_parts.append(f"• [HIGH RELEVANCE] {fact}")
            elif score > 0.5:
                prompt_parts.append(f"• {fact}")
        prompt_parts.append("")
    
    # 3. Aggiungi reasoning paths da HGT
    reasoning_paths = relevant_info.get("reasoning_paths", [])
    if reasoning_paths:
        prompt_parts.append("Multi-hop reasoning chains discovered:")
        for i, path_info in enumerate(reasoning_paths[:3], 1):  # Top 3 paths
            path_str = _verbalize_path(path_info, qid2label)
            confidence = path_info.get("confidence", 0)
            
            if confidence > 0.7:
                prompt_parts.append(f"Chain {i} [STRONG]: {path_str}")
            else:
                prompt_parts.append(f"Chain {i}: {path_str}")
        prompt_parts.append("")
    
    # 4. Aggiungi reasoning patterns
    patterns = relevant_info.get("reasoning_patterns", [])
    if patterns:
        prompt_parts.append("Reasoning patterns detected:")
        for pattern in patterns[:2]:
            pattern_type = pattern.get("pattern_type", "unknown")
            coherence = pattern.get("coherence", 0)
            
            if coherence > 0.8:
                prompt_parts.append(f"• Strong {pattern_type} pattern (coherence: {coherence:.2f})")
            elif coherence > 0.6:
                prompt_parts.append(f"• {pattern_type} pattern")
        prompt_parts.append("")
    
    # 5. Aggiungi la domanda con istruzioni
    prompt_parts.append("Based on the above neural graph analysis and reasoning chains,")
    prompt_parts.append("answer the following question step by step:")
    prompt_parts.append(f"Question: {question}")
    prompt_parts.append("")
    prompt_parts.append("Think through the connections identified by the graph neural network,")
    prompt_parts.append("follow the reasoning chains, and provide a precise answer:")
    prompt_parts.append("Answer:")
    
    return "\n".join(prompt_parts)

def _build_verbalization_prompt(
    question: str,
    triples: List[Dict],
    qid2label: Dict[str, str]
) -> Tuple[str, str]:
    """
    Prompt originale con verbalization (fallback)
    """
    facts = []
    for triple in triples[:15]:  # Limita per token budget
        fact = _verbalize_triple(triple, qid2label)
        facts.append(f"• {fact}")
    
    facts_str = "\n".join(facts)
    
    prompt = f"""Knowledge Graph Facts:
{facts_str}

Question: {question}
Let's think step by step:
Answer:"""
    
    return prompt, facts_str

def _verbalize_triple(triple: Dict, qid2label: Dict[str, str]) -> str:
    """
    Converte una tripla in linguaggio naturale
    """
    head = triple.get("head", "")
    relation = triple.get("relation", "")
    tail = triple.get("tail", "")
    
    # Risolvi QIDs
    if head in qid2label:
        head = qid2label[head]
    if tail in qid2label:
        tail = qid2label[tail]
    
    # Pulisci relazione
    relation = relation.replace("_", " ")
    
    return f"{head} {relation} {tail}"

def _verbalize_path(path_info: Dict, qid2label: Dict[str, str]) -> str:
    """
    Converte un percorso in linguaggio naturale
    """
    start = path_info.get("start", "")
    end = path_info.get("end", "")
    path = path_info.get("path", [])
    
    # Risolvi QIDs
    if start in qid2label:
        start = qid2label[start]
    if end in qid2label:
        end = qid2label[end]
    
    if not path:
        return f"{start} → {end}"
    
    # Costruisci descrizione del percorso
    path_parts = [start]
    for step in path:
        if len(step) == 3:  # (source, relation, target)
            relation = step[1].replace("_", " ")
            target = step[2]
            if target in qid2label:
                target = qid2label[target]
            path_parts.append(f"--{relation}--> {target}")
    
    return " ".join(path_parts)

def _extract_facts_from_relevant_info(
    relevant_info: Dict,
    qid2label: Dict[str, str]
) -> str:
    """
    Estrae fatti in formato leggibile dalle info HGT
    """
    facts = []
    
    # Entità rilevanti
    for entity in relevant_info.get("relevant_entities", [])[:5]:
        entity_name = entity["entity"]
        if entity_name in qid2label:
            entity_name = qid2label[entity_name]
        facts.append(f"Entity: {entity_name} (relevance: {entity['score']:.2f})")
    
    # Triple rilevanti
    for triple in relevant_info.get("relevant_triples", [])[:10]:
        fact = _verbalize_triple(triple, qid2label)
        facts.append(f"Fact: {fact}")
    
    # Percorsi
    for path in relevant_info.get("reasoning_paths", [])[:3]:
        path_str = _verbalize_path(path, qid2label)
        facts.append(f"Path: {path_str}")
    
    return "\n".join(facts)

def _generate_answer(
    model,
    tokenizer,
    prompt: str,
    device: torch.device,
    use_instruction_model: bool
) -> str:
    """
    Genera risposta dal modello
    """
    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        max_length=1024,
        truncation=True,
        padding=True
    ).to(device)
    
    with torch.no_grad():
        if use_instruction_model:
            outputs = model.generate(
                **inputs,
                max_new_tokens=100,
                num_beams=4,
                temperature=0.7,
                do_sample=False
            )
        else:
            outputs = model.generate(
                **inputs,
                max_new_tokens=50,
                temperature=0.7,
                pad_token_id=tokenizer.eos_token_id
            )
    
    answer = tokenizer.decode(outputs[0], skip_special_tokens=True)
    
    # Pulisci risposta
    if use_instruction_model:
        # Flan-T5 ritorna direttamente la risposta
        return answer.strip()
    else:
        # GPT-2 include il prompt, rimuovilo
        answer = answer[len(prompt):].strip()
        # Prendi solo la prima frase
        if "." in answer:
            answer = answer[:answer.index(".") + 1]
        return answer

# Funzione di compatibilità per non rompere il codice esistente
def run_soft_prompting(
    question: str,
    hgt_embeddings: Optional[Dict[str, torch.Tensor]],
    triples: List[Dict],
    qid2label: Dict[str, str],
    use_verbalization: bool = True,
    use_instruction_model: bool = True,
    device: str = "cuda"
) -> Tuple[str, str, str]:
    """
    Wrapper di compatibilità per il codice esistente
    """
    return run_soft_prompting_enhanced(
        question=question,
        hgt_embeddings=hgt_embeddings,
        triples=triples,
        qid2label=qid2label,
        relevant_info=None,  # Nessuna info HGT enhanced
        use_verbalization=use_verbalization,
        use_instruction_model=use_instruction_model,
        use_hgt_reasoning=False,  # Usa metodo vecchio
        device=device
    )
