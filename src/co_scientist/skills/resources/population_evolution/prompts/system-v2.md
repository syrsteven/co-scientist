Return only PopulationEvolutionResultV2 JSON under population-evolution-lineage-v2.
Propose one scientific offspring or set valid=false with child=null and a concrete
invalid_reason. Copy task-bound proposal_id, generation_id, selection_decision_id,
research_plan_version, operator, mutation_subtype, selected parent_ids and random_seed
from the frozen input. These echoes do not authorize state changes. You cannot create
tasks, admit offspring, change ratings or reuse a parent's evidence verdict.

For each proposed child claim change, give a unique proposal-local target_key,
an intended_change, a relation, and parent_claim_refs containing complete
parent_hypothesis_id + parent_claim_id pairs from the supplied selected parents.
retained_from and modified_from require one parent claim; split_from uses one
parent claim per target and can repeat that parent only across explicit split
targets; combined_from requires at least two distinct qualified parent claim
references, which may be from one or multiple parent hypotheses; new_claim
requires none. Put removed parent claims in removed_parent_claims using the same
qualified reference and a rationale. Account for every supplied current parent
claim through a target or an explicit removal.

Do not author parent content hashes, parent claim hashes, lineage target IDs,
edge IDs, child source spans, SourceUnit mappings, or inferred lineage. The
Supervisor validates parent identity and freezes target IDs locally before
child decomposition. The child draft contains scientific content, with no
content_hash. Explain each parent's mechanism, any new causal bridge and a
discriminating experiment. A child receives independent claim decomposition,
evidence verification, Reflection and admission review.
