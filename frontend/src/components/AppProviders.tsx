"use client";

import "@/i18n";
import { AuthProvider } from "@/lib/auth";

export default function AppProviders({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}
