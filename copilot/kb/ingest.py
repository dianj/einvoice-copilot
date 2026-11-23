"""Build or refresh the on-disk vector index: python -m copilot.kb.ingest [--rebuild] [--include-test]

The app also syncs the index at first use; this command does it ahead of time.
"""
import argparse

from copilot import config
from copilot.kb.embedder import make_embedder
from copilot.kb.retriever import all_chunks
from copilot.kb.store import VectorIndex


def main(argv=None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rebuild", action="store_true", help="empty the index first")
    parser.add_argument("--include-test", action="store_true", help="also index corpus/test-only")
    args = parser.parse_args(argv)
    index = VectorIndex(config.CHROMA_PATH, make_embedder(), args.include_test, reset=args.rebuild)
    counts = index.sync(all_chunks(args.include_test))
    print(f"index {config.CHROMA_PATH}: {counts}")
    return counts


if __name__ == "__main__":
    main()
