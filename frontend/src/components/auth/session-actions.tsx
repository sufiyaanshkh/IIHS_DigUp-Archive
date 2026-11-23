"use client";

import { useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AuthApiError, authApi } from "@/lib/auth-api";

export function SessionActions() {
  const session = useQuery({
    queryKey: ["auth-session"],
    queryFn: authApi.session,
    refetchInterval: 60_000,
    retry: false,
  });
  const logout = useMutation({
    mutationFn: () => authApi.logout(session.data?.csrfToken ?? ""),
    onSuccess: () => window.location.replace("/"),
  });

  useEffect(() => {
    if (session.error instanceof AuthApiError && session.error.status === 401) {
      window.location.replace("/");
    }
  }, [session.error]);

  return <div className="flex min-w-0 items-center gap-2">
    {session.data ? <span className="hidden max-w-36 truncate text-sm text-ink/70 lg:inline" title={session.data.display_name}>{session.data.display_name}</span> : null}
    <Button type="button" variant="ghost" size="small" disabled={!session.data || logout.isPending}
      onClick={() => logout.mutate()} aria-label="Sign out">
      <LogOut aria-hidden="true" className="size-4" /><span className="hidden sm:inline">Sign out</span>
    </Button>
    {logout.error ? <span role="alert" className="sr-only">{logout.error.message}</span> : null}
  </div>;
}
