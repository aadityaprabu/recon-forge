import React, { useState } from 'react'
import './policy-history.css'

const processors = ['PROC_A', 'PROC_B', 'PROC_C']
const labels = { ACTIVE: 'Active', ARCHIVED: 'Archived', ELIGIBLE_FOR_APPROVAL: 'Awaiting approval', REJECTED: 'Rejected', ROLLED_BACK: 'Rolled back' }
const date = value => value ? new Date(value * 1000).toLocaleString() : 'Not recorded'
const percent = value => value == null ? '—' : `${(value * 100).toFixed(2)}%`
const tolerance = (policy, processor) => policy?.matching?.processor_amount_tolerance_cents?.[processor]

export default function PolicyHistory({ data }) {
  const [selectedVersion, selectVersion] = useState(null)
  const policies = [...(data.policies || [])].sort((a, b) => (b.created_at || 0) - (a.created_at || 0) || a.version.localeCompare(b.version))
  const active = data.active_policy
  const selected = policies.find(p => p.version === selectedVersion) || policies[0]
  const parent = policies.find(p => p.version === selected?.policy?.parent)
  const run = (data.runs || []).find(r => r.run_id === selected?.run_id)
  const evaluation = (data.evaluations || []).find(e => e.run_id === selected?.run_id) || run?.evaluation
  const status = entry => entry.version === active?.version ? 'ACTIVE' : entry.status || 'RECORDED'
  const changes = selected ? processors.filter(p => parent && tolerance(selected.policy, p) !== tolerance(parent.policy, p)) : []

  return <div className="policy-history">
    <section className="hero"><div><div className="eyebrow">POLICY HISTORY</div><h2>Every change. A clear history.</h2><p>Follow policy evolution from the baseline to the rules running today.</p></div><span className="ph-count">{policies.length} saved {policies.length === 1 ? 'version' : 'versions'}</span></section>

    <section className="ph-active">
      <div className="ph-active-heading"><div><span className="ph-active-label"><i/> CURRENTLY RUNNING</span><h2>{active ? 'Active matching policy' : 'No active policy'}</h2><code>{active?.version || 'Waiting for initialization'}</code></div><span className="ph-badge active">{active ? 'Live' : 'Pending'}</span></div>
      <div className="ph-processors">{processors.map(p => <div key={p}><span>{p}</span><strong>{tolerance(active, p) ?? '—'}<small>¢</small></strong><span>Amount tolerance</span></div>)}</div>
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
        <div className="table-scroll"><table><thead><tr><th>Processor</th>{selected.policy?.parent && <th>Before</th>}<th>{selected.policy?.parent ? 'After' : 'Tolerance'}</th><th>Change</th></tr></thead><tbody>{processors.map(p => <tr key={p} className={changes.includes(p) ? 'ph-changed' : ''}><td><b>{p}</b></td>{selected.policy?.parent && <td>{tolerance(parent?.policy, p) == null ? 'Unavailable' : `${tolerance(parent.policy, p)}¢`}</td>}<td><b>{tolerance(selected.policy, p) ?? '—'}¢</b></td><td>{!selected.policy?.parent ? 'Initial value' : !parent ? 'Parent unavailable' : changes.includes(p) ? <span className="ph-delta">Updated</span> : 'Unchanged'}</td></tr>)}</tbody></table></div>

        {selected.proposal && <div className="ph-rationale"><h3>Why this version was proposed</h3><p>{selected.proposal.reason}</p>{selected.proposal.risk && <><small>RISK CONSIDERED</small><p>{selected.proposal.risk}</p></>}</div>}
        {evaluation && <div className="ph-evaluation"><div><small>AUTO-RESOLUTION</small><b>{percent(evaluation.baseline?.auto_resolution_rate)} → {percent(evaluation.candidate?.auto_resolution_rate)}</b></div><div><small>BACKTEST</small><b>{evaluation.guardrails?.passed == null ? 'Pending' : evaluation.guardrails.passed ? 'Guardrails passed' : 'Guardrails failed'}</b></div></div>}
        <details className="ph-json"><summary>View full policy JSON</summary><pre>{JSON.stringify(selected.policy || {}, null, 2)}</pre></details>
      </section>
    </div>}
  </div>
}
