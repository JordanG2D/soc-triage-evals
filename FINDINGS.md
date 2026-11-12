# Development vertical slice

The 16-alert offline path passes its fixed regression baseline: genuine local embedding retrieval, all four deterministic tool implementations, prewritten assistant responses, deterministic scoring, and report export. Its target-label matches are expected fixture behavior and do not measure a model's quality.

All 16 alerts are development material. They cover eight attack-technique families with benign and uncertain counterparts. No held-out test split, full dataset, second prompt, frozen comparison, or deployment recommendation has been produced.

The initial live run will evaluate the same prompt on one OpenAI and one Anthropic model. Results and actual response records will be retained here after execution. The 20 calibration responses were predeclared as A002, A004, A005, A007, A009, A010, A011, A012, A013, and A014 from each model, followed by a seeded blind shuffle. Selection occurred before observing any live result.

The written faithfulness rubric is implemented, but the judge is **UNCALIBRATED — pending 20 human labels**. No coding agent will supply those labels. Citation ID validity and exact fact-text overlap are mechanical checks and are not semantic faithfulness scores.

Live spending is pending, currently $0. A run will receive a nonrefundable $5 allocation within the lifetime $20 cap. Actual usage estimates, conservative accounting, response latency, confusion matrices, failure examples, and exploratory paired family-bootstrap intervals will be reported separately from fixture results.

The next milestone is a completed vertical slice and human labeling handoff. Expansion remains gated on the project owner's review.
