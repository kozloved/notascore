"use client";

import Link from "next/link";

export default function Wordmark({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="ns-wordmark">
      NotaScore
    </Link>
  );
}
