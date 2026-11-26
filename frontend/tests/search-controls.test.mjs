import test from "node:test";
import assert from "node:assert/strict";
import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { loadSource } from "./source-loader.mjs";

const types = loadSource("src/lib/archive-types.ts");

test("the existing file-kind controls map to DigUp search kinds", () => {
  const { ResultFilters } = loadSource("src/components/archive/result-filters.tsx", {
    "@/lib/archive-types": types,
    "@/components/ui/button": { Button: () => null },
  });
  let selected = null;
  const nav = ResultFilters({
    active: "all", limit: 50, counts: { all: 0, screenshot: 0, image: 0, document: 0, video: 0, audio: 0 },
    onChange: (value) => { selected = value; },
  });
  nav.props.children[3].props.onClick();
  assert.equal(selected, "document");
  assert.deepEqual(types.kindsForFilter(selected), ["pdf", "doc"]);
  assert.deepEqual(types.kindsForFilter("video"), ["video"]);
  assert.equal(types.kindsForFilter("all"), null);
});

test("search sends the selected kinds, mode, scope and result limit", async () => {
  const { archiveApi } = loadSource("src/lib/archive-api.ts", { "@/lib/auth-api": { authApi: {} } });
  const originalFetch = global.fetch;
  let payload, requestSignal;
  global.fetch = async (url, init) => {
    assert.equal(url, "/api/search");
    payload = JSON.parse(init.body);
    requestSignal = init.signal;
    return { ok: true, status: 200, json: async () => ({ hits: [] }) };
  };
  try {
    await archiveApi.search("sample", "keyword", "archive", types.kindsForFilter("document"), 25);
    assert.deepEqual(payload, { query: "sample", mode: "keyword", scope: "archive", kinds: ["pdf", "doc"], limit: 25, prefix_last: false });
    await archiveApi.search("sample", "hybrid", "code");
    assert.deepEqual(payload, { query: "sample", mode: "hybrid", scope: "code", kinds: null, limit: 100, prefix_last: false });
    const signal = new AbortController().signal;
    await archiveApi.search("sam", "keyword", "archive", null, 20, true, signal);
    assert.equal(payload.prefix_last, true);
    assert.equal(requestSignal, signal);
  } finally {
    global.fetch = originalFetch;
  }
});

test("engine controls send authenticated CSRF-protected requests", async () => {
  const { archiveApi } = loadSource("src/lib/archive-api.ts", {
    "@/lib/auth-api": { authApi: { csrfHeaders: async () => ({ "x-csrf-token": "test-token" }) } },
  });
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url, init) => {
    calls.push({ url, method: init.method, credentials: init.credentials, token: init.headers["x-csrf-token"] });
    return { ok: true, status: 200, json: async () => ({}) };
  };
  try {
    await archiveApi.prewarm();
    await archiveApi.reloadSearch();
    assert.deepEqual(calls, ["/api/engine/prewarm", "/api/engine/reload"].map((url) => ({
      url, method: "POST", credentials: "same-origin", token: "test-token",
    })));
  } finally {
    global.fetch = originalFetch;
  }
});

test("archive browsing uses the authenticated same-origin API and forwards cancellation", async () => {
  const { archiveApi } = loadSource("src/lib/archive-api.ts", { "@/lib/auth-api": { authApi: {} } });
  const originalFetch = global.fetch;
  const params = new URLSearchParams({ source_id: "source", folder: "reports", limit: "50" });
  const signal = new AbortController().signal;
  let captured;
  global.fetch = async (url, init) => {
    captured = { url, credentials: init.credentials, signal: init.signal };
    return { ok: true, status: 200, json: async () => ({ sources: [], items: [] }) };
  };
  try {
    await archiveApi.browseArchive(params, signal);
    assert.equal(captured.url, `/api/archive?${params.toString()}`);
    assert.equal(captured.credentials, "same-origin");
    assert.equal(captured.signal, signal);
  } finally {
    global.fetch = originalFetch;
  }
});

test("result cards expose the engine score without changing the displayed content", () => {
  const { ResultsGrid } = loadSource("src/components/archive/results-grid.tsx");
  const result = { id: "one", name: "sample.pdf", folder: "Archive", kind: "document", score: 2.75 };
  const grid = ResultsGrid({
    results: [result], selectedId: "one", onSelect: () => {}, onNavigate: () => {},
    query: "sample", loading: false, error: null,
  });
  const button = grid.props.children[0];
  assert.equal(button.props.title, "DigUp ranking score: 2.75");
  assert.match(button.props["aria-label"], /DigUp ranking score 2\.75/);
});

test("thumbnail failures stay local, recover on URL changes, and preserve result interactions", () => {
  const states = new Map();
  const mountedKeys = new Map();
  let stateKey;
  const { ResultsGrid } = loadSource("src/components/archive/results-grid.tsx", {
    react: {
      useState: (initial) => {
        const key = stateKey;
        return [states.has(key) ? states.get(key) : initial, (value) => states.set(key, value)];
      },
    },
    "next/image": { __esModule: true, default: "img" },
    "lucide-react": { Image: "image-icon", FileText: "document-icon", Video: "video-icon",
      AudioLines: "audio-icon", Code2: "code-icon", Search: "search-icon" },
  });
  const results = [
    { id: "one", name: "one.jpg", folder: "Archive", kind: "image", score: 3, preview_url: "/one" },
    { id: "two", name: "two.mp4", folder: "Archive", kind: "video", score: 2, preview_url: "/two" },
    { id: "three", name: "three.mp3", folder: "Archive", kind: "audio", score: 1, preview_url: null },
  ];
  let selected, navigated, focused;
  const grid = () => ResultsGrid({ results, selectedId: "one", onSelect: (item) => { selected = item.id; },
    onNavigate: (item) => { navigated = item.id; }, query: "fixture", loading: false, error: null });
  const renderThumbnail = (card) => {
    const thumbnail = card.props.children[0].props.children[0];
    assert.equal(typeof thumbnail.type, "function");
    const previous = mountedKeys.get(card.key);
    if (previous !== thumbnail.key) {
      states.delete(`${card.key}/${previous}`);
      mountedKeys.set(card.key, thumbnail.key);
    }
    stateKey = `${card.key}/${thumbnail.key}`;
    return thumbnail.type(thumbnail.props);
  };
  let cards = grid().props.children;
  assert.deepEqual(cards.map((card) => card.key), ["one", "two", "three"]);
  let first = renderThumbnail(cards[0]);
  assert.equal(findElement(first, (node) => node.type === "img").props.src, "/one");
  assert.equal(findElement(renderThumbnail(cards[1]), (node) => node.type === "img").props.src, "/two");
  const missing = renderThumbnail(cards[2]);
  assert.ok(findElement(missing, (node) => node.type === "audio-icon"));
  assert.equal(findElement(missing, (node) => node.props?.role === "status"), null);

  findElement(first, (node) => node.type === "img").props.onError();
  first = renderThumbnail(cards[0]);
  assert.ok(findElement(first, (node) => node.type === "image-icon"));
  assert.equal(findElement(first, (node) => node.props?.role === "status").props.children, "Preview unavailable");
  assert.ok(findElement(renderThumbnail(cards[1]), (node) => node.type === "img"));

  cards[0].props.onClick();
  assert.equal(selected, "one");
  const buttons = results.map((_, index) => ({ focus: () => { focused = index; } }));
  cards[0].props.onKeyDown({
    key: "ArrowRight", nativeEvent: { isComposing: false }, preventDefault: () => {},
    currentTarget: { parentElement: { querySelectorAll: () => buttons } },
  });
  assert.equal(navigated, "two");
  assert.equal(focused, 1);
  assert.equal(cards[0].props["aria-pressed"], true);

  results[0] = { ...results[0], preview_url: "/replacement" };
  cards = grid().props.children;
  assert.deepEqual(cards.map((card) => card.key), ["one", "two", "three"]);
  assert.equal(findElement(renderThumbnail(cards[0]), (node) => node.type === "img").props.src, "/replacement");
  results[0] = { ...results[0], preview_url: "/one" };
  cards = grid().props.children;
  assert.equal(findElement(renderThumbnail(cards[0]), (node) => node.type === "img").props.src, "/one");
});

test("arrow navigation follows visible grid rows and preserves modified and composing keys", () => {
  const { ResultsGrid } = loadSource("src/components/archive/results-grid.tsx");
  const results = Array.from({ length: 5 }, (_, i) => ({
    id: String(i), name: `file${i}`, folder: "Archive", kind: "document", score: 1,
  }));
  let selected, focused, prevented = 0;
  const grid = ResultsGrid({
    results, selectedId: "1", onSelect: () => {}, onNavigate: (value) => { selected = value.id; },
    query: "file", loading: false, error: null,
  });
  const buttons = results.map((_, i) => ({
    getBoundingClientRect: () => ({ top: Math.floor(i / 2) * 100, left: (i % 2) * 200 }),
    focus: () => { focused = i; },
  }));
  const event = (index, key, extra = {}) => ({
    key, nativeEvent: { isComposing: false }, currentTarget: {
      ...buttons[index], parentElement: { querySelectorAll: () => buttons },
    }, preventDefault: () => { prevented++; }, ...extra,
  });
  grid.props.children[1].props.onKeyDown(event(1, "ArrowDown"));
  assert.equal(selected, "3");
  assert.equal(focused, 3);
  grid.props.children[3].props.onKeyDown(event(3, "ArrowDown"));
  assert.equal(selected, "4");
  grid.props.children[4].props.onKeyDown(event(4, "ArrowUp"));
  assert.equal(selected, "2");
  grid.props.children[1].props.onKeyDown(event(1, "ArrowDown", { ctrlKey: true }));
  grid.props.children[1].props.onKeyDown(event(1, "ArrowDown", { nativeEvent: { isComposing: true } }));
  assert.equal(prevented, 3);
});

test("PDF matches without a page segment preview the first page", () => {
  const hit = { engine_kind: "pdf", kind: "document", segment: "chunk", loc: 20,
                preview_url: "/api/media/one/preview", modified: 0, size: 0 };
  assert.equal(types.toArchiveResult(hit).preview_url, "/api/media/one/preview?loc=1");
  assert.equal(types.toArchiveResult({ ...hit, segment: "page", loc: 3 }).preview_url,
               "/api/media/one/preview?loc=3");
});

test("the result-limit control reports the selected limit", () => {
  const { ArchiveToolbar } = loadSource("src/components/archive/archive-toolbar.tsx", {
    react: { useEffect: () => {}, useRef: () => ({ current: false }) },
    "@hookform/resolvers/zod": { zodResolver: () => () => {} },
    "react-hook-form": {
      useForm: () => ({ register: () => ({ ref: () => {} }), control: {}, setValue: () => {}, formState: { errors: {} } }),
      useWatch: () => "",
    },
    "@/components/ui/button": { Button: () => null },
    "@/lib/search-schema": { searchSchema: {} },
    "@/store/search-store": {
      useSearchStore: (selector) => selector({ query: "", mode: "keyword", setQuery: () => {}, setMode: () => {} }),
    },
    "@/components/auth/session-actions": { SessionActions: () => null },
  });
  let selected;
  const tree = ArchiveToolbar({ resultLimit: 100, onResultLimitChange: (value) => { selected = value; } });
  function find(element, predicate) {
    if (!element || typeof element !== "object") return null;
    if (predicate(element)) return element;
    for (const child of [element.props?.children].flat(Infinity)) {
      const found = find(child, predicate);
      if (found) return found;
    }
    return null;
  }
  const control = find(tree, (element) => element.props?.["aria-label"] === "Maximum search results");
  assert.equal(control.props.value, 100);
  control.props.onChange({ target: { value: "50" } });
  assert.equal(selected, 50);
  let backfill;
  const indexing = ArchiveToolbar({ canManageArchive: true, resultLimit: 100,
    indexing: { state: "indexing", backfill_requested: true },
    onBackfillChange: (enabled) => { backfill = enabled; } });
  find(indexing, (element) => element.props?.children === "Pause backfill").props.onClick();
  assert.equal(backfill, false);
  const actions = [];
  const engine = ArchiveToolbar({ canManageArchive: true, resultLimit: 100,
    engine: { files: 1, vectors: 0, encoder: "unavailable" },
    prewarmState: "unavailable",
    onPrewarm: () => actions.push("prewarm"),
    onReloadSearch: () => actions.push("reload"),
    indexing: { state: "idle" } });
  find(engine, (element) => element.props?.children === "Prewarm search").props.onClick();
  find(engine, (element) => element.props?.children === "Reload search").props.onClick();
  assert.deepEqual(actions, ["prewarm", "reload"]);
  assert.ok(find(engine, (element) => element.props?.role === "status" && element.props.children.includes("unavailable")));
  const busy = ArchiveToolbar({ canManageArchive: true, engine: { files: 1, vectors: 0, encoder: "ready" },
    indexing: { state: "indexing" } });
  assert.equal(find(busy, (element) => element.props?.children === "Reload search").props.disabled, true);
  const blocked = ArchiveToolbar({ canManageArchive: true, engine: { files: 1, vectors: 0, encoder: "ready" },
    indexing: { state: "idle", sync_available: false, sync_unavailable_reason: "Incomplete crawl" } });
  assert.equal(find(blocked, (element) => element.props?.children === "Index sources").props.disabled, true);
  assert.ok(find(blocked, (element) => element.props?.children === "Incomplete crawl"));
  const unknown = ArchiveToolbar({ canManageArchive: true, engine: { files: 1, vectors: 0, encoder: "ready" } });
  assert.equal(find(unknown, (element) => element.props?.children === "Index sources").props.disabled, true);
});

test("Escape clears the focused search without intercepting IME composition", () => {
  const changes = [];
  const { ArchiveToolbar } = loadSource("src/components/archive/archive-toolbar.tsx", {
    react: { useEffect: () => {}, useRef: () => ({ current: false }) },
    "@hookform/resolvers/zod": { zodResolver: () => () => {} },
    "react-hook-form": {
      useForm: () => ({ register: () => ({ ref: () => {} }), control: {},
        setValue: (...args) => changes.push(args), formState: { errors: {} } }),
      useWatch: () => "sample",
    },
    "@/components/ui/button": { Button: () => null },
    "@/lib/search-schema": { searchSchema: {} },
    "@/store/search-store": {
      useSearchStore: (selector) => selector({ query: "sample", mode: "keyword",
        setQuery: (value) => changes.push(value), setMode: () => {} }),
    },
    "@/components/auth/session-actions": { SessionActions: () => null },
  });
  const tree = ArchiveToolbar({ resultLimit: 100 });
  function find(element) {
    if (!element || typeof element !== "object") return null;
    if (element.props?.["aria-label"] === "Search the archive") return element;
    for (const child of [element.props?.children].flat(Infinity)) {
      const found = find(child);
      if (found) return found;
    }
    return null;
  }
  const input = find(tree);
  const event = { key: "Escape", nativeEvent: { isComposing: true }, preventDefault: () => changes.push("prevented") };
  input.props.onKeyDown(event);
  assert.deepEqual(changes, []);
  input.props.onKeyDown({ ...event, nativeEvent: { isComposing: false } });
  assert.deepEqual(changes, ["prevented", ["query", ""], ""]);
});

test("IME composition does not submit intermediate searches", () => {
  const changes = [];
  const { ArchiveToolbar } = loadSource("src/components/archive/archive-toolbar.tsx", {
    react: { useEffect: () => {}, useRef: () => ({ current: false }) },
    "@hookform/resolvers/zod": { zodResolver: () => () => {} },
    "react-hook-form": {
      useForm: () => ({ register: () => ({ ref: () => {}, onChange: () => {} }),
        control: {}, setValue: () => {}, formState: { errors: {} } }),
      useWatch: () => "",
    },
    "@/components/ui/button": { Button: () => null },
    "@/lib/search-schema": { searchSchema: {} },
    "@/store/search-store": {
      useSearchStore: (selector) => selector({ query: "", mode: "keyword",
        setQuery: (value) => changes.push(value), setMode: () => {} }),
    },
    "@/components/auth/session-actions": { SessionActions: () => null },
  });
  const input = findElement(ArchiveToolbar({ resultLimit: 100 }),
    (element) => element.props?.["aria-label"] === "Search the archive");
  input.props.onCompositionStart();
  input.props.onChange({ target: { value: "intermediate" }, nativeEvent: { isComposing: true } });
  assert.deepEqual(changes, []);
  input.props.onCompositionEnd({ currentTarget: { value: "finished" } });
  assert.deepEqual(changes, ["finished"]);
});

test("selecting a file-kind filter runs a filtered engine query", async () => {
  const states = ["document", "archive", null, true, false, false, "saffron", 50];
  const queries = [];
  let searchArgs;
  const shell = loadSource("src/components/archive/archive-shell.tsx", {
    react: {
      useState: () => [states.shift(), () => {}],
      useEffect: () => {},
      useMemo: (fn) => fn(),
      useRef: () => ({ current: null }),
    },
    "@tanstack/react-query": {
      useQueryClient: () => ({}),
      useMutation: () => ({ mutate: () => {}, isPending: false }),
      useQuery: (options) => {
        queries.push(options);
        return options.queryKey[0] === "archive-health"
          ? { data: { digup_cli_available: true, status: "ok" }, isSuccess: true }
          : {};
      },
    },
    "@/components/archive/archive-toolbar": {},
    "@/components/archive/archive-section-nav": { ArchiveSectionNav: () => null },
    "@/components/archive/preview-pane": {},
    "@/components/archive/results-grid": {},
    "@/components/archive/result-filters": {},
    "@/components/archive/status-bar": {},
    "@/lib/archive-api": {
      archiveApi: { search: (...args) => { searchArgs = args; } },
      ArchiveApiError: class ArchiveApiError extends Error {},
    },
    "@/lib/archive-types": types,
    "@/store/search-store": {
      useSearchStore: (selector) => selector({ query: "saffron", mode: "keyword", setQuery: () => {} }),
    },
  });
  shell.ArchiveShell({ user: { role: "ARCHIVE_OPERATOR" } });
  const filtered = queries.find((entry) => entry.queryKey.at(-1) === "document" && entry.queryKey[2] === "keyword");
  assert.equal(filtered.enabled, true);
  const signal = new AbortController().signal;
  filtered.queryFn({ signal });
  assert.deepEqual(searchArgs, ["saffron", "keyword", "archive", ["pdf", "doc"], 50, false, signal]);
});

function renderSearch({ query = "", settled = "", mode = "hybrid", filter = "all", showWeaker = false, limit = 50,
                        responses = new Map(), search = () => {}, setQuery = () => {} } = {}) {
  const expanded = showWeaker ? JSON.stringify([query.trim(), mode, "archive", filter, limit]) : null;
  const states = [filter, "archive", null, true, false, expanded, settled, limit];
  const queries = [];
  const effects = [];
  const shell = loadSource("src/components/archive/archive-shell.tsx", {
    react: {
      useState: () => [states.shift(), () => {}],
      useEffect: (fn) => effects.push(fn),
      useMemo: (fn) => fn(),
      useRef: () => ({ current: null }),
    },
    "@tanstack/react-query": {
      useQueryClient: () => ({}),
      useMutation: () => ({ mutate: () => {}, isPending: false }),
      useQuery: (options) => {
        queries.push(options);
        if (options.queryKey[0] === "archive-health") return { data: { digup_cli_available: true, status: "ok" }, isSuccess: true };
        return responses.get(JSON.stringify(options.queryKey)) ?? {};
      },
    },
    "@/components/archive/archive-toolbar": { ArchiveToolbar: function ArchiveToolbar() {} },
    "@/components/archive/archive-section-nav": { ArchiveSectionNav: function ArchiveSectionNav() {} },
    "@/components/archive/preview-pane": { PreviewPane: function PreviewPane() {} },
    "@/components/archive/results-grid": { ResultsGrid: function ResultsGrid() {} },
    "@/components/archive/result-filters": { ResultFilters: function ResultFilters() {} },
    "@/components/archive/status-bar": { StatusBar: function StatusBar() {} },
    "@/lib/archive-api": { archiveApi: { search }, ArchiveApiError: class ArchiveApiError extends Error {} },
    "@/lib/archive-types": types,
    "@/store/search-store": { useSearchStore: (selector) => selector({ query, mode, setQuery }) },
  });
  return { tree: shell.ArchiveShell({ user: { role: "ARCHIVE_OPERATOR" } }), queries, effects };
}

function findElement(element, predicate) {
  if (!element || typeof element !== "object") return null;
  if (predicate(element)) return element;
  for (const child of [element.props?.children].flat(Infinity)) {
    const found = findElement(child, predicate);
    if (found) return found;
  }
  return null;
}

test("filter counts use the unfiltered strong prefix and preserve filtered result order", () => {
  const hit = (id, kind, engine_kind = kind) => ({
    id, name: id, folder: "fixture", kind, engine_kind, segment: "name", loc: null,
    loc_end: null, modified: 1, size: 1, score: 1, preview_url: null,
  });
  const hits = [
    hit("screen", "screenshot"), hit("image", "image"), hit("pdf", "document", "pdf"),
    hit("doc", "document", "doc"), hit("video", "video"), hit("weak-audio", "audio"),
    hit("weak-image", "image"),
  ];
  const allKey = JSON.stringify(["archive-search", "cat", "hybrid", "archive", 50]);
  const filteredKey = JSON.stringify(["archive-search", "cat", "hybrid", "archive", 50, "document"]);
  const responses = new Map([
    [allKey, { data: { hits, strong: 5, meaning: true } }],
    [filteredKey, { data: { hits: [hits[3], hits[2]], strong: 2, meaning: true } }],
  ]);
  const all = renderSearch({ query: "cat", settled: "cat", responses }).tree;
  const filtered = renderSearch({ query: "cat", settled: "cat", filter: "document", responses }).tree;
  const counts = { all: 5, screenshot: 1, image: 1, document: 2, video: 1, audio: 0 };
  for (const tree of [all, filtered]) {
    assert.deepEqual(findElement(tree, (item) => item.type?.name === "ResultFilters").props.counts, counts);
  }
  assert.deepEqual(findElement(all, (item) => item.type?.name === "ResultsGrid").props.results.map((item) => item.id),
    ["screen", "image", "pdf", "doc", "video"]);
  assert.deepEqual(findElement(filtered, (item) => item.type?.name === "ResultsGrid").props.results.map((item) => item.id),
    ["doc", "pdf"]);
});

test("filter counts respect empty, weak-only and full strong boundaries", () => {
  const hit = (id, kind) => ({ id, name: id, folder: "fixture", kind, engine_kind: kind,
    segment: "name", loc: null, loc_end: null, modified: 1, size: 1, score: 1, preview_url: null });
  const hits = [hit("image", "image"), hit("audio", "audio")];
  const key = JSON.stringify(["archive-search", "cat", "hybrid", "archive", 50]);
  for (const [responseHits, strong, expected] of [
    [[], 0, [0, 0]],
    [hits, 0, [0, 0]],
    [hits, 1, [1, 0]],
    [hits, 2, [1, 1]],
  ]) {
    const responses = new Map([[key, { data: { hits: responseHits, strong, meaning: true } }]]);
    const { tree } = renderSearch({ query: "cat", settled: "cat", responses });
    const counts = findElement(tree, (item) => item.type?.name === "ResultFilters").props.counts;
    assert.deepEqual([counts.image, counts.audio], expected);
    assert.equal(counts.all, strong);
  }
});

test("unavailable unfiltered responses do not display stale filter counts", () => {
  const hit = { id: "image", name: "image", folder: "fixture", kind: "image", engine_kind: "image",
    segment: "name", loc: null, loc_end: null, modified: 1, size: 1, score: 1, preview_url: null };
  const key = JSON.stringify(["archive-search", "cat", "hybrid", "archive", 50]);
  for (const response of [undefined, { isError: true, error: new Error("Unavailable"),
                                      data: { hits: [hit], strong: 1 } }]) {
    const responses = new Map(response ? [[key, response]] : []);
    const { tree } = renderSearch({ query: "cat", settled: "cat", filter: "image", responses });
    const counts = findElement(tree, (item) => item.type?.name === "ResultFilters").props.counts;
    assert.equal(counts.image, 0);
    if (response) {
      assert.equal(findElement(tree, (item) => item.type?.name === "StatusBar").props.searchError,
        "Filter counts are unavailable.");
    }
  }
});

test("filter counts and tooltip use the selected result limit", () => {
  const { ResultFilters } = loadSource("src/components/archive/result-filters.tsx", {
    "@/lib/archive-types": types,
    "@/components/ui/button": { Button: () => null },
  });
  const hits = Array.from({ length: 25 }, (_, index) => ({
    id: String(index), name: String(index), folder: "fixture", kind: "image", engine_kind: "image",
    segment: "name", loc: null, loc_end: null, modified: 1, size: 1, score: 1, preview_url: null,
  }));
  for (const limit of [10, 25]) {
    const key = JSON.stringify(["archive-search", "cat", "hybrid", "archive", limit]);
    const responses = new Map([[key, { data: { hits: hits.slice(0, limit), strong: limit, meaning: true } }]]);
    let searchArgs;
    const { tree, queries } = renderSearch({
      query: "cat", settled: "cat", limit, responses, search: (...args) => { searchArgs = args; },
    });
    const props = findElement(tree, (item) => item.type?.name === "ResultFilters").props;
    assert.equal(props.counts.image, limit);
    assert.equal(props.limit, limit);
    assert.match(ResultFilters(props).props.title, new RegExp(`strong.*${limit}.*unfiltered`, "i"));
    const query = queries.find((entry) => JSON.stringify(entry.queryKey) === key);
    query.queryFn({ signal: undefined });
    assert.deepEqual(searchArgs, ["cat", "hybrid", "archive", null, limit, false, undefined]);
  }
});

test("desktop example searches populate the query and use the existing search flow", () => {
  const { ResultsGrid } = loadSource("src/components/archive/results-grid.tsx");
  let selected = "";
  const { tree } = renderSearch({ setQuery: (value) => { selected = value; } });
  const grid = findElement(tree, (item) => item.type?.name === "ResultsGrid");
  const empty = ResultsGrid(grid.props);
  const example = findElement(empty, (item) => item.type === "button" &&
    item.props.children?.includes("someone laughing"));
  assert.ok(example);
  example.props.onClick();
  assert.equal(selected, "someone laughing");
  const next = renderSearch({ query: selected, settled: selected });
  const searches = next.queries.filter((item) => item.queryKey[0] === "archive-search");
  assert.equal(searches[0].enabled, true);
  assert.equal(searches[2].enabled, true);
  assert.equal(searches[2].queryKey[1], selected);

  assert.equal(findElement(ResultsGrid({ ...grid.props, query: "unmatched" }),
    (item) => item.props?.["aria-label"] === "Example searches"), null);
  assert.equal(findElement(ResultsGrid({ ...grid.props, showExamples: false }),
    (item) => item.props?.["aria-label"] === "Example searches"), null);
  assert.equal(findElement(ResultsGrid({ ...grid.props, error: "Unavailable" }),
    (item) => item.props?.["aria-label"] === "Example searches"), null);
});

test("live prefix starts immediately, final search waits 120 ms and empty queries do not search", () => {
  const first = renderSearch({ query: "cat", settled: "ca" });
  const searches = first.queries.filter((item) => item.queryKey[0] === "archive-search");
  assert.equal(searches[0].enabled, true);
  assert.equal(searches[2].enabled, false);
  let delay, cleared;
  const originalWindow = global.window;
  global.window = { setTimeout: (_, ms) => { delay = ms; return 123; }, clearTimeout: (id) => { cleared = id; } };
  try {
    const cleanup = first.effects[0]();
    assert.equal(delay, 120);
    cleanup();
    assert.equal(cleared, 123);
  } finally { global.window = originalWindow; }
  const settled = renderSearch({ query: "cat", settled: "cat" });
  assert.equal(settled.queries.filter((item) => item.queryKey[0] === "archive-search")[2].enabled, true);
  const empty = renderSearch({ query: "  ", settled: "" });
  assert.ok(empty.queries.filter((item) => item.queryKey[0] === "archive-search").every((item) => !item.enabled));
});

test("rapid changes cancel old requests and late replies cannot replace current results", async () => {
  const requests = [];
  const search = (query, mode, scope, kinds, limit, prefix, signal) =>
    new Promise((resolve) => requests.push({ query, prefix, signal, resolve }));
  const old = renderSearch({ query: "ca", search }).queries.find((q) => q.queryKey[2] === "prefix");
  const next = renderSearch({ query: "cat", search }).queries.find((q) => q.queryKey[2] === "prefix");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const observer = new QueryObserver(client, old);
  const unsubscribe = observer.subscribe(() => {});
  assert.equal(requests.length, 1);
  observer.setOptions(next);
  assert.equal(requests.length, 2);
  assert.equal(requests[0].signal.aborted, true);
  requests[1].resolve({ hits: [{ id: "new" }] });
  await new Promise((resolve) => setTimeout(resolve, 0));
  requests[0].resolve({ hits: [{ id: "old" }] });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(observer.getCurrentResult().data.hits[0].id, "new");
  unsubscribe();
  client.clear();
});

test("final engine order replaces prefix results, preserves strong boundary and surfaces fallback", () => {
  const hit = (id) => ({ id, name: `${id}.txt`, folder: "fixture", kind: "document", engine_kind: "doc",
    segment: "chunk", loc: null, loc_end: null, modified: 1, size: 1, score: 1, preview_url: null });
  const prefixKey = JSON.stringify(["archive-search", "cat", "prefix", "archive", 50]);
  const finalKey = JSON.stringify(["archive-search", "cat", "hybrid", "archive", 50]);
  const responses = new Map([
    [prefixKey, { data: { hits: [hit("old")], strong: 1, meaning: false } }],
    [finalKey, { data: { hits: [hit("both"), hit("meaning"), hit("weak")], strong: 2, meaning: false,
                         warning: "Meaning unavailable" } }],
  ]);
  const { tree } = renderSearch({ query: "cat", settled: "cat", responses });
  const grid = findElement(tree, (item) => item.type?.name === "ResultsGrid");
  assert.deepEqual(grid.props.results.map((item) => item.id), ["both", "meaning"]);
  const fold = findElement(tree, (item) => item.props?.["aria-expanded"] === false);
  assert.equal(fold.props.children, "Show 1 weaker match");
  assert.ok(findElement(tree, (item) => item.props?.role === "status" && item.props.children === "Meaning unavailable"));
  const expanded = renderSearch({ query: "cat", settled: "cat", responses, showWeaker: true }).tree;
  assert.deepEqual(findElement(expanded, (item) => item.type?.name === "ResultsGrid").props.results.map((item) => item.id),
    ["both", "meaning", "weak"]);
  const pending = renderSearch({ query: "cat", settled: "ca", responses }).tree;
  assert.deepEqual(findElement(pending, (item) => item.type?.name === "ResultsGrid").props.results.map((item) => item.id), ["old"]);
  assert.equal(findElement(pending, (item) => item.props?.role === "status" && item.props.children === "Meaning unavailable"), null);
});

test("final engine errors are visible rather than replaced by prefix results", () => {
  const key = JSON.stringify(["archive-search", "cat", "hybrid", "archive", 50]);
  const responses = new Map([[key, { isError: true, error: new Error("Engine unavailable") }]]);
  const { tree } = renderSearch({ query: "cat", settled: "cat", responses });
  assert.equal(findElement(tree, (item) => item.type?.name === "ResultsGrid").props.error, "Engine unavailable");
});
