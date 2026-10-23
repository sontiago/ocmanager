import { render, screen } from "@testing-library/react";
import en from "./en.json";
import { I18nProvider, useT } from "./index";
import ru from "./ru.json";

test("ru_and_en_have_identical_keys", () => {
  expect(Object.keys(en).sort()).toEqual(Object.keys(ru).sort());
});

function Probe({ k, vars }: { k: string; vars?: Record<string, string | number> }) {
  const { t } = useT();
  return <span>{t(k, vars)}</span>;
}

test("missing_key_returns_key", () => {
  render(<Probe k="no.such.key" />);
  expect(screen.getByText("no.such.key")).toBeInTheDocument();
});

test("vars_are_interpolated", () => {
  render(
    <I18nProvider dictionaries={{ ru: { hi: "Привет, {name}!" }, en: { hi: "Hi, {name}!" } }}>
      <Probe k="hi" vars={{ name: "Боб" }} />
    </I18nProvider>,
  );
  expect(screen.getByText("Привет, Боб!")).toBeInTheDocument();
});

test("language_persists_and_switches", () => {
  localStorage.setItem("ocm_lang", "en");
  render(
    <I18nProvider dictionaries={{ ru: { hi: "Привет" }, en: { hi: "Hi" } }}>
      <Probe k="hi" />
    </I18nProvider>,
  );
  expect(screen.getByText("Hi")).toBeInTheDocument();
  localStorage.clear();
});
