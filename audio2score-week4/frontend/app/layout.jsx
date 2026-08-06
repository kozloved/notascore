import "./globals.css";

export const metadata = {
  title: "NotaScore",
  description: "AI-powered audio to sheet music. Upload audio and receive MusicXML.",
};

// Set the theme (and a matching background) before first paint to avoid a
// flash of the wrong theme on load/reload.
const themeInitScript = `(function(){try{var t=localStorage.getItem('notascore-theme');var m=(t==='light'||t==='dark')?t:'system';var d=document.documentElement;d.setAttribute('data-theme',m);var dark=m==='dark'||(m!=='light'&&window.matchMedia('(prefers-color-scheme: dark)').matches);d.style.backgroundColor=dark?'#0b0d12':'#f6f7f9';d.style.colorScheme=dark?'dark':'light';}catch(e){d&&d.setAttribute('data-theme','system');}})();`;

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
        {children}
      </body>
    </html>
  );
}
