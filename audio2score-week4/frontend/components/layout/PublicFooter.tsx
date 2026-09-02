import Link from "next/link";

import { PUBLIC_NAV } from "../../lib/site";
import Wordmark from "./Wordmark";

const PRODUCT = PUBLIC_NAV;
const RESOURCES = [
  { href: "/help", label: "Help" },
  { href: "/contact", label: "Contact" },
];
const LEGAL = [
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
  { href: "/cookies", label: "Cookies" },
];

export default function PublicFooter() {
  return (
    <footer className="ns-footer">
      <div className="ns-footer-inner">
        <div className="ns-footer-brand">
          <Wordmark href="/" />
          <p>Turn your music into a score.</p>
        </div>
        <div className="ns-footer-cols">
          <FooterCol title="Product" links={PRODUCT} />
          <FooterCol title="Resources" links={RESOURCES} />
          <FooterCol title="Legal" links={LEGAL} />
        </div>
      </div>
      <p className="ns-footer-copy">© 2026 NotaScore</p>
    </footer>
  );
}

function FooterCol({
  title,
  links,
}: {
  title: string;
  links: readonly { href: string; label: string }[];
}) {
  return (
    <div>
      <p className="ns-footer-title">{title}</p>
      <ul>
        {links.map((link) => (
          <li key={link.href}>
            <Link href={link.href}>{link.label}</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
