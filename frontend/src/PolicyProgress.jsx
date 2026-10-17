import React from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export default function PolicyProgress({ data, latest }) {
  const progress = (data.policy_accuracy_history || []).map((p, index) => ({
    Version: index, Accuracy: Number((p.accuracy * 100).toFixed(2)), name: p.name,
  }))
  const pending = (data.runs || []).find(r => r.status === 'WAITING_APPROVAL')
  const projected = pending?.evaluation?.candidate?.accuracy
  return <>
    <section className="panel"><div className="panel-heading"><div><div className="eyebrow">THREE AGENTS · ONE CONTROLLED CHANGE</div><h2>Diagnosis → Analysis → Evolution</h2></div><span className="status neutral">PYTHON EVOLUTION ON HOLD</span></div>
      <div className="agent-roles">{(data.agents || []).map((a, i) => <div key={a.name} className={latest?.status === 'RUNNING' && latest.current_node === a.stage ? 'agent-running' : ''}><span className="agent-number">0{i + 1}</span><b>{a.name}</b><p>{a.role}</p></div>)}</div><p className="muted">Deterministic backtesting and guardrails evaluate the proposal. A human approves activation; replay verifies the result.</p>
    </section>
    <section className="panel chart-panel"><div className="panel-heading"><div><div className="eyebrow">FIXED 8,000-RECORD BENCHMARK</div><h2>Policy accuracy · gradual improvement</h2></div><span className="status good">{progress.length ? `${progress.at(-1).Accuracy}% active` : 'Initializing'}</span></div>
      <p className="muted">The hard demo targets 20% → 25% → … → 70%. Each approved version changes one field. Hard reference cases remain unresolved while Python and fuzzy evolution are on hold. The chart shows measured active and previously promoted versions.</p>
      {progress.length > 0 && <div className="chart-wrap"><ResponsiveContainer width="100%" height={230}><AreaChart data={progress}><CartesianGrid vertical={false} stroke="#edf0f3"/><XAxis dataKey="Version" tickFormatter={v => v === 0 ? 'Baseline' : `Update ${v}`} allowDecimals={false}/><YAxis domain={[0, 100]} tickFormatter={v => `${v}%`}/><Tooltip labelFormatter={v => v === 0 ? 'Baseline' : `Approved update ${v}`} formatter={v => [`${v}%`, 'Benchmark accuracy']}/><Area type="linear" dataKey="Accuracy" stroke="#5368cd" fill="#5368cd15" strokeWidth={2.5} dot={{ r: 4 }}/></AreaChart></ResponsiveContainer></div>}
      {projected != null && <div className="soft-callout">Pending candidate: {(projected * 100).toFixed(0)}% benchmark accuracy · awaiting approval, not yet active.</div>}
    </section>
  </>
}
