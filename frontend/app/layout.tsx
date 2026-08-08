import type { Metadata } from "next";
import { Archivo, IBM_Plex_Mono, Inter } from "next/font/google";
import "./globals.css";

/**
 * Three roles, three faces.
 *
 * Archivo carries the display weight — a grotesque with real width at heavy
 * weights, closer to vehicle signage than to a neutral UI face. Inter does
 * the reading. Plex Mono sets every figure in the interface, which is what
 * makes the whole thing read as a specification rather than a chat log.
 */

const archivo = Archivo({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-archivo",
  display: "swap",
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Car Matchmaker",
  description:
    "Tell it what you need. It interviews you, searches real listings, and shows its reasoning.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${archivo.variable} ${inter.variable} ${plexMono.variable}`}
      style={
        {
          "--font-display": "var(--font-archivo)",
          "--font-body": "var(--font-inter)",
          "--font-mono": "var(--font-plex-mono)",
        } as React.CSSProperties
      }
    >
      <body>{children}</body>
    </html>
  );
}
