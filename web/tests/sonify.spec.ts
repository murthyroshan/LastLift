import { expect, test } from "@playwright/test";
import { chord } from "../src/sonify";

// Pure mapping: voices = routes (the certified k); closing a lift drops exactly the routes that use it.
test("chord: one voice per route, drops follow the closed lift", () => {
  const routes = [{ label: "A", lifts: ["813"] }, { label: "B", lifts: ["961", "814"] }];
  const open = chord(routes);
  expect(open.voices.length).toBe(2);
  expect(open.active).toBe(2);
  expect(open.tremolo).toBe(false);
  const one = chord(routes, ["961"]);
  expect(one.voices.filter((v) => v.active).map((v) => v.label)).toEqual(["A"]);
  expect(one.tremolo).toBe(true);
  const none = chord(routes, ["813", "814"]);
  expect(none.active).toBe(0);
  expect(none.earcon).toBe(true);
  expect(chord([{ label: "A", lifts: ["885"] }], ["999"]).active).toBe(1);
});
