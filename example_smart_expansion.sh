#!/bin/bash
# Example: Smart Graph Expansion Usage

echo "=========================================="
echo "ESEMPIO 1: Query Base (senza smart expansion)"
echo "=========================================="
python main.py \
  --text "Chi è il coniuge di Obama?" \
  --use-ensemble \
  --use-reranking \
  --use-verbalization \
  --use-instruction-model \
  --device cuda

echo ""
echo ""
echo "=========================================="
echo "ESEMPIO 2: Query con Smart Expansion (2-hop)"
echo "=========================================="
python main.py \
  --text "Allarga il grafo su Wikidata per trovare le connessioni familiari di Obama" \
  --use-ensemble \
  --use-decomposition \
  --use-reranking \
  --use-verbalization \
  --use-instruction-model \
  --use-smart-expansion \
  --use-smart-verbalization \
  --max-expansion-depth 2 \
  --max-total-qids 100 \
  --device cuda

echo ""
echo ""
echo "=========================================="
echo "ESEMPIO 3: Query Multi-Hop (3-hop)"
echo "=========================================="
python main.py \
  --text "Chi è il padre del coniuge del presidente nato a Hawaii?" \
  --use-ensemble \
  --use-decomposition \
  --use-reranking \
  --use-verbalization \
  --use-instruction-model \
  --use-smart-expansion \
  --use-smart-verbalization \
  --max-expansion-depth 3 \
  --max-total-qids 150 \
  --device cuda

echo ""
echo ""
echo "=========================================="
echo "ESEMPIO 4: Espansione Comprehensiva"
echo "=========================================="
python main.py \
  --text "Trova tutte le informazioni biografiche disponibili su Barack Obama e la sua famiglia" \
  --use-ensemble \
  --use-decomposition \
  --use-reranking \
  --use-verbalization \
  --use-instruction-model \
  --use-smart-expansion \
  --use-smart-verbalization \
  --max-expansion-depth 2 \
  --max-total-qids 200 \
  --device cuda

echo ""
echo ""
echo "=========================================="
echo "ESEMPIO 5: Query con Focus Politico"
echo "=========================================="
python main.py \
  --text "Espandi le connessioni politiche di Obama con altri presidenti USA" \
  --use-ensemble \
  --use-decomposition \
  --use-reranking \
  --use-verbalization \
  --use-instruction-model \
  --use-smart-expansion \
  --use-smart-verbalization \
  --max-expansion-depth 2 \
  --max-total-qids 100 \
  --device cuda
