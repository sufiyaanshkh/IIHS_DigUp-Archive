ObjC.import("AppKit");

function run() {
  const app = $.NSApplication.sharedApplication;
  app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
  const panel = $.NSOpenPanel.openPanel;
  panel.setCanChooseFiles(false);
  panel.setCanChooseDirectories(true);
  panel.setAllowsMultipleSelection(true);
  app.activateIgnoringOtherApps(true);
  if (Number(panel.runModal) !== Number($.NSModalResponseOK)) return JSON.stringify([]);
  const urls = panel.URLs;
  const paths = [];
  for (let i = 0; i < Number(urls.count); i++) {
    paths.push(ObjC.unwrap(urls.objectAtIndex(i).path));
  }
  return JSON.stringify(paths);
}
