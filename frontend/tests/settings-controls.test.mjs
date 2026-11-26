import test from "node:test";
import assert from "node:assert/strict";
import { loadSource } from "./source-loader.mjs";

function find(element, predicate) {
  if (!element || typeof element !== "object") return null;
  if (predicate(element)) return element;
  for (const child of [element.props?.children].flat(Infinity)) {
    const found = find(child, predicate);
    if (found) return found;
  }
  return null;
}

test("removing a root requires confirmation and does not start indexing", () => {
  const data = { folders: { roots: [{ id: "one", name: "Archive", location: "Drive", relative_path: ".", available: true }],
                            excluded_folders: [], excluded_extensions: [] } };
  const states = ["folders", data, null, [], false, false, null, null, null];
  const calls = [];
  const { SettingsShell } = loadSource("src/components/settings/settings-shell.tsx", {
    react: {
      useState: (initial) => [states.length ? states.shift() : initial, () => {}],
      useEffect: () => {},
      useCallback: (fn) => fn,
    },
    "@/components/ui/button": { Button: () => null },
    "@/lib/settings-api": { settingsApi: { removeRoot: (...args) => { calls.push(args); } } },
    "@/components/auth/session-actions": { SessionActions: () => null },
  });
  const tree = SettingsShell();
  const panel = find(tree, (node) => node.type?.name === "FoldersPanel");
  const children = panel.type({ ...panel.props, onChange: (operation) => operation() });
  const roots = find(children, (node) => node.type?.name === "LocationList" && node.props.confirmRootRemoval);
  const list = roots.type(roots.props);
  const remove = find(list, (node) => node.props?.["aria-label"] === "Remove Archive");
  const originalWindow = global.window;
  let message = "";
  try {
    global.window = { confirm: (text) => { message = text; return false; } };
    remove.props.onClick();
    assert.deepEqual(calls, []);
    assert.match(message, /external indexing run may remove index records/);
    global.window.confirm = () => true;
    remove.props.onClick();
    assert.deepEqual(calls, [["folders", "one"]]);
  } finally {
    if (originalWindow === undefined) delete global.window;
    else global.window = originalWindow;
  }
});
