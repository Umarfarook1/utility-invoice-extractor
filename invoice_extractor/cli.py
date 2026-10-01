"""Command line entry point: python -m invoice_extractor samples/invoices"""

import argparse
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from .ingest import find_documents
from .llm import CachedExtractor, FallbackExtractor, GeminiExtractor, OpenAIExtractor
from .pipeline import CSV_COLUMNS, InvoiceResult, process_file

# A ladder, tried in order: free tiers allow ~20 requests per model per day and new models are
# often overloaded, so one model alone is a single point of failure.
DEFAULT_MODELS = {
    "gemini": "gemini-3.6-flash,gemini-3.5-flash,gemini-3.8-flash,gemini-3.7-flash,gemini-3.5-flash-lite",
    "openai": "gpt-5-mini",
}
ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Extract structured data from utility invoices with an LLM.")
    parser.add_argument("inputs", nargs="*", type=Path, default=[ROOT / "samples" / "invoices"],
                        help="Invoice files or folders (PDF, TXT, MD).")
    parser.add_argument("--out", type=Path, default=ROOT / "output", help="Output folder.")
    parser.add_argument("--provider", choices=sorted(DEFAULT_MODELS), default=os.getenv("LLM_PROVIDER", "gemini"))
    parser.add_argument("--model", default=os.getenv("LLM_MODEL"),
                        help="Model, or a comma-separated fallback ladder. Defaults: %s" % DEFAULT_MODELS)
    parser.add_argument("--cache", type=Path, default=ROOT / "cache", help="LLM response cache folder.")
    parser.add_argument("--offline", action="store_true", help="Use cached LLM answers only (no API key needed).")
    parser.add_argument("--workers", type=int, default=2, help="Parallel documents (free tiers rate-limit).")
    args = parser.parse_args(argv)
    models = (args.model or DEFAULT_MODELS[args.provider]).split(",")

    live = not args.offline and _has_key(args.provider)
    extractor = FallbackExtractor([
        CachedExtractor(_live_extractor(args.provider, m) if live else None, m, args.cache) for m in models
    ])
    print(f"provider={args.provider} models={models} mode={'live+cache' if live else 'offline (cache only)'}")

    files = find_documents(args.inputs)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda p: process_file(p, extractor), files))

    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(results, args.out / "invoices.csv")
    with open(args.out / "extractions.jsonl", "w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result.audit_record(), ensure_ascii=False) + "\n")
    print_summary(results)
    print(f"\nWrote {args.out / 'invoices.csv'} and {args.out / 'extractions.jsonl'}")
    return 0


def _has_key(provider: str) -> bool:
    return bool(os.getenv("OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY"))


def _live_extractor(provider: str, model: str):
    return OpenAIExtractor(model) if provider == "openai" else GeminiExtractor(model)


def write_csv(results: list[InvoiceResult], path: Path) -> None:
    # utf-8-sig so Excel opens accents and CJK vendor names correctly
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for result in results:
            writer.writerows(result.rows)


def print_summary(results: list[InvoiceResult]) -> None:
    print(f"\n{'file':<46} {'lang':<5} {'rows':>4} {'conf':>5}  review")
    tokens_in = tokens_out = 0
    for r in results:
        conf = min((row["confidence"] or 0.0) for row in r.rows)
        review = "yes" if any(row["needs_review"] for row in r.rows) else "-"
        lang = r.rows[0].get("language") or "?"
        print(f"{r.source_file[:46]:<46} {lang:<5} {len(r.rows):>4} {conf:>5.2f}  {review}")
        if r.llm and not r.llm.cached:
            tokens_in, tokens_out = tokens_in + r.llm.input_tokens, tokens_out + r.llm.output_tokens
    if tokens_in:
        print(f"\nlive tokens: {tokens_in:,} in / {tokens_out:,} out")


if __name__ == "__main__":
    raise SystemExit(main())
