import test from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
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
      useRef: () => ({ current: null }),
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
  assert.ok(find(photo, (node) => node.props?.["aria-expanded"] === false));
  assert.ok(find(photo, (node) => node.props?.["aria-label"] === "Photography metadata"));
});

  function renderFixture(result, players = {}) {
    const states = [];
    let stateIndex = 0;
    let refIndex = 0;
    const { PreviewPane } = loadSource("src/components/archive/preview-pane.tsx", {
      react: {
        useRef: () => ({ current: refIndex++ === 0 ? players.video ?? null : players.audio ?? null }),
        useState: (initial) => {
          const index = stateIndex++;
          if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
          return [states[index], (update) => { states[index] = typeof update === "function" ? update(states[index]) : update; }];
        },
      },
      "next/image": { __esModule: true, default: "img" },
      "@/lib/archive-types": { formatBytes: String },
      "@/lib/archive-api": { archiveApi: { mediaStreamUrl: (id) => `/api/media/${id}/stream` },
                              ArchiveApiError: class ArchiveApiError extends Error {} },
      "@/components/ui/button": { Button: () => null },
    });
    return () => {
      stateIndex = 0;
      refIndex = 0;
      return PreviewPane({ result, metadataLoading: false, metadataError: null,
                           imageMetadataLoading: false, imageMetadataError: null });
    };
  }

  test("match explanations are visible for every preview kind", () => {
    for (const kind of ["image", "screenshot", "video", "audio", "document", "code"]) {
      const reason = `Reason for ${kind}`;
      const tree = renderFixture({ id: kind, name: "fixture", folder: "Archive", kind, reason })();
      assert.ok(find(tree, (node) => node.type === "p" && node.props?.children === reason), kind);
    }
  });

  test("excerpt markers render as bold text with Desktop delimiter behavior", () => {
    const cases = [
      ["Plain text", "Plain text", []],
      ["Before «one» and «two words» after", "Before one and two words after", ["one", "two words"]],
      ["বাংলা «নদী» العربية «النهر» 日本語", "বাংলা নদী العربية النهر 日本語", ["নদী", "النهر"]],
      ["»start «unfinished", "start unfinished", ["unfinished"]],
      ["a «first «second» tail» end", "a first second tail end", ["first ", "second"]],
      ["«»ordinary", "ordinary", []],
    ];
    for (const [excerpt, expectedText, expectedBold] of cases) {
      const tree = renderFixture({ id: "doc", name: "fixture", folder: "Archive", kind: "document", excerpt })();
      const paragraph = find(tree, (node) => node.type === "p" && node.props?.className?.includes("whitespace-pre-wrap"));
      assert.ok(paragraph);
      const children = [paragraph.props.children].flat(Infinity);
      assert.equal(children.map((child) => typeof child === "string" ? child : child.props.children).join(""), expectedText);
      assert.deepEqual(children.filter((child) => child?.type === "strong").map((child) => child.props.children), expectedBold);
    }
  });

  test("excerpt content is escaped as text rather than interpreted as HTML", () => {
    const excerpt = 'Before «<img src=x onerror=alert(1)>» <script>alert("x")</script>';
    const tree = renderFixture({ id: "doc", name: "fixture", folder: "Archive", kind: "document", excerpt })();
    const paragraph = find(tree, (node) => node.type === "p" && node.props?.className?.includes("whitespace-pre-wrap"));
    const html = renderToStaticMarkup(paragraph);
    assert.match(html, /<strong[^>]*>&lt;img src=x onerror=alert\(1\)&gt;<\/strong>/);
    assert.match(html, /&lt;script&gt;alert\(&quot;x&quot;\)&lt;\/script&gt;/);
    assert.doesNotMatch(html, /<(?:script|img)\b/);
  });

  test("Desktop-supported media show existing excerpts and retain expansion controls", () => {
    for (const [kind, engineKind] of [
      ["document", "doc"], ["document", "pdf"], ["image", "image"], ["screenshot", "screenshot"],
      ["video", "video"], ["audio", "audio"], ["code", "code"],
    ]) {
      const render = renderFixture({ id: engineKind, name: "fixture", folder: "Archive", kind,
        engine_kind: engineKind, reason: "Original reason", excerpt: "found «word»" });
      let tree = render();
      assert.ok(find(tree, (node) => node.type === "p" && node.props?.children === "Original reason"), engineKind);
      assert.ok(find(tree, (node) => node.type === "strong" && node.props.children === "word"), engineKind);
      find(tree, (node) => node.props?.["aria-expanded"] === false).props.onClick();
      tree = render();
      assert.equal(find(tree, (node) => node.props?.["aria-expanded"] === true).props.children, "Show less");
      find(tree, (node) => node.props?.["aria-expanded"] === true).props.onClick();
      assert.ok(find(render(), (node) => node.props?.["aria-expanded"] === false));
    }
    for (const excerpt of [null, ""]) {
      const tree = renderFixture({ id: "image", name: "fixture", folder: "Archive", kind: "image", excerpt })();
      assert.equal(find(tree, (node) => node.props?.["aria-expanded"] !== undefined), null);
    }
  });

  test("PDF controls render requested pages and respect page boundaries", () => {
    const render = renderFixture({ id: "pdf", name: "sample.pdf", folder: "Archive", kind: "document",
      engine_kind: "pdf", segment: "page", loc: 2, metadata: { pages: "3" }, preview_url: "/preview" });
    let tree = render();
    assert.equal(find(tree, (node) => node.type === "img").props.src, "/api/media/pdf/preview?loc=2");
    find(tree, (node) => node.props?.children === "Next").props.onClick();
    tree = render();
    assert.equal(find(tree, (node) => node.type === "img").props.src, "/api/media/pdf/preview?loc=3");
    assert.equal(find(tree, (node) => node.props?.children === "Next").props.disabled, true);
    find(tree, (node) => node.props?.children === "Previous").props.onClick();
    tree = render();
    assert.equal(find(tree, (node) => node.type === "img").props.src, "/api/media/pdf/preview?loc=2");
  });

  test("video timestamps request the chosen frame and reject out-of-range values", () => {
    const render = renderFixture({ id: "video", name: "sample.mp4", folder: "Archive", kind: "video",
      engine_kind: "video", segment: "frame", loc: 2, metadata: { duration: "10" }, preview_url: "/frame" });
    let tree = render();
    assert.equal(find(tree, (node) => node.type === "img").props.src, "/api/media/video/frame?at=2");
    find(tree, (node) => node.type === "input").props.onChange({ target: { value: "7.5" } });
    tree = render();
    find(tree, (node) => node.props?.children === "Go").props.onClick();
    tree = render();
    assert.equal(find(tree, (node) => node.type === "img").props.src, "/api/media/video/frame?at=7.5");
    find(tree, (node) => node.type === "input").props.onChange({ target: { value: "11" } });
    tree = render();
    find(tree, (node) => node.props?.children === "Go").props.onClick();
    tree = render();
    assert.equal(find(tree, (node) => node.type === "img").props.src, "/api/media/video/frame?at=7.5");
    assert.match(find(tree, (node) => node.props?.role === "alert").props.children, /between 0 and 10/);
  });

  test("audio timestamp navigation seeks the authenticated player", () => {
    const audio = { currentTime: 0, duration: 20 };
    const render = renderFixture({ id: "audio", name: "sample.mp3", folder: "Archive", kind: "audio",
      engine_kind: "audio", segment: "audio", loc: 2, metadata: { duration: "20" } }, { audio });
    let tree = render();
    find(tree, (node) => node.type === "audio").props.onLoadedMetadata({ currentTarget: audio });
    assert.equal(audio.currentTime, 2);
    find(tree, (node) => node.type === "input").props.onChange({ target: { value: "12" } });
    tree = render();
    find(tree, (node) => node.props?.children === "Go").props.onClick();
    assert.equal(audio.currentTime, 12);
  });
