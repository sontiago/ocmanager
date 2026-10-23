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
