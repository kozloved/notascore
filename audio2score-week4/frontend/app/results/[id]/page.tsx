"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

export default function ResultRedirectPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id;

  useEffect(() => {
    if (id) router.replace(`/score/${id}`);
  }, [id, router]);

  return <p className="ns-text ns-tone-muted">Opening your score…</p>;
}
