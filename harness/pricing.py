"""Token usage accounting and cost estimation."""
from dataclasses import dataclass

# USD per million tokens.
PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
}

_FALLBACK_MODEL = "claude-sonnet-5-5"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read + other.cache_read,
            self.cache_write + other.cache_write,
        )

    @classmethod
    def from_api(cls, u) -> "Usage":
        return cls(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )


def cost_usd(model: str, usage: Usage) -> float:
    p = PRICES.get(model, PRICES[_FALLBACK_MODEL])
    total = (
        usage.input_tokens * p["input"]
        + usage.output_tokens * p["output"]
        + usage.cache_read * p["cache_read"]
        + usage.cache_write * p["cache_write"]
    )
    return total / 1_000_000
