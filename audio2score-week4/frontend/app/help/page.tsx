import LegalPage from "../../components/marketing/LegalPage";

export const metadata = {
  title: "Help",
  description: "How to create a score with NotaScore.",
};

export default function HelpPage() {
  return (
    <LegalPage title="Help" description="Short answers while the product is still early.">
      <h2>How do I create a score?</h2>
      <p>
        Choose Create a score, upload an audio or MIDI file, and wait while NotaScore
        writes the notation. You can then download PDF, MIDI, or MusicXML.
      </p>
      <h2>Do I need an account?</h2>
      <p>
        You can create a score without signing in. An account keeps your scores in
        My Scores.
      </p>
      <h2>Which files work?</h2>
      <p>WAV, MP3, M4A, FLAC, or MIDI, up to 25 MB.</p>
    </LegalPage>
  );
}
