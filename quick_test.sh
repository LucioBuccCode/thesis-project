#!/bin/bash
# Quick test script for testing single questions

set -e

QUESTION="${1:-Which country has Mohamed Morsi in a government post and is the location of the Giza Pyramids?}"

echo "=================================="
echo "QUICK TEST"
echo "=================================="
echo "Question: $QUESTION"
echo "=================================="
echo ""

python3 main_refactored.py \
  --text "$QUESTION" \
  --device auto \
  --no-cache

echo ""
echo "=================================="
echo "Test completed!"
echo "=================================="
