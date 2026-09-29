import type { Metadata } from "next";
import { JetBrains_Mono, Sora } from "next/font/google";
import "./globals.css";

const sora = Sora({ subsets: ["latin"], variable: "--font-sora", display: "swap" });
const jb = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jb", display: "swap" });

export const metadata: Metadata = {
  title: "AxioNex — autonomous commerce intelligence",
  description: "Multi-agent pricing, inventory and risk decisions for D2C brands. Designed and developed by NIKHIL CHARY SRIRAMOJU.",
  authors: [{ name: "NIKHIL CHARY SRIRAMOJU", url: "https://github.com/Nikhil-creat" }],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sora.variable} ${jb.variable}`}>
      <body className="min-h-screen font-display">{children}</body>
    </html>
  );
}
