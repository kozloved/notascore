export const metadata = {
  title: "Audio2Score MVP",
  description: "Upload audio and receive MusicXML.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          fontFamily: "Arial, sans-serif",
          background: "#fafafa",
        }}
      >
        {children}
      </body>
    </html>
  );
}
