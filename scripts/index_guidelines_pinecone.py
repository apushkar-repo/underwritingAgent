#!/usr/bin/env python3
"""Create/update the Pinecone guideline index using OpenAI embeddings."""

from pathlib import Path

from underwriting_agent.integrations import build_integrations_from_env


ROOT = Path(__file__).resolve().parents[1]


def main():
    guideline_path = ROOT / "data" / "underwriting_guidelines.jsonl"
    bundle = build_integrations_from_env(guideline_path, dotenv_path=ROOT / ".env")
    if bundle.guideline_store is None:
        raise SystemExit("Set GUIDELINE_VECTOR_BACKEND=pinecone in .env")
    print("Pinecone guideline index is ready.")


if __name__ == "__main__":
    main()
