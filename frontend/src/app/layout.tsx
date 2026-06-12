import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Bless — Spend Auditor",
  description: "Find every dollar of wasted SaaS spend.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
