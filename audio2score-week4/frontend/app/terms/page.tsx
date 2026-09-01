import LegalPage from "../../components/marketing/LegalPage";

export const metadata = {
  title: "Terms",
  description: "Terms of use for this early NotaScore product.",
};

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms"
      description="Simple terms for an early product. They will be replaced before a public commercial launch."
    >
      <p>
        NotaScore is offered as an early transcription tool. Scores are a starting
        point for your own work. Do not rely on NotaScore for legal, archival,
        or guaranteed-accuracy use.
      </p>
      <p>You are responsible for having the right to upload the recordings you send.</p>
    </LegalPage>
  );
}
