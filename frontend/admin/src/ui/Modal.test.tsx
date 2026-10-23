import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { ConfirmDialog } from "./ConfirmDialog";
import { Modal } from "./Modal";

function WithModal() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>open</button>
      {open && (
        <Modal title="Диалог" onClose={() => setOpen(false)}>
          <input aria-label="first" />
          <button>middle</button>
          <button onClick={() => setOpen(false)}>last</button>
        </Modal>
      )}
    </>
  );
}

test("focus_moves_into_the_dialog_when_it_opens", async () => {
  const user = userEvent.setup();
  render(<WithModal />);
  await user.click(screen.getByRole("button", { name: "open" }));
  expect(screen.getByLabelText("first")).toHaveFocus();
});

test("tab_from_the_last_control_wraps_to_the_first", async () => {
  const user = userEvent.setup();
  render(<WithModal />);
  await user.click(screen.getByRole("button", { name: "open" }));
  screen.getByRole("button", { name: "last" }).focus();
  await user.tab();
  expect(screen.getByLabelText("first")).toHaveFocus();
});

test("shift_tab_from_the_first_control_wraps_to_the_last", async () => {
  const user = userEvent.setup();
  render(<WithModal />);
  await user.click(screen.getByRole("button", { name: "open" }));
  await user.tab({ shift: true });
  expect(screen.getByRole("button", { name: "last" })).toHaveFocus();
});

test("focus_cannot_leave_the_dialog_for_the_page_behind_it", async () => {
  const user = userEvent.setup();
  render(<WithModal />);
  await user.click(screen.getByRole("button", { name: "open" }));
  for (let i = 0; i < 6; i++) {
    await user.tab();
    expect(screen.getByRole("dialog")).toContainElement(document.activeElement as HTMLElement);
  }
});

test("closing_returns_focus_to_what_opened_the_dialog", async () => {
  const user = userEvent.setup();
  render(<WithModal />);
  const opener = screen.getByRole("button", { name: "open" });
  await user.click(opener);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(opener).toHaveFocus();
});

test("the_confirm_dialog_also_takes_and_returns_focus", async () => {
  const user = userEvent.setup();
  function Host() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>ask</button>
        <ConfirmDialog
          open={open}
          title="Точно?"
          confirmLabel="Да"
          onConfirm={() => setOpen(false)}
          onCancel={() => setOpen(false)}
        />
      </>
    );
  }
  render(<Host />);
  const opener = screen.getByRole("button", { name: "ask" });
  await user.click(opener);
  expect(screen.getByRole("dialog")).toContainElement(document.activeElement as HTMLElement);
  await user.keyboard("{Escape}");
  expect(opener).toHaveFocus();
});
