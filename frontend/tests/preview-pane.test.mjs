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

test("document excerpts expand and collapse without changing photography details", () => {
  let expanded = false;
  let stateIndex = 0;
  const { PreviewPane } = loadSource("src/components/archive/preview-pane.tsx", {
    react: {
      useState: (initial) => {
        const index = stateIndex++;
        return [index === 4 ? expanded : initial, (update) => { if (index === 4) expanded = update(expanded); }];
      },
    },
    "@/lib/archive-types": { formatBytes: String },
    "@/lib/archive-api": { archiveApi: {}, ArchiveApiError: class ArchiveApiError extends Error {} },
    "@/components/ui/button": { Button: () => null },
  });
  const result = { id: "one", name: "sample.pdf", folder: "Archive", kind: "document",
                   details: "Document", excerpt: "One\nTwo\nThree\nFour" };
  const props = { result, metadataLoading: false, metadataError: null,
                  imageMetadataLoading: false, imageMetadataError: null };
  const render = () => { stateIndex = 0; return PreviewPane(props); };
  let button = find(render(), (node) => node.props?.["aria-expanded"] === false);
  assert.equal(button.props.children, "Show full excerpt");
  button.props.onClick();
  button = find(render(), (node) => node.props?.["aria-expanded"] === true);
  assert.equal(button.props.children, "Show less");
  button.props.onClick();
  assert.equal(expanded, false);
  stateIndex = 0;
  const photo = PreviewPane({ ...props, result: { ...result, kind: "image" } });
  assert.equal(find(photo, (node) => node.props?.["aria-expanded"] !== undefined), null);
});
