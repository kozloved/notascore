import AppShell from "../../components/layout/AppShell";
import ButtonLink from "../../components/ui/ButtonLink";
import { Display, Text } from "../../components/ui/Text";

export const metadata = {
  title: "How it works",
  description: "Upload a recording. NotaScore writes a score you can review and export.",
};

const STEPS = [
  {
    n: "01",
    title: "Choose a recording",
    body: "Upload a recording of your music. Audio or MIDI, as you have it.",
  },
  {
    n: "02",
    title: "NotaScore listens",
    body: "NotaScore finds the notes, rhythm and musical structure.",
  },
  {
    n: "03",
    title: "Get your score",
    body: "Review the notation and download PDF, MIDI or MusicXML.",
  },
];

export default function HowItWorksPage() {
  return (
    <AppShell variant="public" width="wide">
      <p className="ns-kicker">Product</p>
      <Display as="h1">How it works</Display>
      <Text className="tagline" size="body-large">
        Three steps. No studio jargon.
      </Text>
      <ol className="ns-steps" style={{ marginTop: 48 }}>
        {STEPS.map((step) => (
          <li key={step.n} className="ns-step">
            <span className="how-index">{step.n}</span>
            <h2>{step.title}</h2>
            <p>{step.body}</p>
          </li>
        ))}
      </ol>
      <div className="ns-page-cta">
        <ButtonLink href="/create">Create a score</ButtonLink>
      </div>
    </AppShell>
  );
}
