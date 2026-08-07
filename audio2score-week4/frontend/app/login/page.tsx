"use client";

import AuthButton from "../../components/AuthButton";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#dfe7f1] px-6">
      <div className="w-full max-w-md text-center">
        <p className="font-display text-4xl font-semibold text-ink">NotaScore</p>
        <h1 className="mt-4 font-display text-2xl text-score">Sign in</h1>
        <p className="mt-2 text-slate">Continue to your transcription workspace.</p>
        <div className="mt-8 flex justify-center">
          <AuthButton />
        </div>
      </div>
    </main>
  );
}
