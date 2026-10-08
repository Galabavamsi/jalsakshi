// JalSakshi guard rails (docs/ARCHITECTURE.md section 7).
//
// Style: permit by default, then one forbid per rule. A forbid always wins in Cedar, so every
// denial names the @id of the rule that caused it. policy/reasons.py maps each @id to a
// plain-language reason in English and Hindi. Request shapes are in jalsakshi.cedarschema.

@id("allow-by-default")
permit (principal, action, resource);

// Never call a household that has not given consent.
@id("consent-required")
forbid (principal, action == Action::"PlaceCall", resource)
unless { resource.consent_given };

// TRAI calling hours: 09:00 up to (not including) 21:00 IST.
@id("calling-hours")
forbid (principal, action == Action::"PlaceCall", resource)
unless { context.hour_ist >= 9 && context.hour_ist < 21 };

// At most one daily check-in call per household per day. Verify calls are not limited here.
@id("one-call-per-day")
forbid (principal, action == Action::"PlaceCall", resource)
when { context.purpose == "DAILY" && context.calls_today >= 1 };

// A ticket closes as verified only when a quorum of households confirms water is back.
@id("verify-needs-quorum")
forbid (principal, action == Action::"CloseVerified", resource)
unless { context.verify_yes >= resource.quorum };

// The (simulated) PHED department sees village totals, never single household answers.
@id("no-household-view-for-dept")
forbid (principal, action == Action::"ViewHouseholdAnswers", resource)
when { ["PHED_AE_SIM", "PHED_EE_SIM"].contains(principal.role) };

// Evidence for the Gram Sabha must be built from data at most 24 hours old.
@id("stale-data")
forbid (principal, action == Action::"PublishEvidence", resource)
when { context.data_age_hours > 24 };
