import LegalPage from "../../components/marketing/LegalPage";

export const metadata = {
  title: "Cookies",
  description: "What NotaScore stores in your browser.",
};

export default function CookiesPage() {
  return (
    <LegalPage
      title="Cookies"
      description="This version does not use advertising or analytics cookies."
    >
      <p>
        We store your theme preference in local storage so the interface can follow
        light, dark, or system. Sign-in sessions are handled by the authentication
        provider when it is configured.
      </p>
      <p>There is no cookie banner because there is no optional tracking to consent to.</p>
    </LegalPage>
  );
}
