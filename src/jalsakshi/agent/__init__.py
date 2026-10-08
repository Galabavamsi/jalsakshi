"""Strands agents on Bedrock: spoken-note extraction and the Gram Sabha brief.

See docs/ARCHITECTURE.md section 10. Import from the submodules (``agent.notes``,
``agent.brief``, ``agent.models``); this package deliberately imports nothing so that
deterministic callers (template brief, number validator) do not pay the Strands import cost.
"""
