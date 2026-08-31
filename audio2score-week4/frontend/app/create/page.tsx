import AppShell from "../../components/layout/AppShell";
import CreateScorePanel from "../../components/CreateScorePanel";
import { Display, Text } from "../../components/ui/Text";

export const metadata = {
  title: "Create a score",
  description: "Upload a recording and turn it into editable sheet music.",
};

export default function CreatePage() {
  return (
    <AppShell variant="app" width="default">
      <Display as="h1">Create a score</Display>
      <Text className="tagline">Choose a recording. We’ll write the notation.</Text>
      <div className="mt-8" style={{ marginTop: 32 }}>
        <CreateScorePanel />
      </div>
    </AppShell>
  );
}
