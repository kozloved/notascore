import LegalPage from "../../components/marketing/LegalPage";

export const metadata = {
  title: "Contact",
  description: "How to reach NotaScore.",
};

export default function ContactPage() {
  return (
    <LegalPage
      title="Contact"
      description="This early workspace does not yet have a public support inbox."
    >
      <p>
        For product issues, use the project repository. We will add a contact
        address when support is staffed — this page will not pretend that a mailbox
        exists today.
      </p>
    </LegalPage>
  );
}
