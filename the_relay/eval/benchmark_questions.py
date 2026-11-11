"""
The 15 in-depth evaluation questions spanning Attention Is All You Need,
Moshi, Dynamic Chunking (H-Net), and unanswerable edge cases.
"""
from pydantic import BaseModel

class BenchmarkQuestion(BaseModel):
    id: str
    target_paper: str
    question: str
    expected_negative: bool
    ground_truth_key_facts: list[str]
    domain_tags: list[str]

BENCHMARK_QUESTIONS: list[BenchmarkQuestion] = [
    # 1. Attention Is All You Need (1706.03762v7)
    BenchmarkQuestion(
        id="q01_attention_formula",
        target_paper="Attention Is All You Need",
        question="What is the exact mathematical formula for Scaled Dot-Product Attention, and why is the scaling factor 1/sqrt(d_k) used?",
        expected_negative=False,
        ground_truth_key_facts=["softmax(QK^T / sqrt(d_k))V", "counteract large dot products pushing softmax into small gradients"],
        domain_tags=["attention", "math", "transformer"]
    ),
    BenchmarkQuestion(
        id="q02_transformer_dimensions",
        target_paper="Attention Is All You Need",
        question="In the base Transformer model, what are the values of d_model, the number of heads (h), and the dimensions d_k and d_v?",
        expected_negative=False,
        ground_truth_key_facts=["d_model = 512", "h = 8", "d_k = 64", "d_v = 64"],
        domain_tags=["transformer", "hyperparameters"]
    ),
    BenchmarkQuestion(
        id="q03_transformer_bleu",
        target_paper="Attention Is All You Need",
        question="What BLEU score did the big Transformer model achieve on the WMT 2014 English-to-German and English-to-French translation benchmarks?",
        expected_negative=False,
        ground_truth_key_facts=["28.4 BLEU on English-to-German", "41.8 BLEU on English-to-French"],
        domain_tags=["translation", "benchmark"]
    ),
    BenchmarkQuestion(
        id="q04_ffn_layer",
        target_paper="Attention Is All You Need",
        question="How is the Position-wise Feed-Forward Network formulated in Section 3.3, and what is the inner-layer dimensionality d_ff?",
        expected_negative=False,
        ground_truth_key_facts=["max(0, xW_1 + b_1)W_2 + b_2", "d_ff = 2048"],
        domain_tags=["feedforward", "architecture"]
    ),

    # 2. Moshi (2410.00037v1)
    BenchmarkQuestion(
        id="q05_mimi_codec_framerate",
        target_paper="Moshi",
        question="What is the framerate and the number of Residual Vector Quantization (RVQ) codebooks used by the Mimi neural audio codec?",
        expected_negative=False,
        ground_truth_key_facts=["12.5 Hz framerate", "8 codebooks", "1.1 kbps bitrate"],
        domain_tags=["audio", "codec", "mimi"]
    ),
    BenchmarkQuestion(
        id="q06_moshi_latency_budget",
        target_paper="Moshi",
        question="What is the theoretical end-to-end conversational latency of Moshi, and how does the 80ms audio frame stride contribute to it?",
        expected_negative=False,
        ground_truth_key_facts=["160ms theoretical latency", "80ms frame stride", "overlapping context"],
        domain_tags=["latency", "realtime"]
    ),
    BenchmarkQuestion(
        id="q07_moshi_multistream",
        target_paper="Moshi",
        question="How does Moshi interleave user and agent audio streams alongside text tokens in its multi-stream transformer architecture?",
        expected_negative=False,
        ground_truth_key_facts=["temporal alignment", "hierarchical multi-stream", "parallel audio and text tokens"],
        domain_tags=["multistream", "speech_text"]
    ),
    BenchmarkQuestion(
        id="q08_moshi_pretraining_data",
        target_paper="Moshi",
        question="What is the total size of the foundation model and how many tokens/hours was Moshi pretrained on?",
        expected_negative=False,
        ground_truth_key_facts=["7B parameter model (Helena)", "pre-trained on text and speech"],
        domain_tags=["training", "scale"]
    ),

    # 3. Dynamic Chunking / H-Net (2507.07955v2)
    BenchmarkQuestion(
        id="q09_dynamic_chunking_concept",
        target_paper="Dynamic Chunking for End-to-End Hierarchical Sequence Modeling",
        question="How does dynamic chunking in H-Net replace Byte-Pair Encoding (BPE), and what does the model operate on instead?",
        expected_negative=False,
        ground_truth_key_facts=["operates directly on raw bytes", "eliminates tokenizer heuristic", "learned dynamic segmentation boundaries"],
        domain_tags=["hnet", "tokenization", "bytes"]
    ),
    BenchmarkQuestion(
        id="q10_hnet_hierarchy_stages",
        target_paper="Dynamic Chunking for End-to-End Hierarchical Sequence Modeling",
        question="How does a multi-stage H-Net scale compared to single-stage hierarchy and token-based Transformer baselines?",
        expected_negative=False,
        ground_truth_key_facts=["matches token-based Transformers of twice its size", "better scaling with data"],
        domain_tags=["scaling", "hierarchy"]
    ),
    BenchmarkQuestion(
        id="q11_dna_data_efficiency",
        target_paper="Dynamic Chunking for End-to-End Hierarchical Sequence Modeling",
        question="What data efficiency improvement does H-Net achieve over tokenized baselines on DNA sequence modeling and Chinese text?",
        expected_negative=False,
        ground_truth_key_facts=["nearly 4x improvement in data efficiency", "benefits modalities with weak tokenization heuristics"],
        domain_tags=["dna", "efficiency", "chinese"]
    ),
    BenchmarkQuestion(
        id="q12_character_robustness",
        target_paper="Dynamic Chunking for End-to-End Hierarchical Sequence Modeling",
        question="Why does H-Net exhibit superior character-level robustness compared to standard BPE-tokenized models when noisy text or typos are introduced?",
        expected_negative=False,
        ground_truth_key_facts=["subword tokenizers suffer from catastrophic token drift on typos", "byte-level modeling preserves root byte representations"],
        domain_tags=["robustness", "typos"]
    ),

    # 4. Out-of-Scope / Negative Questions (Testing strict refusal without guessing)
    BenchmarkQuestion(
        id="q13_llama3_hardware_infra",
        target_paper="None",
        question="What specific 16,000 H100 GPU cluster networking topology was used to train the Llama-3 405B base model?",
        expected_negative=True,
        ground_truth_key_facts=["The papers do not say"],
        domain_tags=["negative_control", "out_of_scope"]
    ),
    BenchmarkQuestion(
        id="q14_private_dna_cohorts",
        target_paper="None",
        question="What private clinical hospital patient IDs and genomic sequencing cohorts were used to validate Cartesia's medical deployment?",
        expected_negative=True,
        ground_truth_key_facts=["The papers do not say"],
        domain_tags=["negative_control", "out_of_scope"]
    ),
    BenchmarkQuestion(
        id="q15_quantum_attention_speedup",
        target_paper="None",
        question="According to these papers, what quantum annealing adiabatic speedup is observed when computing attention matrices on D-Wave hardware?",
        expected_negative=True,
        ground_truth_key_facts=["The papers do not say"],
        domain_tags=["negative_control", "out_of_scope"]
    )
]

