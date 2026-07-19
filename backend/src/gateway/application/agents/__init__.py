"""Agent orchestration (ADR-0016, Tier-1 invariants 3 and 4).

Agents conform to ``BaseAgent`` and are sequenced by ``AgentRuntime``, which is the only place a
``RoutingDecision`` is constructed. No provider calls, no MCP, no routing intelligence - the
agents here are deliberately minimal so the orchestration contract can be validated before any
decision logic is added.
"""
