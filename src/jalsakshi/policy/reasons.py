"""Plain-language reasons (English + simple Hindi) for every policy denial.

Keys are the ``@id`` annotations in ``policies/jalsakshi.cedar``. The console and the IVR show
these strings as-is, so keep them short and free of jargon.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final, NamedTuple


class PolicyId(StrEnum):
    """The ``@id`` of each forbid rule, in the order they appear in the policy file."""

    CONSENT_REQUIRED = "consent-required"
    CALLING_HOURS = "calling-hours"
    ONE_CALL_PER_DAY = "one-call-per-day"
    VERIFY_NEEDS_QUORUM = "verify-needs-quorum"
    NO_HOUSEHOLD_VIEW_FOR_DEPT = "no-household-view-for-dept"
    STALE_DATA = "stale-data"


ENGINE_ERROR_ID: Final = "policy-evaluation-error"
"""Not a Cedar rule: the check itself could not run, so the engine denies (fails closed)."""

ALLOW_BY_DEFAULT_ID: Final = "allow-by-default"
"""The baseline permit. It never appears in a denial."""


class Reason(NamedTuple):
    """One reason in both languages."""

    en: str
    hi: str


REASONS: Final[Mapping[str, Reason]] = MappingProxyType(
    {
        PolicyId.CONSENT_REQUIRED: Reason(
            en="No consent on file for this household.",
            hi="इस घर की सहमति दर्ज नहीं है, इसलिए कॉल नहीं होगी।",
        ),
        PolicyId.CALLING_HOURS: Reason(
            en="Calls are allowed only between 09:00 and 21:00 IST (TRAI rule).",
            hi="कॉल सिर्फ़ सुबह 9 बजे से रात 9 बजे के बीच हो सकती है (TRAI नियम)।",
        ),
        PolicyId.ONE_CALL_PER_DAY: Reason(
            en="This household was already called today.",
            hi="इस घर को आज पहले ही कॉल हो चुकी है।",
        ),
        PolicyId.VERIFY_NEEDS_QUORUM: Reason(
            en="Not enough households have confirmed that water is back.",
            hi="अभी काफ़ी घरों ने पानी लौटने की पुष्टि नहीं की है।",
        ),
        PolicyId.NO_HOUSEHOLD_VIEW_FOR_DEPT: Reason(
            en="The department sees village totals only, not household answers.",
            hi="विभाग को सिर्फ़ गाँव का कुल आँकड़ा दिखता है, घरों के जवाब नहीं।",
        ),
        PolicyId.STALE_DATA: Reason(
            en="Data is older than 24 hours. Refresh it first.",
            hi="डेटा 24 घंटे से पुराना है। पहले नया डेटा लें।",
        ),
        ENGINE_ERROR_ID: Reason(
            en="The safety check could not be completed, so this action is blocked.",
            hi="नियम की जाँच पूरी नहीं हो सकी, इसलिए यह काम रोका गया है।",
        ),
    }
)
"""Policy id -> generic reason. Always available, needs no request facts."""

DETAILED: Final[Mapping[str, Reason]] = MappingProxyType(
    {
        PolicyId.VERIFY_NEEDS_QUORUM: Reason(
            en="Only {verify_yes} of the {quorum} households needed have confirmed water.",
            hi="पानी आने की पुष्टि जरूरी {quorum} में से सिर्फ़ {verify_yes} घरों ने की है।",
        ),
    }
)
"""Policy id -> reason template filled from request facts (context and resource attributes)."""


def reason_for(policy_id: str, facts: Mapping[str, object] | None = None) -> Reason:
    """Return the reason for ``policy_id``, with numbers filled in when ``facts`` has them."""
    template = DETAILED.get(policy_id)
    if template is not None and facts:
        try:
            return Reason(en=template.en.format_map(facts), hi=template.hi.format_map(facts))
        except (KeyError, IndexError, ValueError):
            pass
    known = REASONS.get(policy_id)
    if known is not None:
        return known
    return Reason(en=f"Blocked by rule {policy_id}.", hi=f"नियम {policy_id} के कारण रोका गया।")
