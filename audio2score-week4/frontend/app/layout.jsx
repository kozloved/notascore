import "./globals.css";
import { Instrument_Serif, Inter } from "next/font/google";

import { Providers } from "../components/providers";

const display = Instrument_Serif({
  subsets: ["latin"],
  weight: ["400"],
  style: ["normal", "italic"],
  variable: "--font-display",
  display: "swap",
});

const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata = {
  title: "NotaScore",
  description: "Turn your music into a score. From recordings to editable sheet music in minutes.",
};

const themeInitScript = `(function(){try{var t=localStorage.getItem('notascore-theme');var m=(t==='light'||t==='dark')?t:'system';var d=document.documentElement;d.setAttribute('data-theme',m);var dark=m==='dark'||(m!=='light'&&window.matchMedia('(prefers-color-scheme: dark)').matches);d.style.backgroundColor=dark?'#0B1018':'#F6F3EC';d.style.colorScheme=dark?'dark':'light';}catch(e){document.documentElement.setAttribute('data-theme','system');}})();`;

export default function RootLayout({ children }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${display.variable} ${sans.variable}`}
    >
      <body suppressHydrationWarning>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
        <a className="ns-skip" href="#main">
          Skip to content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
