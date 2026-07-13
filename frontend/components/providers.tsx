"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setNonce } from "get-nonce";
import { useState } from "react";
import { ToastProvider } from "@/components/toast";

export function Providers({ children, nonce }: { children: React.ReactNode; nonce?: string }) {
  const [client] = useState(() => {
    if (nonce) setNonce(nonce);
    return new QueryClient({ defaultOptions: { queries: { retry: 1 } } });
  });
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  );
}
