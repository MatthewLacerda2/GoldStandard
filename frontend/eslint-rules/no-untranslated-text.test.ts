import { createTester } from "./tester";
import { noUntranslatedText } from "./no-untranslated-text";

const tester = createTester();

tester.run("no-untranslated-text", noUntranslatedText, {
  valid: [
    {
      // Translated children go through an expression container.
      code: `const x = <p>{t("items.heading")}</p>;`,
      filename: "src/routes/items.tsx",
    },
    {
      // Dynamic content is not the rule's business either.
      code: `const x = <span>{item.name}</span>;`,
      filename: "src/routes/items.tsx",
    },
    {
      // Separators carry no letters, so there is nothing to translate.
      code: `const x = <span>·</span>;`,
      filename: "src/routes/items.tsx",
    },
    {
      code: `const x = <p>{a} — {b} / {c}: 42</p>;`,
      filename: "src/routes/items.tsx",
    },
    {
      code: `const x = <span>&nbsp;&mdash;</span>;`,
      filename: "src/routes/items.tsx",
    },
    {
      code: `const x = <Input placeholder={t("items.namePlaceholder")} />;`,
      filename: "src/routes/items.tsx",
    },
    {
      // Non-user-facing attributes are untouched — the rule allowlists.
      code: `const x = <label className="text-body" htmlFor="name" id="lbl">{t("a")}</label>;`,
      filename: "src/routes/items.tsx",
    },
    {
      // Empty alt is the a11y idiom for a decorative image.
      code: `const x = <img src={logo} alt="" />;`,
      filename: "src/routes/items.tsx",
    },
    {
      // components/ui is vendored shadcn code; exempt.
      code: `const x = <p title="Close">Close</p>;`,
      filename: "src/components/ui/tooltip.tsx",
    },
  ],
  invalid: [
    {
      code: `const x = <span>Save</span>;`,
      filename: "src/routes/items.tsx",
      errors: [{ messageId: "untranslatedText" }],
    },
    {
      code: `const x = <p>Items: {count}</p>;`,
      filename: "src/routes/items.tsx",
      errors: [{ messageId: "untranslatedText" }],
    },
    {
      code: `const x = <Input placeholder="Name" />;`,
      filename: "src/routes/items.tsx",
      errors: [{ messageId: "untranslatedAttribute" }],
    },
    {
      code: `const x = <Input placeholder={"Name"} />;`,
      filename: "src/routes/items.tsx",
      errors: [{ messageId: "untranslatedAttribute" }],
    },
    {
      code: `const x = <button aria-label="Delete item" title="Delete" />;`,
      filename: "src/routes/items.tsx",
      errors: [
        { messageId: "untranslatedAttribute" },
        { messageId: "untranslatedAttribute" },
      ],
    },
    {
      code: `const x = <img src={logo} alt="Company logo" />;`,
      filename: "src/routes/items.tsx",
      errors: [{ messageId: "untranslatedAttribute" }],
    },
  ],
});
