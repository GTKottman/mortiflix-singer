#!/usr/bin/env bash
# Training environment for Mortiflix Singer: DiffSinger (Apache-2.0, pinned) + PyTorch in trainer/.venv.
# Usage: trainer/setup.sh [cpu|cu124|cu126]   (default: cu124 on Linux/Windows with an NVIDIA GPU, else cpu)
set -euo pipefail
cd "$(dirname "$0")/.."
REV=ba031f6f2f969373b49a926cf8b007e9ae48834f
if [ ! -d ref/DiffSinger ]; then git clone https://github.com/openvpi/DiffSinger.git ref/DiffSinger; fi
git -C ref/DiffSinger fetch -q origin "$REV" 2>/dev/null || true
git -C ref/DiffSinger checkout -q "$REV"
# BigVGAN (MIT): only needed to re-export the commercial-clean vocoder (export_bigvgan.py)
BV=7d2b454564a6c7d014227f635b7423881f14bdac
if [ ! -d ref/BigVGAN ]; then git clone https://github.com/NVIDIA/BigVGAN.git ref/BigVGAN; fi
git -C ref/BigVGAN fetch -q origin "$BV" 2>/dev/null || true
git -C ref/BigVGAN checkout -q "$BV"
FLAVOR="${1:-}"
if [ -z "$FLAVOR" ]; then if command -v nvidia-smi >/dev/null; then FLAVOR=cu124; else FLAVOR=cpu; fi; fi
uv venv -q -p 3.11 trainer/.venv
uv pip install -q -p trainer/.venv/bin/python torch torchaudio --index-url "https://download.pytorch.org/whl/$FLAVOR"
uv pip install -q -p trainer/.venv/bin/python -r ref/DiffSinger/requirements.txt soundfile soxr g2p_en mido onnxruntime transformers "setuptools<81"
trainer/.venv/bin/python -c "import nltk; [nltk.download(p, quiet=True) for p in ('averaged_perceptron_tagger_eng', 'cmudict')]"
echo "training environment ready ($FLAVOR)"
