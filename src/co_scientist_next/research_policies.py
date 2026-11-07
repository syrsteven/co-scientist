"""Explicitly selectable nonproduction policies; never production defaults."""

POLICIES = {
    "goal": {
        "id": "GOAL-NONPROD-JOURNEY",
        "version": "2026-11-06-v1",
        "development_only": True,
        "required_information": ["intended_use"],
        "text": "GJ-1: NONPRODUCTION conceptual research policy. Assess the actual Goal and intended use. Only nonclinical hypothesis reading, critique and methods development are within scope. No patient use, clinical decision, human/animal experiments or actual experimental execution is authorized. GJ-2: Scientific uncertainty, weak evidence and unknown novelty alone are not ethical rejection. GJ-3: Reject concrete safety/use conflicts with cited clauses and reasons. GJ-4: Missing safety-determining information requires incomplete execution and clarification, not a third ethical decision. Completed Goal decisions are pass/reject only. GJ-5: Pass permits bounded literature/hypothesis work only, not organizational approval or scientific validation.",
    },
    "candidate": {
        "id": "CANDIDATE-ETHICS-NONPROD-JOURNEY",
        "version": "2026-11-06-v1",
        "mode": "development",
        "text": "NP-01 — Scope. This NONPRODUCTION trial policy applies only to reading and reviewing non-clinical mechanistic hypotheses and research-method development for the specific candidate bound to this operation. It does not authorize patient use, clinical decisions, human or animal experiments, or any actual experimental execution.\nNP-02 — Independent candidate review. Review the complete saved candidate, its proposed interventions, assumptions and actual intended use. Do not inherit Goal Ethics pass. Do not rewrite the candidate or invent absent context or approvals.\nNP-03 — Scientific uncertainty is not an ethical violation. Unproven causal bridges, weak evidence, context-transfer uncertainty and unknown novelty alone justify neither reject nor incomplete. Scientific concerns belong in the later scientific review.\nNP-04 — Specific safety conflicts. A reject must identify concrete safety risks or a proposed use/intervention conflicting with NP-01, cite the applicable clauses and explain the candidate/use facts. Do not infer a prohibited intended use solely because a hypothesis describes conceptual validation.\nNP-05 — Missing safety-determining information. If information necessary to judge a concrete safety risk is missing, decide incomplete and state the missing information and why it matters. Never invent that information or default to pass. Invalid input, missing policy, provider failure or parse failure are execution states, not ethical decisions.\nNP-06 — Limited pass. A completed pass allows only this candidate's separate R0 within this trial and the frozen intended use. It is not organizational ethics approval, scientific admission, clinical advice, permission for experiments or authorization for R1.\nNP-07 — Scope and maturity remain nonproduction. Record pass/reject/incomplete reasons, exact policy references, risks and limitations. A real model response does not upgrade this development policy into a production policy or validate ethical accuracy. Technical failures cannot be converted to ethical conclusions.",
    },
    "decision_policy": {
        "id": "CANDIDATE-ETHICS-NONPROD-TRIAL-DECISIONS",
        "version": "2026-11-05-v1",
        "routes": {"pass": "continue", "reject": "stop", "incomplete": "hold"},
    },
    "r0": {
        "id": "R0-NONPROD-TRIAL",
        "version": "2026-11-05-v1",
        "mode": "development",
        "text": "R0-NP-01: Nonproduction initial review only, under the accepted implemented R0 policy. Require this exact candidate's completed real P09 pass, not Goal pass or fixture pass.\nR0-NP-02: Review Goal alignment, identifiable proposition, same-context internal coherence, empirical testability and indispensable core clearly false factual premises. A factual block requires exact candidate span, reliable actual visible original-source evidence and access/position, and a necessity argument. A claim of source contradiction must quote the actual original passage. Model memory and assistant paraphrase alone cannot support deterministic factual blocking.\nR0-NP-03: Unproven conjectures, absent direct support, context transfer, local wording distortion, weak evidence, unimplemented tools, uncertain novelty and scientific dispute are not automatic blocks. Preserve scientific unknowns and targeted required_R1_checks. Do not demand an unknown causal bridge already be established.\nR0-NP-04: Do not retrieve, edit or repair the candidate, generate a child, create M03 Inventory, perform R2/admission or execute R1. proceed_to_R1 means only eligibility for a subsequent review stage, not scientific correctness or authorization to execute R1 in this trial. Preserve limitations and science_validated=false.",
    },
}
