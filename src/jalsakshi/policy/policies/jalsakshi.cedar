// JalSakshi guard rails (docs/ARCHITECTURE.md section 7).
//
// Style: permit by default, then one forbid per rule. A forbid always wins in Cedar, so every
// denial names the @id of the rule that caused it. policy/reasons.py maps each @id to a
// plain-language reason in English and Hindi. Request shapes are in jalsakshi.cedarschema.

@id("allow-by-default")
permit (principal, action, resource);

// Never call a household that has not given consent. The one exception is the registration
// call, whose whole purpose is to read the notice and ask for consent (§15.3).
@id("consent-required")
forbid (principal, action == Action::"PlaceCall", resource)
unless { resource.consent_given || context.purpose == "REGISTER" };

// A family that declined or withdrew is never called again, unless it gives a missed call itself.
@id("no-calls-after-withdrawal")
forbid (principal, action == Action::"PlaceCall", resource)
when {
  ["DECLINED", "WITHDRAWN"].contains(resource.consent_status) && !context.caller_initiated
};

// At most one daily check-in (or one unasked registration call) per household per day.
// Verify calls and calls back after a missed call are not limited here.
@id("one-call-per-day")
forbid (principal, action == Action::"PlaceCall", resource)
when {
  ["DAILY", "REGISTER"].contains(context.purpose) &&
  !context.caller_initiated &&
  context.calls_today >= 1
};

// Calls back after missed calls: at most 5 a day per number, so nobody can be made to spam.
@id("callback-limit")
forbid (principal, action == Action::"PlaceCall", resource)
when { context.caller_initiated && context.callbacks_today >= 5 };

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

// Only the sarpanch may approve an announcement before it is played to households.
@id("broadcast-needs-sarpanch")
forbid (principal, action == Action::"ApproveBroadcast", resource)
unless { principal.role == "SARPANCH" };

// An announcement is sent only once approved, and at most twice a week per village.
@id("broadcast-not-approved")
forbid (principal, action == Action::"SendBroadcast", resource)
unless { resource.state == "APPROVED" };

@id("broadcast-weekly-limit")
forbid (principal, action == Action::"SendBroadcast", resource)
when { context.sent_last_7_days >= 2 };
