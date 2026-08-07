"use client";

import { useEffect, useState } from "react";
import UploadPanel from "../components/UploadPanel";
import HeartbeatBackground from "../components/HeartbeatBackground";
import ThemeControls, { type Theme } from "../components/ThemeControls";

export default function Home() {
  const [theme, setTheme] = useState<Theme>("system");
  const [bpm, setBpm] = useState(72);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("notascore-theme");
      if (stored === "light" || stored === "dark" || stored === "system") {
        setTheme(stored);
      }
    } catch {
      // ignore
    }
  }, []);

  const changeTheme = (next: Theme) => {
    setTheme(next);
    try {
      localStorage.setItem("notascore-theme", next);
    } catch {
      // ignore
    }
    document.documentElement.setAttribute("data-theme", next);
  };

  return (
    <main className="relative min-h-screen overflow-hidden">
      <HeartbeatBackground bpm={bpm} />

      <div
        aria-hidden
        className="pointer-events-none absolute -right-24 top-16 z-[1] h-[28rem] w-[28rem] rounded-full bg-[radial-gradient(circle,rgba(196,163,90,0.28),transparent_68%)] blur-2xl animate-[pulseSoft_2.4s_ease-in-out_infinite]"
      />

      <div className="relative z-[2] mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16 sm:px-10">
        <ThemeControls
          theme={theme}
          bpm={bpm}
          onThemeChange={changeTheme}
          onBpmChange={setBpm}
        />

        <p className="animate-[rise_0.7s_ease-out_both] font-display text-5xl font-semibold tracking-tight text-ink sm:text-7xl md:text-8xl">
          NotaScore
          <span className="ml-1 inline-block align-baseline text-[1.05em] leading-none text-brass">
            ♪
          </span>
        </p>

        <h1 className="mt-5 max-w-2xl animate-[rise_0.7s_ease-out_0.08s_both] font-display text-2xl font-medium leading-snug text-score sm:text-3xl">
          Audio becomes editable sheet music.
        </h1>

        <p className="mt-4 max-w-lg animate-[rise_0.7s_ease-out_0.12s_both] text-base leading-relaxed text-slate sm:text-lg">
          Upload a performance. The NotaScore Transcription Engine returns
          MusicXML, MIDI, and PDF you can open, edit, and share.
        </p>

        <div className="mt-10">
          <UploadPanel />
        </div>
      </div>
    </main>
  );
}
