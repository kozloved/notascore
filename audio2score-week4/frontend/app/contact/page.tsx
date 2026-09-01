import LegalPage from "../../components/marketing/LegalPage";

export const metadata = {
  title: "Contact",
  description: "How to reach NotaScore.",
};

export default function ContactPage() {
  return (
    <LegalPage
      title="Contact"
      description="NotaScore is in private alpha and does not yet have a public support inbox."
    >
      <p>
        The best way to try NotaScore is to create a score from a recording. We will
        add a contact address when support is staffed — this page will not pretend
        that a mailbox exists today.
      </p>
    </LegalPage>
  );
}
