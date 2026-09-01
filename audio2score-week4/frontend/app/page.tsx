"use client";

import { useEffect } from "react";
import Link from "next/link";

import { track } from "../lib/analytics";
import AppShell from "../components/layout/AppShell";
import Container from "../components/layout/Container";
import DemoPreview from "../components/marketing/DemoPreview";
import HeroVisual from "../components/marketing/HeroVisual";
import Section from "../components/marketing/Section";
import ButtonLink from "../components/ui/ButtonLink";
import { Text } from "../components/ui/Text";

const STEPS = [
  {
    n: "01",
    title: "Choose a recording",
    body: "Upload a recording of your music.",
  },
  {
    n: "02",
    title: "NotaScore listens",
    body: "NotaScore finds the notes, rhythm and musical structure.",
  },
  {
    n: "03",
    title: "Get your score",
    body: "Review your transcription and export it as PDF, MIDI or MusicXML.",
  },
];

const USES = [
  {
    title: "Piano",
    body: "Capture performances, exercises and ideas.",
  },
  {
    title: "Guitar",
    body: "Turn recorded playing into notation. Support is growing with the product.",
  },
  {
    title: "Voice",
    body: "Preserve melodies and musical ideas.",
  },
  {
    title: "More instruments",
    body: "We expand as transcription quality allows — not ahead of it.",
  },
];

const EXPORTS = [
  {
    title: "PDF",
    body: "Read, print and share your score.",
  },
  {
    title: "MIDI",
    body: "Continue working with the musical data.",
  },
  {
    title: "MusicXML",
    body: "Open and continue editing in professional notation software.",
  },
];

export default function LandingPage() {
  useEffect(() => {
    track("landing_view");
  }, []);

  return (
    <AppShell variant="public" contained={false}>
      <section className="ns-hero">
        <Container width="wide">
          <div className="ns-hero-grid">
            <div className="ns-hero-copy">
              <p className="ns-kicker">NotaScore</p>
              <h1 className="ns-display ns-hero-title">Turn your recordings into editable sheet music.</h1>
              <Text size="body-large" className="ns-hero-lead">
                Give NotaScore a recording and get a score you can correct and export.
              </Text>
              <div className="ns-hero-actions">
                <ButtonLink
                  href="/create"
                  onClick={() => track("hero_create_clicked")}
                >
                  Create a score
                </ButtonLink>
                <Link href="/how-it-works" className="ns-text-link">
                  See how it works →
                </Link>
              </div>
            </div>
            <HeroVisual />
          </div>
        </Container>
      </section>

      <Section id="examples" title="See what NotaScore can do.">
        <p className="ns-section-lead">
          Give NotaScore a recording, and you get sheet music you can edit. This
          example is a short piano figure transcribed by NotaScore — labelled as
          an example, not a concert performance.
        </p>
        <DemoPreview />
      </Section>

      <Section id="how-it-works" title="How it works">
        <ol className="ns-steps">
          {STEPS.map((step) => (
            <li key={step.n} className="ns-step">
              <span className="how-index">{step.n}</span>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section title="Made for musicians.">
        <div className="ns-uses">
          {USES.map((item) => (
            <article key={item.title} className="ns-use">
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </article>
          ))}
        </div>
      </Section>

      <Section title="Take your music anywhere.">
        <p className="ns-section-lead">
          NotaScore does not need to replace your existing music tools. It can be
          the bridge: recording → NotaScore → your music software.
        </p>
        <div className="ns-exports">
          {EXPORTS.map((item) => (
            <article key={item.title}>
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </article>
          ))}
        </div>
      </Section>

      <Section title="Music shouldn’t disappear just because you didn’t write it down.">
        <p className="ns-section-lead ns-why">
          NotaScore helps you turn performances, improvisations and musical ideas
          into notation you can keep working with.
        </p>
        <p className="ns-tech">
          Advanced music listening, built around the way musicians work — not around
          studio jargon.
        </p>
      </Section>

      <Section id="pricing" title="Plans, when you need them.">
        <PricingPreview />
      </Section>

      <Section>
        <div className="ns-final-cta">
          <h2 className="ns-display">Ready to write your music down?</h2>
          <p>Turn your next recording into a score.</p>
          <ButtonLink
            href="/create"
            onClick={() => track("hero_create_clicked")}
          >
            Create a score
          </ButtonLink>
        </div>
      </Section>
    </AppShell>
  );
}

function PricingPreview() {
  useEffect(() => {
    track("pricing_viewed");
  }, []);

  return (
    <>
      <p className="ns-section-lead">
        Usage is measured in transcription minutes — not credits. Prices will be
        published when billing opens. Nothing here is a live checkout.
      </p>
      <div className="ns-plans">
        <article>
          <h3>Free</h3>
          <p>A small free allowance to try creating a score.</p>
        </article>
        <article className="is-featured">
          <h3>Creator</h3>
          <p>The primary plan for musicians who transcribe regularly.</p>
        </article>
        <article>
          <h3>Pro</h3>
          <p>A future plan for heavier or more advanced use.</p>
        </article>
      </div>
    </>
  );
}
