"""Local inference using fine-tuned PCB reasoning model (mlx-lm).

Provides LocalLLMClient as a drop-in alternative to LLMClient that runs
inference locally on Apple Silicon using the SFT/GRPO fine-tuned adapter.

No API key required. Uses the mlx-lm library for native GPU acceleration.

Usage:
    from kicad_agent.llm.local_client import LocalLLMClient

    client = LocalLLMClient()
    response = client.chat([
        {"role": "system", "content": "You are a PCB design expert."},
        {"role": "user", "content": "Analyze this board: 50 components, 30 nets"},
    ])
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class LocalLLMClient:
    """Local mlx-lm inference client using fine-tuned PCB reasoning model.

    Loads the base Qwen model + LoRA adapter trained on PCB reasoning chains.
    Runs entirely locally on Apple Silicon GPU — no API key needed.

    Args:
        model: Base model HuggingFace ID.
        adapter_dir: Directory containing adapters.safetensors + adapter_config.json.
        max_tokens: Maximum generation length.
        temperature: Sampling temperature (0.0 = greedy).
    """

    _HF_REPO = "bretbouchard/kicad-agent-pcb-adapter"

    def __init__(
        self,
        model: str | None = None,
        adapter_dir: str | Path | None = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> None:
        self._model_name = model or os.environ.get(
            "KICAD_LOCAL_MODEL", "Qwen/Qwen2.5-0.5B-Instruct",
        )
        self._adapter_dir = self._resolve_adapter(adapter_dir)
        self._adapter_from_hf = False
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._model = None
        self._tokenizer = None

    def _resolve_adapter(self, adapter_dir: str | Path | None) -> Path:
        """Find adapter directory: explicit > local > HF Hub download."""
        # 1. Explicit path
        if adapter_dir:
            p = Path(adapter_dir)
            if p.exists():
                return p

        # 2. Local training output (GRPO > SFT)
        for local in [
            Path(os.environ.get("KICAD_LOCAL_ADAPTER", "training_output/grpo/iter_2")),
            Path("training_output/grpo/iter_2"),
            Path("training_output/sft"),
        ]:
            if local.exists() and (local / "adapters.safetensors").exists():
                return local

        # 3. Download from HuggingFace Hub
        cache_dir = Path.home() / ".cache" / "kicad-agent" / "adapters"
        grpo_dir = cache_dir / "grpo"
        sft_dir = cache_dir / "sft"

        for adapter_type, target_dir in [("grpo", grpo_dir), ("sft", sft_dir)]:
            if (target_dir / "adapters.safetensors").exists():
                return target_dir

        # Download from HF Hub (prefer GRPO, fall back to SFT)
        try:
            import shutil
            from huggingface_hub import snapshot_download
            downloaded = snapshot_download(
                self._HF_REPO,
                allow_patterns=["grpo/*", "sft/*"],
                cache_dir=str(cache_dir),
            )
            for adapter_type in ["grpo", "sft"]:
                src = Path(downloaded) / adapter_type
                dst = cache_dir / adapter_type
                if src.exists() and (src / "adapters.safetensors").exists():
                    dst.mkdir(parents=True, exist_ok=True)
                    for f in src.iterdir():
                        shutil.copy2(f, dst / f.name)

            if (grpo_dir / "adapters.safetensors").exists():
                self._adapter_from_hf = True
                return grpo_dir
            if (sft_dir / "adapters.safetensors").exists():
                self._adapter_from_hf = True
                return sft_dir
        except Exception:
            pass

        # 4. No adapter found — will run base model
        return Path("training_output/grpo/iter_2")

    def _ensure_loaded(self) -> None:
        """Lazy-load model and tokenizer on first use."""
        if self._model is not None:
            return

        from mlx_lm import load

        adapter_path = str(self._adapter_dir) if self._adapter_dir.exists() else None
        if adapter_path:
            self._model, self._tokenizer = load(self._model_name, adapter_path=adapter_path)
        else:
            self._model, self._tokenizer = load(self._model_name)

    @property
    def model(self) -> str:
        """The model identifier."""
        return self._model_name

    @property
    def adapter_path(self) -> str:
        """Path to the LoRA adapter."""
        return str(self._adapter_dir)

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Generate a response from a list of chat messages.

        Args:
            messages: List of {"role": "system|user|assistant", "content": "..."}.
            **kwargs: Override max_tokens, temperature, etc.

        Returns:
            Generated text response.
        """
        self._ensure_loaded()

        max_tokens = kwargs.get("max_tokens", self._max_tokens)
        temperature = kwargs.get("temperature", self._temperature)

        # Format messages as ChatML prompt
        prompt_parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            prompt_parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
        prompt_parts.append("<|im_start|>assistant\n")
        prompt = "\n".join(prompt_parts)

        from mlx_lm import generate
        import mlx.core as mx

        # Create temperature sampler
        if temperature > 0:
            def sampler(logits):
                return mx.random.categorical(logits * (1.0 / max(temperature, 1e-8)))
        else:
            def sampler(logits):
                return mx.argmax(logits, axis=-1)

        response = generate(
            self._model, self._tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=sampler,
            verbose=False,
        )

        # Extract just the assistant response (strip the prompt prefix)
        assistant_marker = "<|im_start|>assistant\n"
        if assistant_marker in response:
            idx = response.index(assistant_marker) + len(assistant_marker)
            return response[idx:].strip()

        return response.strip()

    def create_message(self, **kwargs: Any) -> Any:
        """API-compatible interface matching LLMClient.create_message().

        Converts Anthropic-style messages format to local inference.

        Args:
            **kwargs: Must include 'messages' list. Other kwargs like 'max_tokens'
                      are passed through. 'system' is prepended as a system message.

        Returns:
            Simple namespace object with .content[0].text matching Anthropic response.
        """
        messages = kwargs.get("messages", [])
        system = kwargs.get("system")
        max_tokens = kwargs.get("max_tokens", self._max_tokens)

        # Build message list
        chat_messages = []
        if system:
            chat_messages.append({"role": "system", "content": system})
        chat_messages.extend(messages)

        response_text = self.chat(chat_messages, max_tokens=max_tokens)

        # Return Anthropic-compatible response structure
        class _Content:
            def __init__(self, text: str):
                self.text = text
                self.type = "text"

        class _Message:
            def __init__(self, text: str):
                self.content = [_Content(text)]
                self.role = "assistant"
                self.model = self_model_name
                self.stop_reason = "end_turn"

        self_model_name = self._model_name
        return _Message(response_text)

    def analyze_board(
        self,
        board_name: str,
        n_components: int,
        n_nets: int,
        n_layers: int,
        width_mm: float,
        height_mm: float,
        source: str = "unknown",
    ) -> str:
        """Generate a PCB board analysis using the fine-tuned model.

        Args:
            board_name: Name of the board.
            n_components: Number of components.
            n_nets: Number of nets.
            n_layers: Number of PCB layers.
            width_mm: Board width in mm.
            height_mm: Board height in mm.
            source: Source/repo URL.

        Returns:
            Structured PCB analysis text.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a PCB design expert specializing in spatial reasoning. "
                    "Analyze boards using coordinate-grounded reasoning with <point x,y> tags. "
                    "Provide structured analysis: observation, component analysis, connectivity, "
                    "spatial analysis, and routing assessment."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Analyze this PCB board:\n"
                    f"Board: {board_name}\n"
                    f"Components: {n_components}, Nets: {n_nets}, Layers: {n_layers}\n"
                    f"Board size: {width_mm:.1f} x {height_mm:.1f} mm\n"
                    f"Source: {source}\n\n"
                    f"Provide a complete spatial reasoning analysis."
                ),
            },
        ]
        return self.chat(messages, max_tokens=1024)

    def assess_routing(
        self,
        board_name: str,
        n_components: int,
        n_nets: int,
        n_traces: int,
        res_score: float,
        quality_label: str,
        density: float,
        via_density: float,
        manhattan_eff: float,
    ) -> str:
        """Generate a routing quality assessment.

        Args:
            board_name: Name of the board.
            n_components: Number of components.
            n_nets: Number of nets.
            n_traces: Number of traces.
            res_score: Routing Elegance Score.
            quality_label: Quality label (excellent/good/fair/poor).
            density: Component density (comp/mm2).
            via_density: Via density (/mm2).
            manhattan_eff: Manhattan efficiency ratio.

        Returns:
            Routing quality assessment text.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a PCB design expert specializing in routing quality assessment."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Assess the routing quality of this PCB:\n"
                    f"Board: {board_name}\n"
                    f"Components: {n_components}, Nets: {n_nets}, Traces: {n_traces}\n"
                    f"RES Score: {res_score:.3f} ({quality_label})\n"
                    f"Density: {density:.3f} comp/mm2, Via density: {via_density:.3f}/mm2\n"
                    f"Manhattan efficiency: {manhattan_eff:.3f}\n\n"
                    f"Evaluate the routing quality and identify strengths and weaknesses."
                ),
            },
        ]
        return self.chat(messages, max_tokens=768)
