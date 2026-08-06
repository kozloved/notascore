import UploadPanel from "../components/UploadPanel";

export default function Home() {
  return (
    <main className="relative min-h-screen overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_20%_0%,#f7f1e4_0%,transparent_55%),radial-gradient(ellipse_at_90%_10%,#c9d7e8_0%,transparent_45%),linear-gradient(165deg,#eef3f8_0%,#d5deea_48%,#c3cfdc_100%)]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.22] animate-[stave_28s_linear_infinite]"
        style={{
          backgroundImage:
            "repeating-linear-gradient(0deg, transparent 0, transparent 26px, rgba(16,20,28,0.18) 26px, rgba(16,20,28,0.18) 27px)",
          backgroundSize: "100% 135px",
          maskImage:
            "linear-gradient(90deg, transparent 0%, black 18%, black 82%, transparent 100%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -right-24 top-16 h-[28rem] w-[28rem] rounded-full bg-[radial-gradient(circle,rgba(196,163,90,0.28),transparent_68%)] blur-2xl animate-[pulseSoft_2.4s_ease-in-out_infinite]"
      />

      <div className="relative mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16 sm:px-10">
        <p className="animate-[rise_0.7s_ease-out_both] font-display text-5xl font-semibold tracking-tight text-ink sm:text-7xl md:text-8xl">
          NotaScore
        </p>

        <h1 className="mt-5 max-w-2xl animate-[rise_0.7s_ease-out_0.08s_both] font-display text-2xl font-medium leading-snug text-score sm:text-3xl">
          Audio becomes editable sheet music.
        </h1>

        <p className="mt-4 max-w-lg animate-[rise_0.7s_ease-out_0.12s_both] text-base leading-relaxed text-slate sm:text-lg">
          Upload a performance. The NotaScore Transcription Engine returns
          MusicXML you can open, edit, and share.
        </p>

        <div className="mt-10">
          <UploadPanel />
        </div>
      </div>
    </main>
  );
}
