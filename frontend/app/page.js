'use client'

import { useEffect, useState } from 'react'

const clinical = 'vaidyasetu'
const claims = 'ayushman-sarathi'
const names = { [clinical]: 'VaidyaSetu', [claims]: 'Ayushman-Sarathi' }
const descriptions = {
  [clinical]: 'Review CT-10, trial registration, and participant consent evidence.',
  [claims]: 'Review PM-JAY pre-authorizations, package rates, and claim evidence.',
}
const pretty = value => JSON.stringify(value, null, 2)
const base = process.env.NEXT_PUBLIC_API_BASE ||
  (process.env.NODE_ENV === 'development' ? 'http://127.0.0.1:8000' : '')

async function request(path, body, signal) {
  const response = await fetch(`${base}/api/${path}`, {
    ...(body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }),
    signal,
  })
  const data = await response.json()
  if (!response.ok) {
    const message = Array.isArray(data.detail)
      ? data.detail.map(issue => `${issue.loc.join('.')} (${issue.type})`).join(', ')
      : data.detail
    throw new Error(message || `Request failed (${response.status})`)
  }
  return data
}

function useRequest() {
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function run(task) {
    setError('')
    setBusy(true)
    try {
      const next = await task()
      setResult(next)
      return next
    } catch (failure) {
      setResult(null)
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }
  return { result, error, busy, run, clear: () => { setResult(null); setError('') } }
}

function useSamples(module) {
  const [samples, setSamples] = useState({})
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    request(`samples/${module}`, undefined, controller.signal).then(setSamples).catch(failure => {
      if (failure.name !== 'AbortError') setError(failure.message)
    })
    return () => controller.abort()
  }, [module])
  return { samples, error }
}

function SampleLoader({ module, onLoad }) {
  const { samples, error } = useSamples(module)
  return <label>Load sample
    <select value="" onChange={event => onLoad(pretty(samples[event.target.value]))}>
      <option value="" disabled>Choose a synthetic sample</option>
      {Object.keys(samples).map(key => <option key={key}>{key}</option>)}
    </select>
    {error && <small role="alert">Sample loader unavailable. {error}</small>}
  </label>
}

function Editor({ label, value, onChange, rows = 9 }) {
  return <label>{label}
    <textarea spellCheck={false} rows={rows} value={value} onChange={event => onChange(event.target.value)} />
  </label>
}

function Findings({ findings }) {
  if (!findings.length) return <p>No findings.</p>
  return <div className="table-wrap"><table>
    <thead><tr><th>Outcome</th><th>Rule</th><th>Finding and evidence</th></tr></thead>
    <tbody>{findings.map((item, index) => <tr key={index}>
      <td><span className={`status ${item.outcome}`}>{item.outcome}</span></td>
      <td><code>{item.rule_id}</code>{item.section && <small>{item.section}</small>}
        {item.line_ref && <small>{item.line_ref}</small>}</td>
      <td>{item.message}<small>{item.source_ref}</small>
        {item.evidence_refs?.length > 0 && <small>{item.evidence_refs.join(' · ')}</small>}</td>
    </tr>)}</tbody>
  </table></div>
}

function ErrorMessage({ error }) {
  return error && <p className="error" role="alert">{error}</p>
}

function Audit({ module }) {
  const [payload, setPayload] = useState('')
  const audit = useRequest()
  function edit(value) { setPayload(value); audit.clear() }
  const evaluation = audit.result?.evaluation
  const receipt = audit.result?.receipt
  return <>
    <section className="card">
      <h2>Run an audit</h2>
      <fieldset disabled={audit.busy}>
        <SampleLoader module={module} onLoad={edit} />
        <Editor label="Evidence payload (JSON)" value={payload} onChange={edit} />
        <button disabled={!payload.trim()} onClick={() => audit.run(() => request(module, JSON.parse(payload)))}>
          {audit.busy ? 'Running audit…' : 'Run audit'}
        </button>
      </fieldset>
      <ErrorMessage error={audit.error} />
    </section>
    {evaluation && <section className="card">
      <h2>Rule findings</h2>
      <p>{evaluation.case_ref || evaluation.admission_ref} · {evaluation.as_of} · {evaluation.ruleset_version}</p>
      {evaluation.pathway && <p>CT-10 pathway: {evaluation.pathway.replaceAll('_', ' ')}
        {evaluation.response_due_on && ` · Response due ${evaluation.response_due_on}`}</p>}
      {evaluation.expected_total_paise != null && <p>Expected total {new Intl.NumberFormat('en-IN', {
        currency: 'INR', style: 'currency',
      }).format(evaluation.expected_total_paise / 100)} · {evaluation.schedule_version}</p>}
      <Findings findings={evaluation.findings} />
    </section>}
    {receipt && <section className="card">
      <h2>SHA-256 audit receipt</h2>
      <p>Receipt {receipt.receipt_id} · {receipt.event_count} events · {receipt.recorded_at} UTC</p>
      <code className="digest">{receipt.sha256}</code>
    </section>}
  </>
}

function Vernacular() {
  const [payload, setPayload] = useState('')
  const check = useRequest()
  function edit(value) { setPayload(value); check.clear() }
  const result = check.result
  return <>
    <section className="card">
      <h2>Vernacular ICF</h2>
      <p>Compare English consent clauses with localized wording and English back-translations.</p>
      <fieldset disabled={check.busy}>
        <SampleLoader module="vernacular" onLoad={edit} />
        <Editor label="Consent payload (JSON)" value={payload} onChange={edit} />
        <p className="hint">Add optional <code>localized</code> and <code>back_translation</code> objects keyed by the same disclosure IDs as <code>source</code>.</p>
        <button disabled={!payload.trim()} onClick={() => check.run(() => request('vernacular', JSON.parse(payload)))}>
          {check.busy ? 'Verifying…' : 'Verify clauses'}
        </button>
      </fieldset>
      <ErrorMessage error={check.error} />
    </section>
    {result && <section className="card">
      <h2>Consent comparison</h2>
      <p>{result.mode} · {result.ruleset_version}</p><p>{result.notice}</p>
      <dl className="metrics">
        <div><dt>Required sections populated</dt><dd>{result.metrics.completeness_percent}%</dd></div>
        <div><dt>Round-trip phrase matches</dt><dd>{result.metrics.phrase_matches}</dd></div>
        <div><dt>Words per sentence</dt><dd>{result.metrics.words_per_sentence ?? '—'}</dd></div>
      </dl>
      <div className="table-wrap"><table>
        <thead><tr><th>Disclosure</th><th>English</th><th>Localized</th><th>Back-translation</th></tr></thead>
        <tbody>{Object.entries(result.sections).filter(([, row]) => row.source || row.localized || row.back_translation)
          .map(([key, row]) => <tr key={key}><td>{key.replaceAll('_', ' ')}</td><td>{row.source || '—'}</td>
            <td lang={result.language}>{row.localized || '—'}</td><td>{row.back_translation || '—'}</td></tr>)}</tbody>
      </table></div>
      <h3>Findings</h3>
      <Findings findings={result.findings} />
    </section>}
  </>
}

function Simulator() {
  const [payload, setPayload] = useState('')
  const [population, setPopulation] = useState('')
  const [answers, setAnswers] = useState({})
  const [questions, setQuestions] = useState(null)
  const generate = useRequest()
  const score = useRequest()
  function reset() { setAnswers({}); setQuestions(null); generate.clear(); score.clear() }
  function edit(value) { setPayload(value); reset() }
  function input(question, item, field, value) {
    setAnswers(previous => ({ ...previous, [question]: { ...previous[question],
      [item]: { ...previous[question]?.[item], [field]: value } } }))
    score.clear()
  }
  function body() { return { case: JSON.parse(payload), population: population.trim() || null } }
  async function start() {
    reset()
    const result = await generate.run(() => request('sec', body()))
    if (result) setQuestions(result)
  }
  function submit(event) {
    event.preventDefault()
    const responses = Object.fromEntries(Object.entries(answers).flatMap(([query, items]) => {
      const complete = Object.entries(items).filter(([, item]) => item.statement?.trim() && item.evidence_ref?.trim())
      return complete.length ? [[query, Object.fromEntries(complete)]] : []
    }))
    score.run(() => request('sec', { ...body(), responses }))
  }
  const state = score.result || questions
  return <>
    <section className="card">
      <h2>SEC Query Simulator</h2>
      <fieldset disabled={generate.busy || score.busy}>
        <SampleLoader module={clinical} onLoad={edit} />
        <Editor label="Trial dossier (JSON)" value={payload} onChange={edit} />
        <label>Proposed population (optional)
          <input value={population} maxLength={4000} onChange={event => { setPopulation(event.target.value); reset() }} />
        </label>
        <button disabled={!payload.trim()} onClick={start}>{generate.busy ? 'Generating…' : 'Generate questions'}</button>
      </fieldset>
      <ErrorMessage error={generate.error} />
    </section>
    {state && <form className="card" onSubmit={submit}>
      <h2>Sponsor response checklist</h2>
      <p>{state.notice}</p>
      <fieldset disabled={score.busy}>{state.questions.map(question => <details className="query" key={question.id} open>
        <summary>{question.prompt} <strong>{question.coverage} submitted</strong></summary>
        <p className="hint">{question.source_ref}</p>
        {question.related_findings.length > 0 && <Findings findings={question.related_findings} />}
        {question.checklist.map(item => <div className="answer" key={item.id}>
          <p>{item.requirement} <span className={`status ${item.status === 'submitted' ? 'pass' : 'review'}`}>{item.status}</span></p>
          <label>Sponsor statement<input maxLength={4000} value={answers[question.id]?.[item.id]?.statement || ''}
            onChange={event => input(question.id, item.id, 'statement', event.target.value)} /></label>
          <label>Evidence reference<input maxLength={4000} value={answers[question.id]?.[item.id]?.evidence_ref || ''}
            onChange={event => input(question.id, item.id, 'evidence_ref', event.target.value)} /></label>
        </div>)}
      </details>)}
      <button>{score.busy ? 'Evaluating…' : 'Evaluate responses'}</button>
      </fieldset>
      <ErrorMessage error={score.error} />
    </form>}
  </>
}

function Estimator() {
  const [count, setCount] = useState('10')
  const cases = Math.max(0, Math.min(100000, Math.floor(Number(count))))
  const hours = minutes => `${(cases * minutes / 60).toLocaleString('en-IN', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })} h`
  return <section className="card">
    <h2>Manual Time-Saved Estimator</h2>
    <p>Illustrative estimate using 30 minutes of manual review and 1 minute of deterministic checks per case. Excludes preparation and follow-up.</p>
    <label>Cases in batch<input type="number" min="1" max="100000" step="1" value={count}
      onChange={event => setCount(event.target.value)} /></label>
    <dl className="metrics">
      <div><dt>Manual review</dt><dd>{hours(30)}</dd></div>
      <div><dt>Deterministic checks</dt><dd>{hours(1)}</dd></div>
      <div><dt>Estimated time saved</dt><dd>{hours(29)}</dd></div>
    </dl>
  </section>
}

export default function Dashboard() {
  const [module, setModule] = useState(clinical)
  const [panel, setPanel] = useState('Audit')
  return <div className="shell">
    <aside>
      <div className="brand"><span aria-hidden="true">+</span> SwasthyaSetu</div>
      <nav aria-label="Compliance module">
        {Object.entries(names).map(([id, name]) => <button key={id} aria-pressed={module === id}
          onClick={() => { setModule(id); setPanel('Audit') }}>{name}</button>)}
      </nav>
    </aside>
    <main>
      <header><h1>{names[module]}</h1><p>{descriptions[module]}</p></header>
      {module === clinical && <nav className="panels" aria-label="VaidyaSetu tools">
        {['Audit', 'Vernacular ICF', 'SEC Simulator'].map(name => <button key={name} aria-pressed={panel === name}
          onClick={() => setPanel(name)}>{name}</button>)}
      </nav>}
      {panel === 'Audit' && <Audit key={module} module={module} />}
      {panel === 'Vernacular ICF' && <Vernacular />}
      {panel === 'SEC Simulator' && <Simulator />}
      <Estimator />
      <details className="card"><summary>Roadmap</summary>
        <ul><li>Draft CT-04, CT-01, and CTRI forms with XML and JSON output.</li>
          <li>Expand local consent phrase coverage and SEC evidence checklists.</li>
          <li>Add Schedule M CMC evidence checks.</li></ul>
      </details>
    </main>
  </div>
}
