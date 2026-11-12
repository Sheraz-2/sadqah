import type { Metadata } from "next";
import Link from "next/link";
import { CopyEmail } from "@/components/contact/CopyEmail";
import { Card } from "@/components/ui/Card";
import { buttonClass } from "@/components/ui/Button";
import { SUPPORT_EMAIL, SUPPORT_MAILTO } from "@/lib/contact";

export const metadata: Metadata = {
  title: "Contact us",
  description: `Email SadQah support at ${SUPPORT_EMAIL}. What to include, and what never to send by email.`,
};

function Block({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-2">
      <h2 id={id} className="font-display text-2xl font-semibold text-lapis-900">{title}</h2>
      <div className="space-y-2 text-lg leading-relaxed text-ink">{children}</div>
    </section>
  );
}

export default function ContactPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-10 px-4 py-12 sm:px-6">
      <header>
        <h1 className="font-display text-4xl font-bold text-lapis-900 sm:text-5xl">Contact us</h1>
        <p className="mt-3 text-xl text-ink-soft">
          Stuck, worried about something, or need a person to look at your case? Write to SadQah support by email. We are glad to hear from you.
        </p>
      </header>

      <Card className="space-y-4 p-6 sm:p-8">
        <h2 className="font-display text-2xl font-semibold text-lapis-900">Support email</h2>
        <p className="break-words font-display text-xl font-bold text-lapis-900 min-[400px]:text-2xl sm:text-3xl">
          <a href={SUPPORT_MAILTO} className="underline decoration-saffron-400 decoration-2 underline-offset-4 hover:text-lapis-700">
            {SUPPORT_EMAIL}
          </a>
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <a href={SUPPORT_MAILTO} className={buttonClass("primary", "lg")}>Write an email</a>
          <CopyEmail />
        </div>
        <p className="text-base text-ink-soft">
          &ldquo;Write an email&rdquo; opens a new message in your own email app with the subject filled in. Nothing is sent until you press Send there.
          If no email app opens, copy the address and write from any email account.
        </p>
      </Card>

      <Block id="include" title="Help us understand quickly">
        <ul className="list-disc space-y-1 pl-6">
          <li>Say what you were trying to do and what happened instead, in your own words and any language you like.</li>
          <li>Mention the page (for example Settings or Verification) and roughly when it happened.</li>
          <li>Tell us which kind of account you have (giving or grant) and the email address you signed up with.</li>
          <li>For a question about a gift, give the campaign name, the approximate date and the amount. Keep your Donation Token to yourself.</li>
          <li>Include error messages exactly as they appeared. A screenshot is fine if it shows no private details.</li>
        </ul>
      </Block>

      <section aria-labelledby="privacy" className="rounded-2xl bg-pomegranate-500/10 p-6 ring-1 ring-pomegranate-500/30">
        <h2 id="privacy" className="font-display text-2xl font-semibold text-lapis-900">Please never email these</h2>
        <ul className="mt-2 list-disc space-y-1 pl-6 text-lg leading-relaxed text-ink">
          <li>Your password, or the one-time code we send you to reset it.</li>
          <li>Card numbers, or your PayPal or bank login details.</li>
          <li>Photos or scans of identity documents. Verification documents are uploaded only inside your Verification page, never by email.</li>
        </ul>
        <p className="mt-3 text-base text-ink-soft">Email is not a private channel. SadQah will never ask you for these things by email, so treat any message that does as a scam.</p>
      </section>

      <Block id="notes" title="Good to know">
        <ul className="list-disc space-y-1 pl-6">
          <li>Email is the only way to contact us in this version. There is no phone line, live chat or contact form, and the AI assistant cannot send messages for you.</li>
          <li>We cannot promise how quickly someone will reply.</li>
          <li>To report a story that looks fake, use the <strong>Report this campaign</strong> button on that campaign page.</li>
          <li>Questions about fees, refunds and timing are explained on <Link href="/trust" className="font-semibold text-lapis-700 underline underline-offset-2">Trust &amp; transparency</Link>.</li>
        </ul>
      </Block>
    </div>
  );
}
