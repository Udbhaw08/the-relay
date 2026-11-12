"""
CLI testing tool to ask questions directly to The Relay from the terminal.
Usage:
    python scripts/ask.py "What is the formula for Scaled Dot-Product Attention?"
    python scripts/ask.py --source stand-in --setting setting_a "What is Mimi framerate?"
"""
import sys
import argparse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from the_relay.pipeline.orchestrator import RelayPipeline

def main():
    parser = argparse.ArgumentParser(description="Ask questions to The Relay pipeline from the terminal.")
    parser.add_argument("query", nargs="?", default="What is the formula for Scaled Dot-Product Attention in Attention Is All You Need?", help="The technical question to ask.")
    parser.add_argument("--source", default="real", choices=["real", "groq", "stand-in"], help="Model source ('real' / 'groq' for GroqCloud, 'stand-in' for simulator).")
    parser.add_argument("--setting", default="setting_b", choices=["setting_a", "setting_b", "setting_c"], help="Retrieval setting.")
    parser.add_argument("--unanswerable", action="store_true", help="Flag if this question is expected to be unanswerable.")

    args = parser.parse_args()

    print("=" * 75)
    print("THE RELAY: RESEARCH PAPER ASSISTANT (CLI)")
    print("=" * 75)
    print(f"Question:  {args.query}")
    print(f"Source:    {args.source.upper()}")
    print(f"Setting:   {args.setting}")
    print("-" * 75)
    print("Executing 4-Step Pipeline...")

    pipeline = RelayPipeline()
    res = pipeline.run_request(
        query=args.query,
        request_id="cli_test",
        source=args.source,
        retrieval_setting=args.setting,
        expected_negative=args.unanswerable
    )

    print("\n✅ PIPELINE EXECUTION COMPLETED")
    print("-" * 75)
    print(f"Status:          {res.status.upper()}")
    print(f"Grade:           {res.answer_grade}")
    print(f"Steps Executed:  {' -> '.join(res.steps_executed)}")
    print(f"Loop Triggered:  {res.loop_triggered}")
    print(f"First Token:     {res.first_token_ms} ms")
    print(f"Total Latency:   {res.total_ms} ms")
    print(f"Tokens (In/Out): {res.tokens_in} / {res.tokens_out}")
    if res.citations_found:
        print(f"Citations:       {', '.join(res.citations_found)}")
    print("-" * 75)
    print(f"\nANSWER:\n{res.answer}\n")
    print("=" * 75)

if __name__ == "__main__":
    main()

