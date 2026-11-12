import Link from "next/link";
import { Logo } from "./Header";

export function Footer() {
  return (
    <footer className="mt-24 bg-lapis-900 text-lapis-100">
      <div className="pattern-stars">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr]">
          <div>
            <Logo className="text-white" />
            <p className="mt-4 max-w-sm text-lapis-100/90">
              <span lang="ar" dir="rtl" className="font-arabic text-2xl text-saffron-400">
                صدقة
              </span>{" "}
              is Arabic for giving that is sincere. SadQah sends small, verified grants to people who live on less than $50 a month.
            </p>
          </div>
          <nav aria-label="Explore" className="space-y-2">
            <p className="font-display text-lg font-semibold text-white">Explore</p>
            <Link className="block hover:text-white" href="/campaigns">Campaigns</Link>
            <Link className="block hover:text-white" href="/about">About SadQah</Link>
            <Link className="block hover:text-white" href="/leaderboard">Leaderboard</Link>
            <Link className="block hover:text-white" href="/track">Track a gift</Link>
            <Link className="block hover:text-white" href="/trust">Trust &amp; transparency</Link>
            <Link className="block hover:text-white" href="/contact">Contact us</Link>
            <Link className="block hover:text-white" href="/settings">Settings</Link>
          </nav>
          <nav aria-label="Join" className="space-y-2">
            <p className="font-display text-lg font-semibold text-white">Join</p>
            <Link className="block hover:text-white" href="/register?role=donor">Create a giving account</Link>
            <Link className="block hover:text-white" href="/register?role=recipient">Apply for a grant</Link>
            <Link className="block hover:text-white" href="/login">Sign in</Link>
          </nav>
        </div>
        <div className="border-t border-white/10">
          <p className="mx-auto max-w-6xl px-4 py-5 text-sm text-lapis-100/80 sm:px-6">
            Hackathon build running on the PayPal Developer Sandbox: no real money moves. Sadaqah is voluntary and is not a substitute for Zakat.
          </p>
        </div>
      </div>
    </footer>
  );
}
