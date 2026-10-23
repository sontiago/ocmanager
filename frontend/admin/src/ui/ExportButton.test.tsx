import { render, screen } from "@testing-library/react";
import { ExportButton, exportUrl } from "./ExportButton";

test("exportUrl_builds_path_and_drops_empty_params", () => {
  expect(exportUrl("payments", { status: "refunded", since: undefined, q: "" })).toBe(
    "/admin/export/payments.csv?status=refunded",
  );
});

test("exportUrl_without_params_has_no_query", () => {
  expect(exportUrl("clients", {})).toBe("/admin/export/clients.csv");
});

test("exportUrl_encodes_values", () => {
  expect(exportUrl("clients", { q: "a&b c" })).toBe("/admin/export/clients.csv?q=a%26b+c");
});

test("button_is_a_download_link", () => {
  render(<ExportButton kind="audit" params={{ action: "client.block" }} />);
  const link = screen.getByRole("link", { name: "Экспорт CSV" });
  expect(link).toHaveAttribute("href", "/admin/export/audit.csv?action=client.block");
  expect(link).toHaveAttribute("download");
});
