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
    NO_CALLS_AFTER_WITHDRAWAL = "no-calls-after-withdrawal"
    CALLBACK_LIMIT = "callback-limit"
    VERIFY_NEEDS_QUORUM = "verify-needs-quorum"
    NO_HOUSEHOLD_VIEW_FOR_DEPT = "no-household-view-for-dept"
    STALE_DATA = "stale-data"
    BROADCAST_NEEDS_SARPANCH = "broadcast-needs-sarpanch"
    BROADCAST_NOT_APPROVED = "broadcast-not-approved"
    BROADCAST_WEEKLY_LIMIT = "broadcast-weekly-limit"


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
        PolicyId.NO_CALLS_AFTER_WITHDRAWAL: Reason(
            en="This family said no to calls (or stopped them), so it is not called.",
            hi="इस परिवार ने कॉल के लिए मना किया है (या बंद कराई हैं), इसलिए कॉल नहीं होगी।",
        ),
        PolicyId.CALLBACK_LIMIT: Reason(
            en="This number already got 5 call-backs today.",
            hi="इस नंबर पर आज पहले ही 5 बार वापस कॉल हो चुकी है।",
        ),
        PolicyId.BROADCAST_NEEDS_SARPANCH: Reason(
            en="Only the sarpanch can approve an announcement.",
            hi="घोषणा को सिर्फ़ सरपंच मंज़ूरी दे सकते हैं।",
        ),
        PolicyId.BROADCAST_NOT_APPROVED: Reason(
            en="The sarpanch has not approved this announcement yet.",
            hi="सरपंच ने अभी इस घोषणा को मंज़ूरी नहीं दी है।",
        ),
        PolicyId.BROADCAST_WEEKLY_LIMIT: Reason(
            en="At most 2 announcements a week can be sent to the village.",
            hi="गाँव में हफ़्ते में ज़्यादा से ज़्यादा 2 घोषणाएँ भेजी जा सकती हैं।",
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
