import { useEffect, useState } from "react";
import { getClaims, getDisclaimers } from "../api";
import { S } from "../strings.en";

const REPO = "https://github.com/murthyroshan/LastLift";

/** Small explanatory drawings, one per step (decorative; each step's text says the same). */
function Art({ step }: { step: number }) {
  if (step === 0) return (
    <svg viewBox="0 0 200 120" className="how-art" aria-hidden="true">
      {[0, 1, 2, 3, 4].map((i) => <rect key={i} x={30 + i * 6} y={18 + i * 16} width={140 - i * 12} height={9} rx={3} className="ha-line" style={{ opacity: 1 - i * 0.15 }} />)}
      <rect x={22} y={10} width={156} height={100} rx={10} className="ha-frame" />
    </svg>
  );
  if (step === 1) return (
    <svg viewBox="0 0 200 120" className="how-art" aria-hidden="true">
      <path d="M40 25 L100 60 L160 25 M100 60 L70 100 M100 60 L130 100" className="ha-edge" />
      <path d="M100 60 L130 100" className="ha-lift" />
      {[[40, 25], [160, 25], [100, 60], [70, 100], [130, 100]].map(([x, y], i) => <circle key={i} cx={x} cy={y} r={7} className="ha-node" />)}
      <rect x={106} y={70} width={22} height={16} rx={4} className="ha-liftbox" />
    </svg>
  );
  if (step === 2) return (
    <svg viewBox="0 0 200 120" className="how-art" aria-hidden="true">
      <circle cx={100} cy={16} r={8} className="ha-node" />
      <circle cx={100} cy={104} r={8} className="ha-node" />
      <path d="M100 24 C 40 40, 40 80, 100 96" className="ha-route a" />
      <path d="M100 24 C 160 40, 160 80, 100 96" className="ha-route b" />
      <rect x={42} y={52} width={24} height={16} rx={4} className="ha-liftbox" />
      <rect x={134} y={52} width={24} height={16} rx={4} className="ha-liftbox" />
    </svg>
  );
  return (
    <svg viewBox="0 0 200 120" className="how-art" aria-hidden="true">
      <circle cx={100} cy={60} r={36} className="ha-seal" />
      <path d="M82 60 l12 12 l24 -26" className="ha-check" />
    </svg>
  );
}

export function About() {
  const [d, setD] = useState<Record<string, string>>({});
  const [claims, setClaims] = useState<Record<string, any> | null>(null);
  useEffect(() => {
    getDisclaimers().then(setD).catch(() => {});
    getClaims().then(setClaims).catch(() => {});
  }, []);
  const steps = [
    [S.about.how.s1t, S.about.how.s1],
    [S.about.how.s2t, claims ? S.about.how.s2(claims.platforms_modelled) : ""],
    [S.about.how.s3t, S.about.how.s3],
    [S.about.how.s4t, claims ? S.about.how.s4(claims.falkordb_certified, claims.maxflow_calls) : ""],
  ];
  return (
    <article className="about">
      <p className="eyebrow">{S.about.eyebrow}</p>
      <h1>{S.about.title}</h1>
      <p className="lead">{S.about.model}</p>
      <ol className="how">
        {steps.map(([t, body], i) => (
          <li key={i} className="how-step">
            <Art step={i} />
            <div><h2>{t}</h2><p>{body}</p></div>
          </li>
        ))}
      </ol>
      <section className="card about-notes">
        <h2>{S.about.limitsTitle}</h2>
        <p>{S.about.assumptions}</p>
        {d.validation && <p>{d.validation}</p>}
        <p className="muted">{S.about.ai}</p>
        <p><a href={REPO}>{S.about.source}</a> · <a href={`${REPO}/issues/new?template=accessibility-problem.yml`}>{S.about.feedback}</a></p>
      </section>
    </article>
  );
}
