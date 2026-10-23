import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfirmDialog } from "./ConfirmDialog";

function show(props: Partial<React.ComponentProps<typeof ConfirmDialog>> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      open
      title="Заблокировать?"
      body="Клиент потеряет доступ"
      confirmLabel="Заблокировать"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...props}
    />,
  );
  return { onConfirm, onCancel };
}

test("renders_nothing_when_closed", () => {
  show({ open: false });
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("confirm_calls_handler", async () => {
  const { onConfirm } = show();
  await userEvent.click(screen.getByRole("button", { name: "Заблокировать" }));
  expect(onConfirm).toHaveBeenCalledTimes(1);
});

test("confirm_button_disabled_while_pending", async () => {
  const { onConfirm } = show({ pending: true });
  const button = screen.getByRole("button", { name: "Заблокировать" });
  expect(button).toBeDisabled();
  await userEvent.click(button);
  expect(onConfirm).not.toHaveBeenCalled();
});

test("escape_cancels", async () => {
  const { onCancel } = show();
  await userEvent.keyboard("{Escape}");
  expect(onCancel).toHaveBeenCalledTimes(1);
});
