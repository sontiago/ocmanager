import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataTable } from "./DataTable";
import { Pagination } from "./Pagination";

const columns = [
  { key: "id", header: "ID", render: (r: { id: number }) => r.id },
];

test("renders_rows", () => {
  render(<DataTable columns={columns} rows={[{ id: 7 }]} rowKey={(r) => r.id} />);
  expect(screen.getByText("7")).toBeInTheDocument();
});

test("shows_empty_text", () => {
  render(<DataTable columns={columns} rows={[]} rowKey={(r) => r.id} emptyText="Пусто" />);
  expect(screen.getByText("Пусто")).toBeInTheDocument();
});

test("shows_error_state", () => {
  render(<DataTable columns={columns} rows={undefined} rowKey={(r) => r.id} error="boom" />);
  expect(screen.getByRole("alert")).toHaveTextContent("boom");
});

test("shows_loading_state", () => {
  render(<DataTable columns={columns} rows={undefined} rowKey={(r) => r.id} loading />);
  expect(screen.getByText(/Загрузка/)).toBeInTheDocument();
});

test("pagination_next_and_prev", async () => {
  const onChange = vi.fn();
  render(<Pagination total={120} limit={50} offset={50} onChange={onChange} />);
  await userEvent.click(screen.getByRole("button", { name: "Вперёд" }));
  expect(onChange).toHaveBeenLastCalledWith(100);
  await userEvent.click(screen.getByRole("button", { name: "Назад" }));
  expect(onChange).toHaveBeenLastCalledWith(0);
});

test("pagination_disabled_at_edges", () => {
  render(<Pagination total={10} limit={50} offset={0} onChange={() => {}} />);
  expect(screen.getByRole("button", { name: "Назад" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Вперёд" })).toBeDisabled();
});


test("clickable_rows_are_reachable_and_activate_from_the_keyboard", async () => {
  const onRowClick = vi.fn();
  render(
    <DataTable columns={columns} rows={[{ id: 7 }]} rowKey={(r) => r.id} onRowClick={onRowClick} />,
  );
  const row = screen.getByText("7").closest("tr")!;
  expect(row).toHaveAttribute("tabindex", "0");
  await userEvent.tab(); // шапка не фокусируется: первый Tab попадает на строку
  expect(row).toHaveFocus();
  await userEvent.keyboard("{Enter}");
  expect(onRowClick).toHaveBeenCalledWith({ id: 7 });
  await userEvent.keyboard(" ");
  expect(onRowClick).toHaveBeenCalledTimes(2);
});

test("rows_without_a_handler_are_not_focusable", () => {
  render(<DataTable columns={columns} rows={[{ id: 7 }]} rowKey={(r) => r.id} />);
  expect(screen.getByText("7").closest("tr")).not.toHaveAttribute("tabindex");
});
