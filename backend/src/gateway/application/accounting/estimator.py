"""Pre-call usage estimation for budget reservation (ADR-0016 Slice 9).

No tokenizer exists anywhere in this project (out of scope - see ADR-0017/evidence log), so this
is a deliberately crude, deterministic, character-based heuristic - the same kind of estimate
ADR-0004 always intended ("estimation uses max_tokens x price as an upper bound... conservative so
we never under-reserve"). It must never be read as an accurate token count: it exists only to
produce a reservation that is very unlikely to be exceeded by the real call, not to predict cost.

Deliberately over-, not under-, estimates: ``completion_tokens`` here assumes the response could be
as large as the prompt, whereas ``InMemoryProviderClient``'s own (separate) usage-synthesis
heuristic assumes a response half the prompt's size. A reservation built from this estimate is
expected to exceed the fake client's actual usage in tests - that is the intended "reserve
conservatively, settle to the smaller real number" shape, not a bug.
"""

from __future__ import annotations

from gateway.application.ports.providers import InferenceRequest, ProviderUsage

_CHARS_PER_TOKEN = 4


def estimate_usage(request: InferenceRequest) -> ProviderUsage:
    """Conservative pre-call token estimate. Never zero: an empty payload still reserves for at
    least one token of each kind, since the accounting layer never treats an actual response as
    free either."""
    payload_chars = len(str(dict(request.payload)))
    prompt_tokens = max(1, payload_chars // _CHARS_PER_TOKEN)
    completion_tokens = prompt_tokens
    return ProviderUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
