"""Request-scoped payer identity and conservative provider cost estimates."""
import json
import math
import os
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from .commerce import Commerce


@dataclass
class Payer:
    commerce: Commerce
    mode: str = "byok"
    account_id: str | None = None
    job_id: str | None = None
    step: str = "extraction"
    credits: int = 2
    should_stop: Callable[[], bool] | None = None


class GenerationStopped(Exception):
    """Cooperative stop before dispatch; never interrupts a billed HTTP request."""


payer_context: ContextVar[Payer | None] = ContextVar("castle_payer", default=None)


def cost_for(model: str, usage: dict) -> int:
    # USD/million tokens == micro-USD/token. Peak rates; override when provider prices change.
    pro = model == "deepseek-v4-pro"
    prefix = "CASTLE_PRO" if pro else "CASTLE_FLASH"
    input_rate = Decimal(os.getenv(prefix+"_INPUT_RATE", "1.32" if pro else "0.30"))
    cached_rate = Decimal(os.getenv(prefix+"_CACHED_RATE", "0.044" if pro else "0.006"))
    output_rate = Decimal(os.getenv(prefix+"_OUTPUT_RATE", "3.96" if pro else "1.20"))
    inputs = max(0, int(usage.get("prompt_tokens", 0)))
    cached = min(inputs, max(0, int(usage.get("prompt_cache_hit_tokens", 0))))
    outputs = max(0, int(usage.get("completion_tokens", 0)))
    return math.ceil((inputs-cached)*input_rate + cached*cached_rate + outputs*output_rate)


def upper_cost(payload: dict) -> int:
    # UTF-8 byte count conservatively bounds text token count, plus framing headroom.
    size = len(json.dumps(payload["messages"], ensure_ascii=False).encode()) + 1024
    if size > 180_000:
        raise ValueError("input too large")
    return cost_for(payload["model"], {"prompt_tokens": size, "completion_tokens": payload["max_tokens"]})
