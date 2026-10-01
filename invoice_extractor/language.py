"""Local language detection: a free, independent second opinion next to the LLM's own answer."""

import re
import threading

from langdetect import DetectorFactory, LangDetectException, detect_langs

DetectorFactory.seed = 0  # langdetect samples randomly; a fixed seed makes runs reproducible
# langdetect loads its profiles lazily and seeds the global RNG on every call, so concurrent
# workers can get different answers. The detected language is part of the prompt (and so of the
# cache key), which makes that a reproducibility bug, not just noise.
_lock = threading.Lock()


def detect_language(text: str) -> tuple[str | None, float]:
    # Bills are mostly digits, amounts and codes; detect on the words only.
    words = re.sub(r"[\d\W_]+", " ", text)
    try:
        with _lock:
            best = detect_langs(words)[0]
    except LangDetectException:
        return None, 0.0
    return best.lang.split("-")[0], round(best.prob, 2)
