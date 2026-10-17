import { useEffect, useState } from "react";
import { getDisclaimers } from "../api";
import { S } from "../strings.en";

const REPO = "https://github.com/murthyroshan/LastLift";

export function About() {
  const [d, setD] = useState<Record<string, string>>({});
  useEffect(() => { getDisclaimers().then(setD).catch(() => {}); }, []);
  return (
    <>
      <h1>{S.about.title}</h1>
      <p>{S.about.model}</p>
      <p>{S.about.assumptions}</p>
      {d.validation && <p>{d.validation}</p>}
      <p>{S.about.ai}</p>
      <p><a href={REPO}>{S.about.source}</a> · <a href={`${REPO}/issues/new?template=accessibility-problem.yml`}>{S.about.feedback}</a></p>
    </>
  );
}
