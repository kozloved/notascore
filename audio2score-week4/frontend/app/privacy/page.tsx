import LegalPage from "../../components/marketing/LegalPage";

export const metadata = {
  title: "Privacy",
  description: "How NotaScore handles information on this workspace.",
};

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy"
      description="A short notice for this early product — not a substitute for a later legal review."
    >
      <p>
        Recordings you upload are sent to the NotaScore service so a score can be
        written. We do not add advertising or third-party analytics cookies in this
        version.
      </p>
      <p>
        If you create an account, email and sign-in are handled by the configured
        authentication provider. Theme preference is stored only on your device.
      </p>
    </LegalPage>
  );
}
