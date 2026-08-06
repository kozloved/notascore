import UploadPanel from "../../components/UploadPanel";

export default function Dashboard() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-[#dfe7f1] px-6 py-16">
      <div className="relative mx-auto max-w-3xl">
        <p className="font-display text-4xl font-semibold text-ink">NotaScore</p>
        <h1 className="mt-3 font-display text-2xl text-score">Dashboard</h1>
        <p className="mt-2 text-slate">
          Upload audio and track transcription progress.
        </p>
        <div className="mt-10">
          <UploadPanel />
        </div>
      </div>
    </main>
  );
}
