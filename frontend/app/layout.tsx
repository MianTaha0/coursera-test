import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Droply — eBay Dropshipping Automation",
  description:
    "Import Amazon products to eBay in one click. Automate price monitoring, fulfillment, and buyer messages.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-white">{children}</body>
    </html>
  );
}
