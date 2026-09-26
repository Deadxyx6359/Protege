"""Training LoRA adapters (E4), in a process and a Python of their own.

Nothing here is imported by Akira's own process. `_trainer.py` is run by the
separate training environment (`models/train/env`), which holds PyTorch and
Hugging Face's libraries. Those libraries include a model downloader, which is
why they are kept out of Akira's own Python altogether, and why the trainer
installs Akira's network guard and forces every library offline before it
imports any of them. `verify_offline.py` holds both rules.

`lora_gguf.py` writes a trained adapter in the form llama.cpp loads, and needs
only NumPy.
"""
