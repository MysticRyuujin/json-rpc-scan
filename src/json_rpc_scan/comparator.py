"""Semantic response comparator for JSON-RPC responses.

Answers a boolean question: "are these two responses semantically equivalent?"
This is separate from `DiffComputer` in `diff.py`, which produces a structural
diff for reporting — the comparator is the *gate* deciding whether to invoke
the reporter at all.

The comparator always applies `normalize.ALWAYS_ON` normalizers (spec-safe),
plus any opt-in normalizers declared per runner. Error-vs-success mismatch is
surfaced as its own outcome: today `RPCClient.call` catches HTTP errors into
`RPCResponse(response={}, error=...)`, so two different 500s compare equal
without this distinction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from json_rpc_scan.normalize import ALWAYS_ON, Normalizer, apply_all


@dataclass
class ComparisonResult:
    """Outcome of comparing two normalized responses.

    `equal=False` is the "save a diff" gate. `one_errored` and `both_errored`
    are for callers that want to route error-vs-success diffs differently in
    their reporting.
    """

    equal: bool
    one_errored: bool = False
    both_errored: bool = False
    # The post-normalization responses. Runners pass these to DiffReporter so
    # the persisted diff files reflect what the comparator actually compared.
    normalized1: dict[str, Any] = field(default_factory=dict)
    normalized2: dict[str, Any] = field(default_factory=dict)


class ResponseComparator:
    """Compare two JSON-RPC responses after applying normalizers.

    Always applies `ALWAYS_ON` normalizers. Additional opt-in normalizers can
    be passed by the caller — a runner typically declares these as a class-var
    and passes them to the comparator it builds.
    """

    def __init__(self, extra_normalizers: list[Normalizer] | None = None) -> None:
        self._normalizers: list[Normalizer] = [*ALWAYS_ON, *(extra_normalizers or [])]

    def equal(
        self,
        response1: dict[str, Any],
        response2: dict[str, Any],
    ) -> ComparisonResult:
        """Compare two responses, returning a structured result."""
        n1 = apply_all(response1, self._normalizers)
        n2 = apply_all(response2, self._normalizers)

        err1 = _is_error(n1)
        err2 = _is_error(n2)

        # Transport-level errors (network failure, timeout, exhausted 5xx
        # retries) never represent a real agreement between clients — no
        # RPC call actually completed. Flag them as a diff even when the
        # transport error messages match, so a user running against two
        # unreachable endpoints doesn't see a misleading "0 diffs".
        if is_transport_error(n1) or is_transport_error(n2):
            return ComparisonResult(
                equal=False,
                one_errored=err1 != err2,
                both_errored=err1 and err2,
                normalized1=n1,
                normalized2=n2,
            )

        if err1 != err2:
            return ComparisonResult(
                equal=False,
                one_errored=True,
                normalized1=n1,
                normalized2=n2,
            )

        if err1 and err2:
            return ComparisonResult(
                equal=n1.get("error") == n2.get("error"),
                both_errored=True,
                normalized1=n1,
                normalized2=n2,
            )

        return ComparisonResult(
            equal=n1 == n2,
            normalized1=n1,
            normalized2=n2,
        )


def _is_error(response: dict[str, Any]) -> bool:
    """Return True if the response carries a JSON-RPC `error` object."""
    return "error" in response


def is_transport_error(response: dict[str, Any]) -> bool:
    """Return True if the error in this response is a synthetic transport
    error (network failure, 5xx-after-retries) injected by
    `RPCClient._call_with_retry`. Distinguished from genuine RPC errors by
    the ``transport: True`` marker on the error object. Used by both the
    comparator (gate) and DiffComputer (reporter) to force a diff even
    when both sides match — transport failures are infrastructure problems,
    never semantic agreements."""
    err = response.get("error")
    return isinstance(err, dict) and err.get("transport") is True
