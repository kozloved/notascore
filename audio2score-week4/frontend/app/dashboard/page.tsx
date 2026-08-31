import AppShell from "../../components/layout/AppShell";
import UploadPanel from "../../components/UploadPanel";
import Card from "../../components/ui/Card";
import { Display, Text } from "../../components/ui/Text";

export default function Dashboard() {
  return (
    <AppShell variant="app" width="default">
      <Display>My Scores</Display>
      <Text className="tagline">
        Upload a recording and follow it through to an editable score.
      </Text>
      <div className="mt-8">
        <Card>
          <UploadPanel />
        </Card>
      </div>
    </AppShell>
  );
}
