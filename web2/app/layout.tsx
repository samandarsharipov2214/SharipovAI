import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'SharipoAI — AI Trading OS',
  description: 'Autonomous AI trading mission control',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
