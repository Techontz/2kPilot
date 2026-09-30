import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 px-4 text-center">
      <p className="num text-sm text-fg-subtle">404</p>
      <h1 className="text-lg font-semibold">Page not found</h1>
      <Link href="/" className="text-sm text-accent hover:underline">
        Back to Overview
      </Link>
    </main>
  );
}
