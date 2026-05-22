"""GRPO Spatial Reasoning Training pipeline.

Phase 9: DeepSeek-style RL training with coordinate-grounded reward signals
on synthetic PCB maze data.

Modules:
    dataset — MazeSample, MazeDataset, generate_dataset()
    generator — parallel generation, adversarial samples
    chains — MazeReasoningChain, chain synthesis from maze samples
    chain_builder — DFS exploration and chain construction
    chain_writer — batch chain writing to JSONL
    reward — RewardSignal, ChainReward, score_chain()
    reward_hacking — anomaly detection, smooth penalties
    reward_model — neural reward model (PyTorch)
    grpo — GRPOTrainer, GRPOConfig
    evaluation — EvalResult, EvaluationHarness
    pipeline — TrainingPipelineConfig, run_pipeline()
"""
