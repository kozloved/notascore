import AppShell from "../../components/layout/AppShell";
import DemoPreview from "../../components/marketing/DemoPreview";
import ButtonLink from "../../components/ui/ButtonLink";
import { Display, Text } from "../../components/ui/Text";

export const metadata = {
  title: "Examples",
  description: "Hear a short recording and see the score NotaScore writes from it.",
};

export default function ExamplesPage() {
  return (
    <AppShell variant="public" width="wide">
      <p className="ns-kicker">Examples</p>
      <Display as="h1">See what NotaScore can do.</Display>
      <Text className="tagline" size="body-large">
        Play the recording, then read the score. This is a short piano figure
        transcribed by NotaScore — labelled as an example, not a concert
        performance.
      </Text>
      <div style={{ marginTop: 40 }}>
        <DemoPreview />
      </div>
      <div className="ns-page-cta">
        <ButtonLink href="/create">Create a score</ButtonLink>
      </div>
    </AppShell>
  );
}
