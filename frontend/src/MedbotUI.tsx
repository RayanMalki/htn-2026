import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Case, ClaimResult } from "./types";

export function Scanner({ active = false }: { active?: boolean }) {
  return (
    <div className={`scanner ${active ? "active" : ""}`} aria-hidden="true">
      <div className="scanner-glow" />
      <div className="scan-paper back">
        <i />
        <i />
        <i />
      </div>
      <div className="scan-paper front">
        <b>✚</b>
        <i />
        <i />
        <i />
      </div>
      <div className="laser" />
      <div className="scanner-base">
        <div className="scanner-slot" />
        <span />
      </div>
      <div className="shreds">
        <i />
        <i />
        <i />
        <i />
      </div>
    </div>
  );
}

export function Sheet({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = ref.current;
    const trigger = document.activeElement as HTMLElement | null;
    node?.showModal();
    return () => {
      node?.close();
      if (trigger?.isConnected) trigger.focus({ preventScroll: true });
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="sheet"
      aria-labelledby="sheet-title"
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <button
        className="icon-button sheet-close"
        aria-label="Close dialog"
        onClick={onClose}
      >
        ×
      </button>
      <h2 id="sheet-title">{title}</h2>
      {children}
    </dialog>
  );
}

export function Overview({
  items,
  mock,
}: {
  items: ClaimResult[];
  mock: boolean;
}) {
  const groups = [
    {
      label: "Supported",
      tone: "supports",
      count: items.filter((i) => i.verdict?.label === "supports").length,
    },
    {
      label: "Contradicted",
      tone: "contradicts",
      count: items.filter((i) => i.verdict?.label === "contradicts").length,
    },
    {
      label: "Uncertain",
      tone: "uncertain",
      count: items.filter((i) => i.verdict?.label === "uncertain").length,
    },
    {
      label: "Unfinished",
      tone: "pending",
      count: items.filter((i) => !i.verdict).length,
    },
  ];
  return (
    <section className="evidence-overview" aria-label="Evidence overview">
      <h3>{mock ? "Prepared findings" : "What did the check find?"}</h3>
      <p className="evidence-takeaway">{mock ? 'Example findings only.' : items.some(i => !i.verdict) ? 'Some claims still need an assessment.' : items.some(i => i.verdict?.label === 'contradicts') ? 'Some claims are challenged by the retrieved evidence.' : items.some(i => i.verdict?.label === 'uncertain') ? 'Some claims remain unsettled.' : 'The assessed claims have support in the retrieved evidence.'}</p>
      <p>Out of {items.length} {items.length === 1 ? 'claim' : 'claims'} checked:</p>
      <div className="overview-counts">
        {groups.map((g) => (
          <div key={g.label} className={`${g.tone} ${g.count ? 'has-findings' : ''}`}>
            <b>{g.count}</b>
            <span>{g.label}</span>
          </div>
        ))}
      </div>
      <p>
        These counts describe this check. They are not a score for how true the whole video is.
      </p>
      {items.filter(item => item.verdict?.label === 'uncertain').map((item, i) => <details className="uncertainty-reason" key={item.claim.id}><summary>Why claim {items.indexOf(item) + 1} is uncertain</summary><p>{item.verdict?.explanation}</p>{!!item.verdict?.limitations.length && <ul>{item.verdict.limitations.map((reason, n) => <li key={`${i}-${n}`}>{reason}</li>)}</ul>}</details>)}
    </section>
  );
}

export function ClaimCarousel({
  children,
  count,
}: {
  children: ReactNode;
  count: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(0);
  function move(next: number) {
    const node = ref.current;
    const child = node?.children[next] as HTMLElement | undefined;
    if (!node || !child) return;
    node.scrollTo({
      left: child.offsetLeft - (node.children[0] as HTMLElement).offsetLeft,
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  }
  return (
    <section className="claims-section" id="claims" aria-label="Individual claims">
      <div className="section-heading">
        <div>
          <span className="eyebrow">LET’S GET SPECIFIC</span>
          <h2>Let’s unpack it.</h2>
        </div>
        {count > 1 && (
          <div className="carousel-controls">
            <button
              className="icon-button"
              aria-label="Previous claim"
              disabled={index === 0}
              onClick={() => move(index - 1)}
            >
              ←
            </button>
            <button
              className="icon-button"
              aria-label="Next claim"
              disabled={index >= count - 1}
              onClick={() => move(index + 1)}
            >
              →
            </button>
          </div>
        )}
      </div>
      <div
        ref={ref}
        className="claims-list"
        onScroll={() => {
          const node = ref.current;
          if (!node) return;
          const first = node.children[0] as HTMLElement;
          let nearest = 0,
            distance = Infinity;
          Array.from(node.children).forEach((child, i) => {
            const d = Math.abs(
              (child as HTMLElement).offsetLeft -
                first.offsetLeft -
                node.scrollLeft,
            );
            if (d < distance) {
              distance = d;
              nearest = i;
            }
          });
          setIndex(nearest);
        }}
      >
        {children}
      </div>
      {count > 1 && (
        <p className="swipe-hint">
          <span className="carousel-dots" aria-hidden="true">{Array.from({length: count}, (_, i) => <i key={i} className={i === index ? 'current' : ''} />)}</span>
          Claim {index + 1} of {count} · Swipe or use the arrows
        </p>
      )}
    </section>
  );
}

export function ShareResult({ value }: { value: Case }) {
  const [message, setMessage] = useState("");
  const [fallback, setFallback] = useState(false);
  const link = new URL(
    `?case=${encodeURIComponent(value.id)}`,
    location.origin + location.pathname,
  ).href;
  async function share() {
    setMessage("");
    try {
      if (navigator.share)
        await navigator.share({ title: "MedBot · Evidence check", url: link });
      else if (navigator.clipboard) {
        await navigator.clipboard.writeText(link);
        setMessage("Result link copied.");
      } else setFallback(true);
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setFallback(true);
        setMessage("Copy the link below instead.");
      }
    }
  }
  return (
    <section className="share-section" id="share-results">
      <span className="eyebrow">PASS ON THE CONTEXT</span>
      <h2>A little less guesswork.</h2>
      <p>
        Share this saved check, including its sources and limitations. Anyone
        with the link can view it.
      </p>
      <div className="share-actions"><button className="button secondary" onClick={() => void share()}>
        Share results ↗
      </button><a className="button secondary" href={`/api/cases/${value.id}/replay`}>Save offline ↓</a></div>
      <small>Save a copy of the written findings to read without internet.</small>
      {fallback && (
        <label className="share-link">
          Result link
          <input readOnly value={link} onFocus={(e) => e.target.select()} />
        </label>
      )}
      <p role="status">{message}</p>
    </section>
  );
}

export function TopicExamples() {
  const [topic, setTopic] = useState<string | null>(null);
  return <section className="topic-examples" aria-label="Example topics">
    <span className="eyebrow">CURIOUS? START HERE · EXAMPLES</span>
    <h2>Big topics. Small clips.</h2><p>Explore what a check could cover.</p>
    {['Peptides & recovery', 'Collagen & skin', 'Supplements & sleep'].map((name, i) => <button key={name} className={`topic-row topic-${i}`} onClick={() => setTopic(name)}><span className="topic-symbol" aria-hidden="true">{['✳', '◒', '☾'][i]}</span><span><b>{name}</b><small>Example topic · clip coming later</small></span><span aria-hidden="true">↗</span></button>)}
    {topic && <Sheet title={topic} onClose={() => setTopic(null)}><p>This is a topic preview. A sample clip and its checked sources will be added later.</p><p>For a real check, paste a supported video link on the homepage. No assessment has been generated for this example.</p></Sheet>}
  </section>;
}
