#!/usr/bin/env python3
"""
Deep analysis script for multi-hop question failures.

Analyzes the question: "What college did the President who attended Minneapolis High School go to?"

Traces every phase and identifies failure points.
"""

import json
import os
import sys
import torch
from typing import List, Dict, Any

# Make outputs more verbose
os.makedirs("outputs/debug", exist_ok=True)


def save_debug(filename: str, data: Any):
    """Save debug data to file."""
    path = f"outputs/debug/{filename}"
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(data, (dict, list)):
            json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            f.write(str(data))
    print(f"[DEBUG] Saved to {path}")


def analyze_triple_extraction(question: str):
    """Phase 1: Triple Extraction Analysis"""
    print("\n" + "="*80)
    print("PHASE 1: TRIPLE EXTRACTION ANALYSIS")
    print("="*80)

    from relation_extraction import extract_triples, decompose_question

    # Analyze question decomposition
    print("\n[1.1] Question Decomposition")
    sub_questions = decompose_question(question)
    print(f"Original question: {question}")
    print(f"\nDecomposed into {len(sub_questions)} sub-questions:")
    for i, sq in enumerate(sub_questions, 1):
        print(f"  {i}. {sq}")

    save_debug("1_decomposed_questions.json", {
        "original": question,
        "sub_questions": sub_questions
    })

    # Extract with decomposition
    print("\n[1.2] Triple Extraction (with decomposition)")
    triples_with_decomp = extract_triples(
        question,
        device="cpu",
        use_ensemble=True,
        use_decomposition=True
    )

    print(f"\nExtracted {len(triples_with_decomp)} triples:")
    for t in triples_with_decomp:
        print(f"  - {t['head']} | {t['relation']} | {t['tail']}")

    save_debug("1_triples_extracted.json", triples_with_decomp)

    # Check if critical relations are captured
    print("\n[1.3] Critical Relation Check")

    critical_relations = {
        "attended_school": False,  # President -> Minneapolis High School
        "education": False,  # President -> College
        "position": False  # Person -> President
    }

    for triple in triples_with_decomp:
        rel_lower = triple['relation'].lower()
        if 'attend' in rel_lower or 'school' in rel_lower:
            critical_relations['attended_school'] = True
        if 'education' in rel_lower or 'college' in rel_lower or 'university' in rel_lower:
            critical_relations['education'] = True
        if 'president' in rel_lower or 'position' in rel_lower:
            critical_relations['position'] = True

    print("Critical relations captured:")
    for rel, captured in critical_relations.items():
        status = "✓" if captured else "✗"
        print(f"  {status} {rel}")

    # Check if entities are captured
    print("\n[1.4] Entity Coverage Check")
    entities = set()
    for t in triples_with_decomp:
        entities.add(t['head'])
        entities.add(t['tail'])

    print(f"Entities extracted: {len(entities)}")
    print("Looking for key entities:")
    key_entities = {
        "Minneapolis High School": any("minneapolis" in e.lower() for e in entities),
        "President": any("president" in e.lower() for e in entities),
        "College/University": any("college" in e.lower() or "university" in e.lower() for e in entities)
    }

    for entity, found in key_entities.items():
        status = "✓" if found else "✗"
        print(f"  {status} {entity}")

    save_debug("1_analysis.json", {
        "triple_count": len(triples_with_decomp),
        "critical_relations": critical_relations,
        "key_entities": key_entities,
        "all_entities": sorted(list(entities))
    })

    return triples_with_decomp


def analyze_entity_linking(triples: List[Dict], question: str):
    """Phase 2: Entity Linking Analysis"""
    print("\n" + "="*80)
    print("PHASE 2: ENTITY LINKING ANALYSIS")
    print("="*80)

    from kg_build import link_entities_to_qids

    # Extract entities
    entities = sorted(set([t["head"] for t in triples] + [t["tail"] for t in triples]))
    print(f"\n[2.1] Linking {len(entities)} entities to Wikidata")

    # Link with reranking
    e2q_with_rerank = link_entities_to_qids(
        entities,
        cache_path="outputs/debug/entity2qid_reranked.json",
        question_context=question,
        use_reranking=True
    )

    # Link without reranking for comparison
    e2q_no_rerank = link_entities_to_qids(
        entities,
        cache_path="outputs/debug/entity2qid_no_rerank.json",
        question_context=question,
        use_reranking=False
    )

    # Analyze linking quality
    print("\n[2.2] Entity Linking Results")

    linking_analysis = []
    for entity in entities:
        reranked = e2q_with_rerank.get(entity)
        no_rerank = e2q_no_rerank.get(entity)

        analysis = {
            "entity": entity,
            "reranked_qid": reranked['qid'] if reranked else None,
            "reranked_label": reranked['label'] if reranked else None,
            "no_rerank_qid": no_rerank['qid'] if no_rerank else None,
            "no_rerank_label": no_rerank['label'] if no_rerank else None,
            "same": (reranked['qid'] if reranked else None) == (no_rerank['qid'] if no_rerank else None)
        }

        linking_analysis.append(analysis)

        status = "✓" if reranked else "✗"
        print(f"  {status} '{entity}'")
        if reranked:
            print(f"      -> {reranked['qid']} ({reranked['label']})")
            if reranked.get('desc'):
                print(f"         {reranked['desc'][:80]}...")
        else:
            print(f"      -> NOT LINKED")

    save_debug("2_entity_linking.json", {
        "with_reranking": e2q_with_rerank,
        "without_reranking": e2q_no_rerank,
        "analysis": linking_analysis
    })

    # Check if we got the right entities
    print("\n[2.3] Critical Entity Linking Check")

    # Check if key entities were linked correctly
    issues = []

    for entity, qid_info in e2q_with_rerank.items():
        if "minneapolis" in entity.lower():
            if qid_info:
                print(f"  Minneapolis entity: {entity}")
                print(f"    Linked to: {qid_info['qid']} ({qid_info['label']})")
                # Should be Q967503 (Minneapolis Public Schools) or a specific high school
                if "high school" not in qid_info['label'].lower():
                    issues.append(f"'{entity}' linked to '{qid_info['label']}' - may not be the school")
            else:
                issues.append(f"'{entity}' not linked to Wikidata")

        if "president" in entity.lower():
            if qid_info:
                print(f"  President entity: {entity}")
                print(f"    Linked to: {qid_info['qid']} ({qid_info['label']})")
            else:
                issues.append(f"'{entity}' not linked to Wikidata")

    if issues:
        print("\n  Issues found:")
        for issue in issues:
            print(f"    ✗ {issue}")
    else:
        print("  ✓ No obvious issues detected")

    return e2q_with_rerank


def analyze_wikidata_expansion(e2q: Dict, question: str):
    """Phase 3: Wikidata Expansion Analysis"""
    print("\n" + "="*80)
    print("PHASE 3: WIKIDATA EXPANSION ANALYSIS")
    print("="*80)

    from wikidata_utils import expand_with_wikidata_qids, wd_get_label_desc

    # Get QIDs
    qids = [row["qid"] for row in e2q.values() if row and row.get("qid")]
    print(f"\n[3.1] Expanding {len(qids)} QIDs")

    # Properties we'll expand
    props = [
        "spouse", "country of citizenship", "place of birth",
        "instance of", "occupation", "position held",
        "member of", "educated at", "alma mater",  # Added education properties
        "capital", "continent", "shares border with"
    ]

    print(f"Using properties: {', '.join(props)}")

    # Expand
    expanded_edges = expand_with_wikidata_qids(
        qids,
        prop_keys=props,
        prop_lang="en",
        max_edges_per_qid=15,
        preferred_only=False
    )

    print(f"\n[3.2] Expansion Results")
    print(f"  Total edges: {len(expanded_edges)}")

    # Group by property
    prop_counts = {}
    for h, p, t in expanded_edges:
        prop_counts[p] = prop_counts.get(p, 0) + 1

    print("\n  Edges by property:")
    for prop, count in sorted(prop_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"    {prop}: {count}")

    # Analyze if we have education-related edges
    print("\n[3.3] Education Edge Analysis")
    education_edges = []
    for h, p, t in expanded_edges:
        if 'educat' in p.lower() or 'alma' in p.lower() or 'P69' in p:
            h_label, _ = wd_get_label_desc(h, "en")
            t_label, _ = wd_get_label_desc(t, "en")
            education_edges.append({
                "head": h,
                "head_label": h_label,
                "property": p,
                "tail": t,
                "tail_label": t_label
            })
            print(f"  ✓ {h_label} --[{p}]--> {t_label}")

    if not education_edges:
        print("  ✗ No education-related edges found!")
        print("  This is likely why multi-hop reasoning fails!")

    save_debug("3_expansion.json", {
        "qids_expanded": qids,
        "total_edges": len(expanded_edges),
        "property_counts": prop_counts,
        "education_edges": education_edges,
        "all_edges": [
            {
                "head": h,
                "property": p,
                "tail": t
            }
            for h, p, t in expanded_edges
        ]
    })

    return expanded_edges


def analyze_graph_construction(triples: List[Dict], question: str):
    """Phase 4: Graph Construction Analysis"""
    print("\n" + "="*80)
    print("PHASE 4: GRAPH CONSTRUCTION ANALYSIS")
    print("="*80)

    from kg_build import build_enriched_hetero_graph

    print("\n[4.1] Building heterogeneous graph")

    data, meta = build_enriched_hetero_graph(
        triples,
        embed_model="sentence-transformers/all-MiniLM-L6-v2",
        device="cpu",
        wd_props=[
            "spouse", "country of citizenship", "place of birth",
            "instance of", "occupation", "position held",
            "member of", "educated at", "alma mater",
            "capital", "continent", "shares border with"
        ],
        wd_lang="en",
        wd_max_edges_per_qid=15,
        wd_preferred_only=False,
        question_context=question,
        use_reranking=True
    )

    print(f"\n[4.2] Graph Statistics")
    print(f"  Node types: {list(data.node_types)}")
    print(f"  Edge types: {len(data.edge_types)}")
    print(f"  Entity nodes: {data['entity'].x.shape[0]}")
    if 'wikidata' in data.node_types:
        print(f"  Wikidata nodes: {data['wikidata'].x.shape[0]}")

    # Analyze edge types
    print(f"\n[4.3] Edge Type Analysis")
    for edge_type in data.edge_types:
        edge_index = data[edge_type].edge_index
        if edge_index is not None:
            print(f"  {edge_type}: {edge_index.shape[1]} edges")

    # Check for multi-hop paths
    print("\n[4.4] Multi-hop Path Analysis")
    print("  Checking if graph contains necessary paths...")

    # We need a path like:
    # President -> attended -> Minneapolis High School
    # President -> educated at -> College
    # Or: Person -> position -> President
    #     Person -> educated at -> College
    #     Person -> attended -> High School

    # Load expanded triples to check
    if os.path.exists("outputs/triples_expanded.json"):
        with open("outputs/triples_expanded.json", "r") as f:
            expanded = json.load(f)

        # Find paths involving education
        education_paths = []
        for triple in expanded:
            if 'educat' in triple['relation'].lower() or 'alma' in triple['relation'].lower():
                education_paths.append(triple)

        print(f"  Found {len(education_paths)} education-related edges in graph")
        for ep in education_paths[:10]:
            print(f"    {ep['head']} --[{ep['relation']}]--> {ep['tail']}")

    save_debug("4_graph_stats.json", {
        "meta": meta,
        "node_types": list(data.node_types),
        "edge_types": [str(et) for et in data.edge_types],
        "entity_count": data['entity'].x.shape[0],
        "wikidata_count": data['wikidata'].x.shape[0] if 'wikidata' in data.node_types else 0
    })

    return data, meta


def analyze_retrieval(question: str):
    """Phase 5: Retrieval Analysis"""
    print("\n" + "="*80)
    print("PHASE 5: RETRIEVAL & VERBALIZATION ANALYSIS")
    print("="*80)

    from soft_prompting import run_soft_prompting

    print("\n[5.1] Running soft prompting / retrieval")

    baseline, enriched, retrieved = run_soft_prompting(
        text=question,
        device="cpu",
        embed_model="sentence-transformers/all-MiniLM-L6-v2",
        llm_name="google/flan-t5-large",
        topk=25,
        mix_entity=12,
        mix_wd=13,
        max_new_tokens=200,
        use_verbalization=True,
        use_instruction_model=True
    )

    print(f"\n[5.2] Retrieved Nodes")
    print(f"  Total: {len(retrieved)}")
    print("\n  Top 20 retrieved nodes:")
    for i, (label, ntype, score) in enumerate(retrieved[:20], 1):
        print(f"    {i:2d}. [{ntype:8s}] {label:50s} | {score:.3f}")

    # Check if retrieved nodes contain education information
    print("\n[5.3] Education Content in Retrieved Nodes")
    education_nodes = []
    for label, ntype, score in retrieved:
        if any(kw in label.lower() for kw in ['college', 'university', 'educat', 'school', 'alma']):
            education_nodes.append((label, ntype, score))

    print(f"  Found {len(education_nodes)} education-related nodes")
    for label, ntype, score in education_nodes[:10]:
        print(f"    [{ntype}] {label} | {score:.3f}")

    # Load verbalized facts
    print("\n[5.4] Verbalized Facts Analysis")
    if os.path.exists("outputs/soft_prompt_facts.txt"):
        with open("outputs/soft_prompt_facts.txt", "r") as f:
            facts = f.read()

        print(f"  Total characters: {len(facts)}")
        print("\n  Verbalized facts (first 1000 chars):")
        print("  " + "-"*70)
        print("  " + facts[:1000].replace("\n", "\n  "))
        print("  " + "-"*70)

        # Check if facts contain answer
        if 'college' in facts.lower() or 'university' in facts.lower():
            print("\n  ✓ Facts contain college/university mentions")
        else:
            print("\n  ✗ Facts do NOT contain college/university mentions")

        if 'minneapolis' in facts.lower():
            print("  ✓ Facts mention Minneapolis")
        else:
            print("  ✗ Facts do NOT mention Minneapolis")

    print("\n[5.5] Answer Generation")
    print(f"\n  Baseline answer:")
    print(f"    {baseline}")
    print(f"\n  Enriched answer (with KG):")
    print(f"    {enriched}")

    save_debug("5_retrieval.json", {
        "baseline_answer": baseline,
        "enriched_answer": enriched,
        "retrieved_nodes": [
            {"label": label, "type": ntype, "score": score}
            for label, ntype, score in retrieved
        ],
        "education_nodes": [
            {"label": label, "type": ntype, "score": score}
            for label, ntype, score in education_nodes
        ]
    })

    return baseline, enriched, retrieved


def generate_analysis_report():
    """Generate final analysis report"""
    print("\n" + "="*80)
    print("GENERATING ANALYSIS REPORT")
    print("="*80)

    report = []
    report.append("# MULTI-HOP QA FAILURE ANALYSIS")
    report.append(f"\nQuestion: What college did the President who attended Minneapolis High School go to?")
    report.append("\n## Summary of Findings\n")

    # Load all debug files
    debug_files = os.listdir("outputs/debug")

    # Analyze each phase
    if "1_analysis.json" in debug_files:
        with open("outputs/debug/1_analysis.json") as f:
            phase1 = json.load(f)

        report.append("### Phase 1: Triple Extraction")
        report.append(f"- Extracted {phase1['triple_count']} triples")
        report.append("- Critical relations:")
        for rel, found in phase1['critical_relations'].items():
            status = "✓" if found else "✗"
            report.append(f"  {status} {rel}")
        report.append("")

    if "2_entity_linking.json" in debug_files:
        with open("outputs/debug/2_entity_linking.json") as f:
            phase2 = json.load(f)

        report.append("### Phase 2: Entity Linking")
        linked = sum(1 for v in phase2['with_reranking'].values() if v)
        total = len(phase2['with_reranking'])
        report.append(f"- Linked {linked}/{total} entities to Wikidata")
        report.append("")

    if "3_expansion.json" in debug_files:
        with open("outputs/debug/3_expansion.json") as f:
            phase3 = json.load(f)

        report.append("### Phase 3: Wikidata Expansion")
        report.append(f"- Total edges: {phase3['total_edges']}")
        report.append(f"- Education edges: {len(phase3['education_edges'])}")
        if phase3['education_edges']:
            report.append("- Education edges found:")
            for edge in phase3['education_edges'][:5]:
                report.append(f"  - {edge['head_label']} → {edge['tail_label']}")
        report.append("")

    if "5_retrieval.json" in debug_files:
        with open("outputs/debug/5_retrieval.json") as f:
            phase5 = json.load(f)

        report.append("### Phase 5: Retrieval & Answer")
        report.append(f"- Retrieved {len(phase5['retrieved_nodes'])} nodes")
        report.append(f"- Education-related nodes: {len(phase5['education_nodes'])}")
        report.append(f"\nBaseline answer: {phase5['baseline_answer']}")
        report.append(f"Enriched answer: {phase5['enriched_answer']}")
        report.append("")

    report_text = "\n".join(report)

    save_debug("ANALYSIS_REPORT.md", report_text)
    print("\n" + report_text)

    return report_text


def main():
    """Main analysis pipeline"""
    question = "What college did the President who attended Minneapolis High School go to?"

    print("="*80)
    print("DEEP MULTI-HOP QUESTION ANALYSIS")
    print("="*80)
    print(f"\nQuestion: {question}")
    print(f"\nThis is a 2-hop question requiring:")
    print("  1. Find which President attended Minneapolis High School")
    print("  2. Find which college that President attended")
    print("\n" + "="*80)

    try:
        # Phase 1: Triple Extraction
        triples = analyze_triple_extraction(question)

        # Phase 2: Entity Linking
        e2q = analyze_entity_linking(triples, question)

        # Phase 3: Wikidata Expansion
        expanded = analyze_wikidata_expansion(e2q, question)

        # Phase 4: Graph Construction
        graph, meta = analyze_graph_construction(triples, question)

        # Phase 5: Retrieval & Answer
        baseline, enriched, retrieved = analyze_retrieval(question)

        # Generate report
        generate_analysis_report()

        print("\n" + "="*80)
        print("ANALYSIS COMPLETE")
        print("="*80)
        print("\nAll debug files saved to outputs/debug/")
        print("\nKey findings:")
        print("  1. Check outputs/debug/1_analysis.json for triple extraction issues")
        print("  2. Check outputs/debug/2_entity_linking.json for disambiguation errors")
        print("  3. Check outputs/debug/3_expansion.json for missing Wikidata edges")
        print("  4. Check outputs/debug/5_retrieval.json for retrieval failures")
        print("  5. Read outputs/debug/ANALYSIS_REPORT.md for full report")

    except Exception as e:
        print(f"\n[ERROR] Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
