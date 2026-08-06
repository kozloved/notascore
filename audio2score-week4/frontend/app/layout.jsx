import "./globals.css";

export const metadata = {
  title: "NotaScore",
  description: "AI-powered audio to sheet music. Upload audio and receive MusicXML.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
