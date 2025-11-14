#!/usr/bin/env python3
"""
Script semplice per testare il sistema QA su dev_simple.json
"""

import json
import subprocess
import csv
import sys
from typing import List, Dict, Tuple


def read_dev_simple(filepath: str, max_questions: int = None) -> List[Dict]:
    """Legge dev_simple.json e restituisce lista di domande."""
    questions_data = []

    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            if max_questions and len(questions_data) >= max_questions:
                break

            if not line.strip():
                continue

            try:
                data = json.loads(line)
                questions_data.append({
                    'id': data.get('id', f'q_{line_num}'),
                    'question': data.get('question', ''),
                    'answers': [ans.get('text', '') for ans in data.get('answers', [])]
                })
            except:
                continue

    return questions_data


def run_qa_pipeline(question: str) -> Tuple[str, str]:
    """Esegue main_refactored.py e restituisce (baseline, enriched)."""
    cmd = [
        sys.executable,
        "main_refactored.py",
        "--text", question,
        "--device", "cpu"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=300
        )

        output = result.stdout + result.stderr

        # Estrai baseline
        baseline = ""
        if '[BASELINE ANSWER]' in output:
            idx = output.find('[BASELINE ANSWER]')
            section = output[idx:idx+500]
            if '[ENRICHED' in section:
                baseline = section.split('[ENRICHED')[0].replace('[BASELINE ANSWER]', '').strip()
            else:
                baseline = section.replace('[BASELINE ANSWER]', '').strip()[:200]

        # Estrai enriched
        enriched = ""
        if 'ENRICHED ANSWER' in output:
            idx = output.find('ENRICHED ANSWER')
            section = output[idx:idx+500]
            if '[STATISTICS]' in section:
                enriched = section.split('[STATISTICS]')[0].strip()
            else:
                enriched = section[:200].strip()
            enriched = enriched.replace('[ENRICHED ANSWER (with Knowledge Graph)]', '').strip()
            enriched = enriched.replace('ENRICHED ANSWER (with Knowledge Graph)', '').strip()

        return baseline, enriched

    except Exception as e:
        print(f"[ERROR] {e}")
        return "", ""


def test_and_save_csv(input_file: str, output_csv: str, from_row :int, to_row: int = 50):
    """Legge domande, testa pipeline, salva in CSV."""

    print(f"Lettura {input_file}...")
    questions = read_dev_simple(input_file, to_row)
    print(f"Trovate {to_row-from_row} domande\n")

    # Apri CSV per scrittura
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, delimiter=';',fieldnames=[
            'id', 'question', 'expected_answers', 'baseline_answer', 'enriched_answer'
        ])
        writer.writeheader()

        # Processa ogni domanda
        for i, q in enumerate(questions[from_row:], 1):
            print(f"[{i}/{to_row-from_row}] {q['id']}")

            # Esegui pipeline
            baseline, enriched = run_qa_pipeline(q['question'])

            # Scrivi in CSV
            # Scrivi in CSV
            row = {
                'id': q['id'],
                'question': q['question'],
                'expected_answers': ' | '.join(q['answers']),
                'baseline_answer': baseline,
                'enriched_answer': enriched
            }
            writer.writerow(row)
            f.flush()  # Forza scrittura immediata

            print(f"  Expected: {q['answers']}")
            print(f"  Baseline: {baseline[:60]}...")
            print(f"  Enriched: {enriched[:60]}...")
            print(f"  ✓ Scritto in CSV\n")

    print(f"Risultati salvati in {output_csv}")


# Esegui test
if __name__ == "__main__":
    test_and_save_csv(
        input_file="dev_simple.json",
        output_csv="results.csv",
        from_row=101,
        to_row=200# Cambia qui il numero di domande
    )
