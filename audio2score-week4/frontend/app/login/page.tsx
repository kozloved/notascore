import AuthButton from "../../components/AuthButton";
import AppShell from "../../components/layout/AppShell";
import { Display, Text } from "../../components/ui/Text";

export default function LoginPage() {
  return (
    <AppShell variant="public" width="narrow">
      <Display>Welcome back.</Display>
      <Text className="tagline">
        Continue to your scores, or start a new one from a recording.
      </Text>
      <div className="mt-8 flex justify-center">
        <AuthButton />
      </div>
    </AppShell>
  );
}
