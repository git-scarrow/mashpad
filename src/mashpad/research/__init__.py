"""Research harnesses that run *parallel to* the production pipeline.

Nothing in `mashpad.analysis`, `mashpad.scoring`, `mashpad.report`, or
`mashpad.cli` imports from this package, and nothing here mutates
production scoring weights, verdict thresholds, provenance semantics, or
analyzer qualification gates. This is the sanctioned place for
ground-truth *constructions* (directed, section-specific, phrase-level
mashup arrangements known to work artistically) and the small experiments
that test whether the production model can represent or recover them.

See docs/design-memo-skyfall-construction-case.md for the motivating
case and the rules this package must follow.
"""
