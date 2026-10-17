import React from 'react'
import { policyValue, processorLabel } from './policy-fields.js'
import './policy-diff.css'

// Line positions in the complete policy serialized with two-space indentation.
function policyLine(policy, path) {
  let value = policy, line = 1
  for (const key of path) {
    if (!value || !Object.hasOwn(value, key)) return '—'
    line += 1
    for (const sibling of Object.keys(value)) {
      if (sibling === key) break
      line += JSON.stringify(value[sibling], null, 2).split('\n').length
    }
    value = value[key]
  }
  return line
}

export default function PolicyDiff({ baseline, candidate, patch, change }) {
  const before = policyValue(baseline, change, patch.processor)
  const after = policyValue(candidate, change, patch.processor)
  const inherited = baseline?.processor_overrides?.[patch.processor]?.[change.group]?.[change.parameter] == null
  const overridePath = ['processor_overrides', patch.processor, change.group, change.parameter]
  const oldLine = policyLine(baseline, inherited ? [change.group, change.parameter] : overridePath)
  const newLine = policyLine(candidate, overridePath)
  const line = value => `    "${change.parameter}": ${JSON.stringify(value)}`
  return <div className="policy-diff">
    <div className="policy-diff-heading"><code>policy.json</code><span>{processorLabel(patch.processor, candidate)} · {change.label}</span></div>
    <div className="policy-diff-path"><code>processor_overrides.{patch.processor}.{change.group}</code></div>
    <div className="policy-diff-columns"><span>Active policy · {baseline?.version}</span><span>Candidate policy · {candidate?.version}</span></div>
    <div className="policy-diff-body" role="region" aria-label="Policy change diff" tabIndex={0}>
      <pre className="policy-diff-context">{`  "${change.group}": {`}</pre>
      <pre className="policy-diff-removed"><span className="policy-diff-number" title="Active policy line">{oldLine}</span><span className="policy-diff-number" aria-hidden="true"></span><span aria-label="Removed">−</span>{line(before)}</pre>
      <pre className="policy-diff-added"><span className="policy-diff-number" aria-hidden="true"></span><span className="policy-diff-number" title="Candidate policy line">{newLine}</span><span aria-label="Added">+</span>{line(after)}</pre>
      <pre className="policy-diff-context">{'  }'}</pre>
    </div>
    {inherited && <p className="policy-diff-note">Line numbers refer to the complete formatted policy JSON. The active value is inherited from the default {change.group} settings. This change adds a processor override.</p>}
  </div>
}
