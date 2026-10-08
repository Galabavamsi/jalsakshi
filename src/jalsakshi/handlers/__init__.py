"""Lambda entrypoints: thin glue over core, policy, store, voice, agent and data.

Modules: api (console /api/*), sim (/sim/*), ivr_vobiz (Vobiz webhooks), sfn_tasks (Step
Functions tasks), context (scheduled public-data refresh). Shared glue lives in config, common,
calls, tickets, dialer and sfn.
"""
