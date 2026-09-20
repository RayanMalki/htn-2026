import { StrictMode, Component, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import '@fontsource-variable/manrope';
import './medbot.css';

function sampleRate(value: string | undefined, fallback: number) {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= 1 ? parsed : fallback;
}

export const sentryReady = import.meta.env.VITE_SENTRY_DSN
  ? import('@sentry/react').then(Sentry => {
    Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || 'development',
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.browserProfilingIntegration(),
      Sentry.replayIntegration({
        maskAllText: true, maskAllInputs: true, blockAllMedia: true, unmask: [], unblock: [],
      }),
    ],
    tracesSampleRate: sampleRate(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE, 1),
    profileSessionSampleRate: sampleRate(import.meta.env.VITE_SENTRY_PROFILE_SESSION_SAMPLE_RATE, 0.1),
    profileLifecycle: 'trace',
    // Keep normal sessions off by default; enable a sample explicitly for demos.
    replaysSessionSampleRate: sampleRate(import.meta.env.VITE_SENTRY_REPLAY_SESSION_SAMPLE_RATE, 0),
    replaysOnErrorSampleRate: sampleRate(import.meta.env.VITE_SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE, 1),
    tracePropagationTargets: [/^\/api\//], sendDefaultPii: false,
    beforeSend(event) {
      delete event.request; delete event.user; delete event.breadcrumbs; delete event.extra;
      return event;
    },
    beforeSendTransaction(event) {
      delete event.request; delete event.user; delete event.breadcrumbs;
      return event;
    },
    });
    return Sentry;
  }) : Promise.resolve(undefined);

class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) {
    void sentryReady.then(sentry => sentry?.captureException(error));
  }
  render() {
    return this.state.failed ? <main className="fatal"><h1>Something didn’t load.</h1>
      <p>Your analysis is saved on the server. Reload to reconnect.</p>
      <button onClick={() => location.reload()}>Reload page</button></main> : this.props.children;
  }
}
createRoot(document.getElementById('root')!).render(<StrictMode><ErrorBoundary><App /></ErrorBoundary></StrictMode>);
