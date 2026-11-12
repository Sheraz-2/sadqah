import { LinkButton } from "@/components/ui/Button";
import { Star } from "@/components/ui/Star";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center px-4 py-24 text-center sm:px-6">
      <Star className="size-16 text-saffron-400" lit={false} />
      <h1 className="mt-6 text-5xl font-bold">We could not find that page</h1>
      <p className="mt-4 text-lg text-ink-soft">The link may be old or mistyped. Here are some places to start.</p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <LinkButton href="/">Go home</LinkButton>
        <LinkButton href="/campaigns" variant="secondary">
          Browse campaigns
        </LinkButton>
      </div>
    </div>
  );
}
