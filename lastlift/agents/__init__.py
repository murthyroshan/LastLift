"""Operations agents: three roles in one process, with no language model in the critical path.

  Monitor     reads the scope's lift closures (the alert feed);
  Analyst     chooses a playbook from graph facts (Cypher), calls the tools through MCP, writes an Assessment;
  Dispatcher  proposes actions from a fixed policy table, only for assessments made at the graph's current
              state_version (a Cypher guard); a stale belief cannot act. Humans approve; nothing is filed here.

Roles hand off by writing nodes ((:Assessment)-[:ABOUT]->(:Lift), (:ActionProposal)-[:BASED_ON]->(:Assessment)),
so every decision can be read back in Cypher. No language model is given a write tool, so text in an alert (or a
prompt injection in it) cannot cause an action.
"""
