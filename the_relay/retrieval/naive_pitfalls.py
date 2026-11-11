"""
Analysis and demonstrations of how the 3-paper library misleads naive retrievers.
Addresses the assignment heading: 'How this library will mislead a naive retriever'.
"""
from dataclasses import dataclass

@dataclass
class PitfallCase:
    pitfall_id: str
    title: str
    mechanism: str
    example_question: str
    naive_retriever_failure: str
    resilient_remedy: str

MISLEADING_CASES = [
    PitfallCase(
        pitfall_id="pitfall_1_attention_overload",
        title="Lexical Collision on 'Attention' & 'Causal Masking'",
        mechanism=(
            "Both 'Attention Is All You Need' and 'Moshi' heavily feature 'attention', "
            "'multi-head attention', and 'causal masking'. A naive retriever searching for causal attention "
            "scores highest on Vaswani et al.'s Section 3.2.3 because of raw keyword density, even when the user "
            "is inquiring about real-time conversational streaming and acoustic channel synchronization."
        ),
        example_question="How does the causal attention mask synchronize the parallel user and agent speech channels in real-time?",
        naive_retriever_failure=(
            "Retrieves Vaswani et al. Section 3.2.3 (Scaled Dot-Product / Causal Masking in Transformer decoder), "
            "attempting to answer speech synchronization using autoregressive machine translation masking, "
            "completely missing Moshi's multi-stream temporal interleaving."
        ),
        resilient_remedy=(
            "Hybrid retrieval with Section/Title semantic boosting and entity routing (detecting speech/dialogue "
            "intents to boost Moshi 2410.00037v1)."
        )
    ),
    PitfallCase(
        pitfall_id="pitfall_2_chunking_clash",
        title="Term Collision on 'Chunking' (H-Net Dynamic Chunking vs Audio Frame Chunks)",
        mechanism=(
            "The term 'chunking' is heavily overloaded across the library: H-Net (2507.07955) defines "
            "'dynamic chunking' as learned byte-level boundary segmentation to abolish BPE tokenizers; "
            "Moshi (2410.00037) discusses acoustic frame chunking (12.5 Hz / 80ms chunks); and generic NLP "
            "discusses text-chunking. A naive query on 'chunk size' matches acoustic frame windows."
        ),
        example_question="What is the primary advantage of dynamic chunking over subword tokenizers for DNA and Chinese text?",
        naive_retriever_failure=(
            "A naive keyword retriever matches passages in Moshi discussing 80ms audio chunk quantization or "
            "general text segmentation, giving an answer about speech frame latency instead of H-Net's byte hierarchy."
        ),
        resilient_remedy=(
            "Intent parsing that disambiguates sequence modeling vs audio frame processing, cross-matching "
            "target vocabulary (e.g. 'DNA', 'Chinese', 'BPE', 'H-Net')."
        )
    ),
    PitfallCase(
        pitfall_id="pitfall_3_vocabulary_mismatch",
        title="Vocabulary Mismatch on Speech Codec vs Text Tokenization ('Tokens')",
        mechanism=(
            "Engineers frequently ask how raw inputs become discrete tokens. In Vaswani et al., tokens are "
            "subwords (BPE/WordPiece). In Moshi, speech is tokenized via the 'Mimi' neural codec (RQ-VAE, 8 codebooks). "
            "In H-Net, tokenization is eliminated entirely in favor of raw bytes. A naive query on 'tokenization method' "
            "always defaults to Transformer BPE."
        ),
        example_question="What neural codec is used to discretize continuous 24kHz audio into multi-stream tokens at low latency?",
        naive_retriever_failure=(
            "BM25 matches 'tokens' and 'discretize' against Attention Is All You Need's shared vocabulary embeddings "
            "(37,000 subwords), hallucinating that the Transformer vocabulary is used for speech."
        ),
        resilient_remedy=(
            "Dense semantic re-ranking with domain synonym expansion ('neural codec' -> 'Mimi', 'RQ-VAE', 'Residual Vector Quantization')."
        )
    )
]

