import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Ham Ninh AI Guide',
  description: 'Bilingual AI guide for Ham Ninh fishing village heritage and responsible tourism.'
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
