import { useEffect, useState } from 'react';
import { api, seconds } from './api';
import type { Metrics } from './types';

export default function Dashboard() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    const load = () => api<Metrics>('/api/metrics', { signal: controller.signal }).then(value => {
      setMetrics(value); setError('');
    }).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    void load(); const interval = setInterval(load, 10000);
    return () => { controller.abort(); clearInterval(interval); };
  }, []);
  const maximum = Math.max(...Object.values(metrics?.stages || {}), 1);
  return <section className="dashboard"><div className="section-heading"><div><span className="eyebrow">PIPELINE OBSERVATORY</span>
    <h2>Know where the seconds go.</h2></div><span className="subtle">Last 24 hours · refreshes every 10s</span></div>
    {error ? <p className="error" role="alert">{error}</p> : null}
    <div className="metric-grid">{[
      ['Cases submitted', metrics?.total_cases],
      ['Completion rate', metrics?.finished ? `${Math.round(metrics.complete / metrics.finished * 100)}%` : null],
      ['Failure rate', metrics?.finished ? `${Math.round(metrics.failed / metrics.finished * 100)}%` : null],
      ['Median duration', metrics?.p50_seconds != null ? seconds(metrics.p50_seconds) : null],
      ['95th percentile', metrics?.p95_seconds != null ? seconds(metrics.p95_seconds) : null], ['In queue', metrics?.queued],
    ].map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value ?? '—'}</strong></div>)}</div>
    <div className="stage-chart"><h3>Average time by stage</h3>{Object.entries(metrics?.stages || {}).map(([name, duration]) =>
      <div className="bar-row" key={name}><span>{name.replaceAll('_', ' ')}</span><div className="bar-track"><div style={{ width: `${duration / maximum * 100}%` }} /></div><b>{seconds(duration)}</b></div>)}
      {!Object.keys(metrics?.stages || {}).length ? <p className="subtle">Stage timings will appear after the first analysis finishes.</p> : null}
    </div><p className="subtle">This dashboard uses persisted case measurements. Distributed traces and captured errors are available in your configured Sentry project.</p>
  </section>;
}
