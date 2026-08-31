"use client";

import { useEffect } from "react";

import { track } from "../../lib/analytics";
import AppShell from "../../components/layout/AppShell";
import ButtonLink from "../../components/ui/ButtonLink";
import { Display, Text } from "../../components/ui/Text";

export default function PricingPage() {
  useEffect(() => {
    track("pricing_viewed");
  }, []);

  return (
    <AppShell variant="public" width="wide">
      <p className="ns-kicker">Pricing</p>
      <Display as="h1">Plans, when you need them.</Display>
      <Text className="tagline" size="body-large">
        Usage will be measured in transcription minutes. We have not published
        prices yet — this page describes the structure, not a live checkout.
      </Text>
      <div className="ns-plans" style={{ marginTop: 40 }}>
        <article>
          <h2>Free</h2>
          <p>A small free allowance to try creating a score.</p>
        </article>
        <article className="is-featured">
          <h2>Creator</h2>
          <p>The primary plan for musicians who transcribe regularly.</p>
        </article>
        <article>
          <h2>Pro</h2>
          <p>A future plan for heavier or more advanced use.</p>
        </article>
      </div>
      <div className="ns-page-cta">
        <ButtonLink href="/create">Create a score</ButtonLink>
      </div>
    </AppShell>
  );
}
