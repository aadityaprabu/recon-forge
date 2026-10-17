import React, { useState } from 'react'
import './policy-history.css'
import { policyFields, policyProcessors as processors, policyValue, processorLabel } from './policy-fields.js'

const labels = { ACTIVE: 'Active', ARCHIVED: 'Archived', ELIGIBLE_FOR_APPROVAL: 'Awaiting approval', REJECTED: 'Rejected', ROLLED_BACK: 'Rolled back' }
const date = value => value ? new Date(value * 1000).toLocaleString() : 'Not recorded'
const percent = value => value == null ? '—' : `${(value * 100).toFixed(2)}%`

export default function PolicyHistory({ data }) {
  const [selectedVersion, selectVersion] = useState(null)
  const policies = [...(data.policies || [])].sort((a, b) => (b.created_at || 0) - (a.created_at || 0) || a.version.localeCompare(b.version))
  const active = data.active_policy
  const selected = policies.find(p => p.version === selectedVersion) || policies[0]
  const parent = policies.find(p => p.version === selected?.policy?.parent)
  const run = (data.runs || []).find(r => r.run_id === selected?.run_id)
  const evaluation = (data.evaluations || []).find(e => e.run_id === selected?.run_id) || run?.evaluation
  const status = entry => entry.version === active?.version ? 'ACTIVE' : entry.status || 'RECORDED'
  const rows = policyFields.flatMap(config => processors.map(processor => ({ config, processor, before: parent ? policyValue(parent.policy, config, processor) : null, after: policyValue(selected?.policy, config, processor) })))

  return <div className="policy-history">
    <section className="hero"><div><div className="eyebrow">POLICY HISTORY</div><h2>Every change. A clear history.</h2><p>Follow amount, settlement, fixed-fee, and percentage-fee rules from baseline to production.</p></div><span className="ph-count">{policies.length} saved {policies.length === 1 ? 'version' : 'versions'}</span></section>

    <section className="ph-active">
      <div className="ph-active-heading"><div><span className="ph-active-label"><i/> CURRENTLY RUNNING</span><h2>{active ? 'Active matching policy' : 'No active policy'}</h2><code>{active?.version || 'Waiting for initialization'}</code></div><span className="ph-badge active">{active ? 'Live' : 'Pending'}</span></div>
      <div className="ph-policy-categories">{policyFields.map(config => <div className="ph-rule" key={config.field}><h3>{config.label}</h3><code className="ph-param-name">{config.group}.{config.parameter}</code>{processors.map(p => <div key={p}><span title={p}>{processorLabel(p, active)}</span><b>{active ? policyValue(active, config, p) : '—'}{config.unit}</b></div>)}</div>)}</div>
      <div className="ph-policy-settings">
        <div><small>AMOUNT RULES</small><b>Relative tolerance: {active?.amount_matching?.relative_tolerance_bps ?? 0} bps</b><span>Hard cap: {active?.amount_matching?.maximum_tolerance_cents ?? 25}¢</span></div>
        <div><small>SETTLEMENT RULES</small><b>{active?.settlement?.day_basis === 'business' ? 'Business days' : 'Calendar days'} · weekend grace {active?.settlement?.weekend_grace_days ?? 0} days</b><span>{active?.settlement?.timezone || 'America/New_York'}</span></div>
        <div><small>FEE CALCULATION</small><b>{(active?.fees?.treatment || 'gross_to_net').replaceAll('_', ' ')}</b><span>Rounding: {(active?.fees?.rounding || 'half_up').replaceAll('_', ' ')}</span></div>
        <div><small>FUTURE CAPABILITIES</small><b>Refund and group matching disabled</b><span>Exact references · Python/fuzzy integration on hold</span></div>
      </div>
      <div className="ph-fixed">Fixed controls: matching customer, merchant, currency and processor · unique allocation · false-match guardrails · human approval</div>
      <p>New candidates take effect after passing evaluation and human approval.</p>
    </section>

    {!selected ? <section className="panel empty"><h3>Your policy history starts here</h3><p>Saved policy versions will appear once the baseline is initialized.</p></section> : <div className="ph-layout">
      <section className="panel ph-timeline"><div className="panel-heading"><div><div className="eyebrow">VERSION TIMELINE</div><h2>Policy evolution</h2></div><span className="ph-subtle">Newest first</span></div>
        <ol>{policies.map(entry => {
          const currentStatus = status(entry)
          return <li key={entry.version}><button className={`ph-version ${entry.version === selected.version ? 'selected' : ''}`} onClick={() => selectVersion(entry.version)} aria-pressed={entry.version === selected.version}>
            <span className={`ph-node ${currentStatus === 'ACTIVE' ? 'active' : ''}`}/>
            <span className="ph-version-top"><span className={`ph-badge ${currentStatus.toLowerCase()}`}>{labels[currentStatus] || currentStatus}</span><time>{date(entry.created_at)}</time></span>
            <b>{entry.patch_name || (entry.policy?.parent ? 'Policy update' : 'Baseline policy')}</b><code>{entry.version}</code>
            <span className="ph-version-note">{entry.policy?.parent ? `Based on ${entry.policy.parent}` : 'Starting point'} <span aria-hidden="true">↗</span></span>
          </button></li>
        })}</ol>
      </section>

      <section className="panel ph-details" aria-label="Selected policy details">
        <div className="panel-heading"><div><div className="eyebrow">VERSION DETAILS</div><h2>{selected.patch_name || 'Matching policy'}</h2></div><span className={`ph-badge ${status(selected).toLowerCase()}`}>{labels[status(selected)] || status(selected)}</span></div>
        <code className="ph-id">{selected.version}</code>
        <div className="ph-meta"><div><small>CREATED</small><span>{date(selected.created_at)}</span></div><div><small>PARENT VERSION</small>{parent ? <button className="text-button" onClick={() => selectVersion(parent.version)}>{parent.version} ↗</button> : <span>{selected.policy?.parent || 'Baseline — no parent'}</span>}</div></div>

        <h3>{selected.policy?.parent ? 'What changed' : 'Baseline configuration'}</h3>
        <div className="table-scroll"><table><thead><tr><th>Policy rule</th><th>Processor</th>{selected.policy?.parent && <th>Before</th>}<th>{selected.policy?.parent ? 'After' : 'Value'}</th><th>Change</th></tr></thead><tbody>{rows.map(({ config, processor, before, after }) => <tr key={`${config.field}-${processor}`} className={parent && before !== after ? 'ph-changed' : ''}><td>{config.label}<code className="ph-param-name">{config.group}.{config.parameter}</code></td><td><b title={processor}>{processorLabel(processor, selected.policy)}</b></td>{selected.policy?.parent && <td>{before == null ? 'Unavailable' : `${before}${config.unit}`}</td>}<td><b>{after}{config.unit}</b></td><td>{!selected.policy?.parent ? 'Initial' : !parent ? 'Unknown' : before !== after ? <span className="ph-delta">Updated</span> : 'Unchanged'}</td></tr>)}</tbody></table></div>

        {selected.proposal && <div className="ph-rationale"><h3>Why this version was proposed</h3><p>{selected.proposal.reason}</p>{selected.proposal.risk && <><small>RISK CONSIDERED</small><p>{selected.proposal.risk}</p></>}</div>}
        {evaluation && <div className="ph-evaluation"><div><small>BENCHMARK ACCURACY</small><b>{percent(evaluation.baseline?.accuracy)} → {percent(evaluation.candidate?.accuracy)}</b></div><div><small>BACKTEST</small><b>{evaluation.guardrails?.passed == null ? 'Pending' : evaluation.guardrails.passed ? 'Guardrails passed' : 'Guardrails failed'}</b></div></div>}
        {selected.policy_skill && <div className="soft-callout"><b>Policy Update Skill · v{selected.policy_skill.version}</b><p>Proposal informed by the current policy, diagnosis, and analysis.</p><code className="ph-param-name">SHA-256: {selected.policy_skill.sha256}</code></div>}
        <details className="ph-json"><summary>View full policy JSON</summary><pre>{JSON.stringify(selected.policy || {}, null, 2)}</pre></details>
      </section>
    </div>}
  </div>
}
