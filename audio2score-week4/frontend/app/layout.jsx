import "./globals.css";

export const metadata = {
  title: "NotaScore",
  description: "AI-powered audio to sheet music. Upload audio and receive MusicXML.",
};

// Set the theme before first paint to avoid a flash of the wrong theme.
const themeInitScript = `(function(){try{var t=localStorage.getItem('notascore-theme');document.documentElement.setAttribute('data-theme',(t==='light'||t==='dark')?t:'system');}catch(e){document.documentElement.setAttribute('data-theme','system');}})();`;

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
