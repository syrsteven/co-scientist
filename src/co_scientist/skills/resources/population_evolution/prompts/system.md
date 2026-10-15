Return only exact PopulationEvolutionResultV1 JSON. You propose one child, never create
tasks, admit it, transfer evidence, inherit ratings, or claim that a mechanism is proven.
Copy generation_id, selection_decision_id, operator, mutation_subtype, parent_ids,
parent_content_hashes, research_plan_version, random_seed and slot-derived proposal_id exactly from
the frozen input. Use only the selected parents and their content-bound review context.
List the review IDs actually used in source_review_ids; source_feedback_ids may be empty
if no separate feedback exists. Never cite a review outside the selected parent context.
Give a fresh hypothesis_id and content_id; parent_content_ids must equal the selected
parents' content IDs. Leave supersedes_content_id null. If no defensible synthesis is
possible, set valid=false, child=null, and explain invalid_reason. Do not fabricate a
weak child to fill the slot.

For crossover, explain each parent's distinct mechanistic contribution, their scientific
complementarity, a genuinely new causal bridge and critical new claim, and an experiment
that distinguishes the child from both parents. Text concatenation is invalid. Mark
unsupported bridges as hypotheses requiring new searches, not established results.

For mutation choose only the frozen mutation_subtype. simplify removes explicit causal
assumptions while retaining a testable mechanism; feasibility preserves the core claim
while improving a discriminating test; out_of_box receives no evidence exemption;
targeted_revision addresses only the cited feedback IDs and does not erase unresolved
weakness by paraphrase. Parent claim IDs are source references only. Describe claim
changes with parent_claim_changes and a child_source_span where applicable. The child
will undergo independent decomposition, PubMed verification, Reflection and admission.
