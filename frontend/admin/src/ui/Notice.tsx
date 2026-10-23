export function Notice({ text, tone = "ok" }: { text: string | null; tone?: "ok" | "danger" }) {
  if (!text) return null;
  return (
    <p
      role={tone === "danger" ? "alert" : "status"}
      className={`rounded-md border p-2 ${tone === "danger" ? "border-danger text-danger" : "border-ok text-ok"}`}
    >
      {text}
    </p>
  );
}
