"""cth_flex: OpenAI Flex-tier client with capacity-aware retry, safe billing and cost accounting."""
from .batch import BatchSummary, CheckpointBusy, run_batch
from .cache import ResponseCache
from .client import AsyncFlexClient, Event, FlexClient, flex_request
from .cost import Rates, Usage, cost_usd, reservation_usd, usage_from_response
from .errors import classify, outcome_of
from .exceptions import (AttemptFailed, Cancelled, Deferred, ErrorInfo, FlexError, IncompleteResponse, Kind, NotSent, Stopped,
                         TierMismatch, UncertainOutcome, UnrecordedResponse)
from .ledger import SpendLedger
from .policy import RetryPolicy

__version__ = "0.1.5"

__all__ = [
    "AttemptFailed", "AsyncFlexClient", "Cancelled", "BatchSummary", "CheckpointBusy", "Deferred", "ErrorInfo", "Event", "FlexClient", "FlexError",
    "IncompleteResponse", "Kind", "NotSent", "Rates", "ResponseCache", "RetryPolicy", "SpendLedger", "Stopped", "TierMismatch",
    "UncertainOutcome", "UnrecordedResponse", "Usage", "classify", "cost_usd", "flex_request", "outcome_of", "reservation_usd", "run_batch",
    "usage_from_response",
]
