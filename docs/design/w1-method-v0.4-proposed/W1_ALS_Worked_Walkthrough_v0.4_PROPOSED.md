# W1 v0.4 — ALS worked walkthrough (scientific method illustration)

**Status:** SIMULATED DATA HANDOFF, **not** an independently executed agent pipeline or scientific validation. Source snippets below are restricted paraphrases from the v0.3 Pro study; selected foundational facts (Kosako 2009; Megat 2023) were cross-checked against public primary pages in the current review. No paid model, wet-lab experiment or exhaustive database search was run for this v0.4 packaging step.

## 1. Goal preparation

**Original question:** “Propose a novel, testable mechanism by which phosphorylation of a nuclear pore complex nucleoporin may contribute to amyotrophic lateral sclerosis. Explain the molecular mechanism and suggest feasible validation experiments.”

**Retain as requirements:** ALS; nucleoporin phosphorylation; a causal/testable mechanism; feasible validation concept. **Not given:** particular kinase or nucleoporin, ALS subtype, specific cell model, phosphosite. **Do not add:** iPSC motor neurons as a user hard constraint.

**Goal Ethics (demonstration only):** `pass` under a **non-approved illustrative policy** for nonclinical scientific ideation; not ethics approval for experiments.

## 2. Two-stage retrieval plan

**Broad orientation** (query design, not an assertion these exact PubMed API calls ran): disease association with NPC; nucleoporin phosphorylation/transport, without ALS term; competing structural and Ran-based mechanisms; neuronal-context findings; measurement/assay opportunities.

**Example of recorded v0.3 public web queries** (actual study trace, non-exhaustive):
- `Q02`: ALS NUP50 phosphorylation nuclear pore transport.
- `Q03`: C9orf72 ALS nucleocytoplasmic transport RanGAP1 Zhang 2015 Nature.
- `Q04`: ALS CHMP7 POM121 nuclear pore loss 2021 2023.
- `Q10`: "NUP50" "phosphorylation" "ALS" "ERK".
- `Q16`: "NUP50" "ERK" "ALS" phosphorylation.
- `Q-API-FAILED`: attempted Europe PMC API query, access failed; **not** an empty successful search.

**Focused retrieval:** after reading the preliminary findings, ask how NUP50 abundance, kinase state and transport-recovery measurements could be compared. Search for the closest published mechanism and important opposing models. The completion status of each query and the actual material accessed must be recorded.

## 3. Literature records retained, rather than flattened into a story

| Source | Actual experimental scope retained | Scientific use | Cannot infer |
|---|---|---|---|
| Kosako et al., 2009, PMID 19767751 | ERK/NUP50 phosphorylation altered receptor affinity and migration in the reported system | Modification-function anchor | ALS-neuron cargo import or disease causation |
| Kosako Supplementary Fig. 5 | CDK1/cyclin B could phosphorylate indicated NUP50 sites in vitro | Kinase-assignment counterexample | S221/S315 signal proves ERK as the sole kinase |
| Megat et al., 2023, PMCID PMC9860017 | NUP50 **depletion**, reporter export and survival in reported neuronal models; TDP-43 negative findings | Disease-related anchor, negative-result guard | Depletion equals phosphorylation; TDP-43 change is required |
| Zhang et al., 2015, PMC4800742 | C9ORF72/Ran-related model | Transport alternative | NPC phosphorylation is the primary cause |
| Coyne et al., 2021, PMC9022198 | CHMP7-linked pore injury | Structural alternative | Transport changes require NUP50 modification |
| Chou et al., 2018, PMC5800968 | TDP-43/NPC timing and reciprocal context | Reverse-causality alternative | All contexts share the same direction |

A complete **single model-visible packet** containing these six source views, locators, access restrictions, hypotheses-versus-observations labels and ContextContrast fields is in `W1_Complete_Worked_Input_v0.4_PROPOSED.json` under `TransportSeedBackgroundPacket`. A rendered example USER message is under `TransportSeedModelInputRendering`.

These are materials for *generation*, not a completed M03 inventory/M05 appraisal/M06 Dossier.

## 4. KnowledgeMap and Seed creation

**Observed in distinct contexts:** (A) NUP50 phosphorylation changes some transport-receptor interactions; (B) NUP50 abundance depletion affects reported neuronal phenotypes; (C) Ran and CHMP7 studies offer alternative routes to transport/NPC injury.

**Hypothesized, not observed:** A low-abundance neuronal state could alter sensitivity to a NUP50 phosphorylation state, changing transport recovery.

- `DIRECTED-TRANSPORT-01`: question is **whether NUP50 abundance modifies the phosphorylation effect**. New bridge = interaction; not the statement that either individual study proved that interaction.
- `DIRECTED-STRUCTURE-01`: whether NUP98 phosphorylation could alter pore integrity in nondividing cells. This **requires more reading** before a site-specific formulation: inspect original site/assay details in the mitotic studies.
- `OPEN-01`: input at launch is the **original Goal + neutral scientific orientation + retrieval capabilities**, not a preselected AMPK/metabolic hypothesis and not directed-seed outputs. The v0.3 metabolic direction can serve as an *after-the-fact example*, but does not prove independent branch discovery.

## 5. Per-seed Background Readiness

`DIRECTED-TRANSPORT-01` decision for **conceptual, explicitly conditional** Generation:

| Criterion | Result | Basis |
|---|---|---|
| Goal interpretable | Met | Original explicit goal |
| Starting anchors traceable | Met within read scope | Kosako/Megat source views |
| Experimental context preserved | Met | Receptor migration ≠ cargo flux; depletion ≠ phosphorylation |
| Alternatives considered | Met for this limited scope | Ran, CHMP7, reverse-causality views |
| Critical reading adequate | Met **only for conceptual claim** | Not claiming neuronal site/kinase has been validated |
| Closest prior work attempted | Met as attempt, **not exhaustive** | Recorded Q10/Q12/Q16/Q19 |

`decision=ready`, `allowed_specificity=qualified conceptual interaction hypothesis`; not `proven`. **No completed discriminating prediction is required for this decision.**

`DIRECTED-STRUCTURE-01`: `retrieve_more` because details necessary for the requested specific NUP98 mechanism were not actually inspected. This is a missing-premise-information finding, **not** a failed biological hypothesis.

## 6. Representative Generation (not an executed model output)

**Proposed candidate:** “If a disease-relevant neuronal population has reduced NUP50 abundance, a reversible phosphorylation state may disproportionately delay receptor-dependent cargo-transport recovery, contributing to injury before generalized pore loss.”

**Existing anchors:** modification/function in another experimental setting; NUP50 abundance perturbation in disease-relevant biology.

**NEW causal bridges:** (1) abundance-by-modification interaction in the chosen neurons; (2) contribution of recovery delay to later vulnerability.

**Candidate's discriminating prediction:** compare NUP50 abundance and a verified modification state factorially; the proposed interaction implies different time-resolved recovery effects across abundance conditions. Ran dysfunction or structural injury does not, by itself, predict the same abundance-by-phosphorylation interaction.

**Falsification concept:** after verified target engagement and a sufficiently sensitive assay, the predicted interaction and recovery defect do not occur. This does not make every single negative experiment definitive; measurement validity matters.

**Source-boundary statement:** a site-level signal does not uniquely identify ERK in vivo, and direct ALS neuronal causality has not been established.

## 7. Candidate Ethics and R0 (simulated)

**Candidate Ethics**: illustrative `pass` under the *non-approved demonstration policy* limited to conceptual research. **No production screening is asserted.** Candidate Ethics' actual decision taxonomy is not silently changed by the user's request to make Goal Ethics binary.

**R0**: `proceed_to_R1` because a conditional, causally interpretable and empirically refutable proposition exists. The following remain explicit **R1 questions**, not R0 falsehood verdicts:

- Which phosphosite and kinase operate in the chosen neuronal system?
- Does protein abundance interact with modification, versus independent main effects?
- Does altered transport recovery precede and mediate injury?
- Could Ran-dependent transport changes or structural NPC damage explain the result?
- Has the proposed interaction been investigated before?

A candidate asserting that “Megat proved NUP50 phosphorylation produces TDP-43 mislocalization” as a directly cited established fact would be blocked **only if the exact passage directly contradicts that indispensable premise**. A novel candidate hypothesizing a context-specific TDP-43 effect is not automatically blocked.

## 8. AML/KIRA6 transfer check

The PR #4 public development material is used to check that **cell viability differs by line**, while studies of KIT interactions, broad KIRA6 binding and HSP60-related signaling arise in other settings. A model must not jump from different IC50 values to an exclusively IRE1-mediated AML mechanism, or automatically choose KIT/HSP60 as the true target. The proposed proper output is a conditional **target-attribution question**, not a therapeutic claim.

## 9. What the example does and does not establish

**Does:** demonstrate the specific data objects and a permissible flow from source views to Seed readiness, a newly proposed mechanism, and narrow R0.

**Does not:** prove coverage of the world's ALS literature; prove independent seed discovery; run or compare two actual Generation modes; demonstrate superior prompt quality; provide wet-lab results; or validate scientific novelty. The next legitimate study is a controlled model experiment with frozen input packets and independent expert review.

## Primary source locators

- Kosako et al., 2009, https://pubmed.ncbi.nlm.nih.gov/19767751/ ; related supplement in the v0.3 source catalogue.
- Megat et al., 2023, https://pmc.ncbi.nlm.nih.gov/articles/PMC9860017/ , Results: Consequences of NUP50 depletion in cultured neurons.
- Source IDs and access descriptions for other materials appear in v0.3 and in the v0.4 JSON; additional claims remain limited to the inspected sections reported by v0.3.
