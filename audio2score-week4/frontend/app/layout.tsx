import type { Metadata } from "next";
import { Fraunces, Outfit } from "next/font/google";
import "./globals.css";

const display = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const sans = Outfit({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "NotaScore AI",
  description: "Upload audio. Get editable sheet music.",
};

// Set the theme (and a matching background) before first paint to avoid a
// flash of the wrong theme on load/reload.
const themeInitScript = `(function(){try{var t=localStorage.getItem('notascore-theme');var m=(t==='light'||t==='dark')?t:'system';var d=document.documentElement;d.setAttribute('data-theme',m);var dark=m==='dark'||(m!=='light'&&window.matchMedia('(prefers-color-scheme: dark)').matches);d.style.backgroundColor=dark?'#0b0d12':'#dfe7f1';d.style.colorScheme=dark?'dark':'light';}catch(e){}})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${display.variable} ${sans.variable}`}
    >
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
        {children}
      </body>
    </html>
  );
}
