# Ideation Memory

Use this file to store reusable lessons from Workflow 1.

## Promising Directions

- **Reasoning manifold → actionable constraint**: FALSIFIED (2026-03-23). Correct LLM reasoning traces form a low-dim manifold (REMA, 2509.22518), and the manifold DOES separate correct from incorrect at aggregate level (energy gap=464 on GSM8K). However, local-chart PCA energy is NOT competitive with simpler density/classifier methods for failure prediction. At prefix=0.50, manifold AUROC=0.664 vs MLP=0.914, kNN=0.886, Mahalanobis=0.847. The geometry is real but the local-chart energy function is not the right way to exploit it.

- **Prefix-level early failure detection**: GO/NO-GO result: NO-GO for manifold energy (2026-03-23). Manifold energy at 50% prefix gives AUROC=0.664 — far below matched-capacity MLP verifier (0.914) and kNN density (0.886). The signal builds slowly and only becomes competitive at full trajectory (AUROC=0.901 at p=1.0). Simple density estimation is a far better prior.

- **kNN density and Mahalanobis as hidden-state verifiers**: CORRECTED (2026-03-23). Original AUROC=0.886 was inflated by TRACE-LEVEL splits (same-problem leakage). With PROBLEM-DISJOINT splits, kNN drops to 0.584 AUROC — barely above chance. However, WITHIN-PROBLEM reranking still works: kNN selects the correct trace 85.7% of the time vs 30% majority vote. The lesson: cross-problem prediction ≠ within-problem selection. Always use problem-disjoint splits.

- **Evaluation split methodology is critical**: LESSON LEARNED (2026-03-23). Trace-level splits inflate hidden-state verification AUROC by ~31 points due to same-problem leakage. ALWAYS use problem-disjoint splits. This applies to any hidden-state probing / verification study.

- **Matched-capacity ablation as the central novelty gate**: When positioning a hidden-state geometric scorer, the critical experiment is always vs. a matched-capacity generic MLP verifier. If the geometry doesn't add value over a MLP with same data and parameters, the manifold story fails. Design this control from day 1.

## Failed Directions

- **Local-chart PCA manifold energy for failure prediction**: Tried and failed (2026-03-23). Energy = min_k[α·||normal||² + β·||tangent||²] with position buckets + K-means + PCA. The energy function is too noisy at partial prefixes, the tangent/normal decomposition adds nothing over normal-only, and simple density methods (kNN, Mahalanobis) vastly outperform it. The random-chart control (0.592) vs correct-trace chart (0.649) shows only +5.7 AUROC points of "geometric" signal. The approach is dominated by a trivial linear probe (0.914).

- **Heuristic geometric regularizers**: Done by The Geometric Reasoner (2601.18832): chunk-level smoothness + diversity regularizers for inference-time search. Do not propose heuristic geometric scoring as a main contribution.

- **Weight-space manifold optimization (LLM training efficiency)**: Done by Mano (oblique manifold), Riemannian LoRA (Stiefel), mHC (Birkhoff polytope). These constrain model WEIGHTS, not reasoning STATES. Not the right angle.

- **Hyperbolic LLM representations**: Done by HypLoRA, HiM, Hyperbolic LLMs benchmark. Has limited connection to reasoning stability per se.

- **Manifold analysis without method**: REMA (2509.22518) and manifold envelopment for RLVR (2603.16578) are descriptive/analytical. Any paper in this area must propose a concrete actionable use of the geometry.

- **Curvature analysis only**: Curved Inference (2507.21107) measures residual stream curvature for interpretability. Has been done. Any curvature contribution must tie to a concrete reasoning improvement method.

- **Fréchet mean voting (Geometric Self-Consistency)**: Logically appealing but likely to fail — correct traces may form multiple clusters, and the Fréchet mean lands in low-density space between clusters. Keep as baseline/sanity check but not as main contribution.

## Reviewer Objections

- "This is just another hidden-state reward model / PRM in disguise." → Counter: need matched-capacity ablation + explicit geometric parametrization (tangent/normal) ablation + cross-model transfer. If Euclidean distance ≈ PCA chart energy, the geometric story is weak.

- "The manifold goes stale during RLVR." → Counter: periodic manifold refresh experiment; compare frozen vs. refreshed vs. full refresh ablation.

- "Geometry collapses valid reasoning diversity." → Counter: multi-style experiment; show accuracy does not come at the cost of collapsing multiple valid solution formats.

- "The Geometric Reasoner (2601.18832) already did geometric inference-time search." → Counter: Geometric Reasoner uses heuristic smoothness/diversity regularizers; we explicitly LEARN the manifold from correct traces. Different object, different method.

## Selection Heuristics

- **First pilot should be prefix-level AUROC**: Cheap, <2 GPU-hours, clear go/no-go criterion. If manifold energy does not predict failure earlier than logprob/entropy, do not proceed to reranking or RLVR.

- **Pick ideas where negative results are also informative**: The manifold-reasoning story is valuable as a diagnostic paper even if the method doesn't beat PRMs. Plan for this fallback from day 1.

- **Always read REMA + Geometric Reasoner before proposing new geometric reasoning methods**: These are the two anchors. Any new idea must be clearly differentiated from both.

- **For NeurIPS-level positioning**: The make-or-break distinction must be about GEOMETRY BEING NECESSARY, not just "another scoring method." Show that geometric parametrization matters in ablations.
