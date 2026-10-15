Decompose the immutable offspring hypothesis into explicit causal claims under
claim-provenance-lineage-v3. Return only provider JSON with a claims array.
Every included claim supplies scientific fields and valid source_unit_ids from
the frozen child hypothesis. These IDs establish text provenance only. Choose
semantic_relation as direct, paraphrase or synthesized; it does not establish
parent lineage. A diagnostic quote is optional and has no authority.

For each claim, reference exactly one lineage_target_id already present in the
frozen task context, or mark is_explicit_new_claim=true for an unplanned new
claim and leave lineage_target_id null. Copy target IDs exactly. Do not create
target IDs or infer a mapping from claim wording, array position, source text,
SourceUnit IDs, span or similarity. A planned new_claim target still needs its
target ID. Do not author parent hashes, child claim hashes, edge IDs, source
spans or resolved SourceUnit objects. Local validation binds source units and
lineage references and applies the configured total/critical claim limits.
