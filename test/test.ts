// Type assertion helper ensuring TActual extends TExpected
function assertType<TExpected>(value: TExpected): void {}

async function testAction() {
    await browser.action.setTitle({ title: "My Action", tabId: 1 });
    const title = await browser.action.getTitle({ tabId: 1 });
    assertType<string>(title);

    await browser.action.setBadgeText({ text: "42" });
    const badgeText = await browser.action.getBadgeText({});
    assertType<string>(badgeText);

    await browser.action.setBadgeBackgroundColor({ color: "#FF0000" });
    const isEnabled = await browser.action.isEnabled({ tabId: 1 });
    assertType<boolean>(isEnabled);

    await browser.action.setPopup({ popup: "popup.html" });
    const popup = await browser.action.getPopup({ tabId: 1 });
    assertType<string>(popup);

    // Assert strictly typed event listener
    browser.action.onClicked.addListener((tab: browser.Tab) => {
        const tabId: number | undefined = tab.id;
        assertType<number | undefined>(tabId);
    });
}

async function testAlarms() {
    // Both with and without optional leading name
    await browser.alarms.create("sync-alarm", { periodInMinutes: 15, delayInMinutes: 1 });
    await browser.alarms.create({ periodInMinutes: 30 });

    const alarm = await browser.alarms.get("sync-alarm");
    assertType<browser.Alarm | undefined>(alarm);

    const allAlarms = await browser.alarms.getAll();
    assertType<browser.Alarm[]>(allAlarms);

    const cleared = await browser.alarms.clear("sync-alarm");
    assertType<boolean>(cleared);

    const clearedAll = await browser.alarms.clearAll();
    assertType<boolean>(clearedAll);

    browser.alarms.onAlarm.addListener((a: browser.Alarm) => {
        assertType<browser.Alarm>(a);
    });
}

async function testBookmarks() {
    const node = await browser.bookmarks.create({
        title: "WebKit",
        url: "https://webkit.org"
    });
    assertType<browser.BookmarkTreeNode>(node);

    const tree = await browser.bookmarks.getTree();
    assertType<browser.BookmarkTreeNode[]>(tree);

    const children = await browser.bookmarks.getChildren(node.id!);
    assertType<browser.BookmarkTreeNode[]>(children);

    const searchResults = await browser.bookmarks.search({ query: "WebKit" });
    assertType<browser.BookmarkTreeNode[]>(searchResults);

    await browser.bookmarks.remove(node.id!);
}

async function testCommands() {
    const commands = await browser.commands.getAll();
    assertType<browser.Command[]>(commands);

    browser.commands.onCommand.addListener((cmdName: string) => {
        assertType<string>(cmdName);
    });

    browser.commands.onChanged.addListener((changeInfo) => {
        assertType<{ name: string; oldShortcut: string; newShortcut: string }>(changeInfo);
    });
}

async function testCookies() {
    const cookie = await browser.cookies.get({
        url: "https://apple.com",
        name: "test_cookie"
    });
    assertType<browser.Cookie | null>(cookie);

    await browser.cookies.set({
        url: "https://apple.com",
        name: "test_cookie",
        value: "sample_value",
        secure: true,
        httpOnly: true,
        sameSite: "lax"
    });

    const allCookies = await browser.cookies.getAll({ domain: "apple.com" });
    assertType<browser.Cookie[]>(allCookies);

    const stores = await browser.cookies.getAllCookieStores();
    assertType<browser.CookieStore[]>(stores);

    // Safari dispatches this event with no arguments, so a listener may take
    // them but cannot read through one without narrowing it first.
    browser.cookies.onChanged.addListener((changeInfo) => {
        assertType<unknown>(changeInfo);

        if (changeInfo && typeof changeInfo === "object" && "removed" in changeInfo)
            assertType<unknown>(changeInfo.removed);
    });

    browser.cookies.onChanged.addListener(() => {});
}

async function testDeclarativeNetRequest() {
    const dynamicRules = await browser.declarativeNetRequest.getDynamicRules();
    assertType<Record<string, unknown>[]>(dynamicRules);

    await browser.declarativeNetRequest.updateEnabledRulesets({
        enableRulesetIds: ["ruleset_1"],
        disableRulesetIds: ["ruleset_2"]
    });

    const isSupported = await browser.declarativeNetRequest.isRegexSupported({
        regex: "^https://",
        isCaseSensitive: true
    });
    assertType<{ isSupported: boolean; reason?: string }>(isSupported);
}

async function testDevTools() {
    const tabId: number = browser.devtools.inspectedWindow.tabId;
    assertType<number>(tabId);

    browser.devtools.inspectedWindow.reload({ ignoreCache: true });
    browser.devtools.network.onNavigated.addListener((url: string) => {
        assertType<string>(url);
    });
}

async function testExtension() {
    const url: string = browser.extension.getURL("popup.html");
    assertType<string>(url);

    const incognitoAllowed = await browser.extension.isAllowedIncognitoAccess();
    assertType<boolean>(incognitoAllowed);

    const fileAllowed = await browser.extension.isAllowedFileSchemeAccess();
    assertType<boolean>(fileAllowed);

    const bgPage = browser.extension.getBackgroundPage();
    assertType<Window | null>(bgPage);

    const views = browser.extension.getViews({ type: "popup" });
    assertType<Window[]>(views);
}

async function testI18n() {
    const msg: string = browser.i18n.getMessage("app_name", "sub");
    assertType<string>(msg);

    const lang: string = browser.i18n.getUILanguage();
    assertType<string>(lang);

    const acceptLangs = await browser.i18n.getAcceptLanguages();
    assertType<string[]>(acceptLangs);
}

async function testMenus() {
    const id = browser.menus.create({
        id: "menu-item-1",
        title: "Test Menu Item",
        contexts: ["page", "selection", "link"]
    });
    assertType<number | string>(id);

    await browser.menus.update(id, { title: "Updated Item" });
    await browser.menus.remove(id);
    await browser.menus.removeAll();

    browser.menus.onClicked.addListener((info, tab) => {
        assertType<number | string>(info.menuItemId);
        assertType<browser.Tab | undefined>(tab);
    });
}

async function testNotifications() {
    // Neither event is ever dispatched, so neither declares a payload. A
    // listener may still take arguments; it cannot assume what they hold.
    browser.notifications.onClicked.addListener((notificationId) => {
        assertType<unknown>(notificationId);

        if (typeof notificationId === "string")
            assertType<string>(notificationId);
    });

    browser.notifications.onButtonClicked.addListener((notificationId, buttonIndex) => {
        assertType<unknown>(notificationId);
        assertType<unknown>(buttonIndex);
    });

    browser.notifications.onClicked.addListener(() => {});
}

async function testOffscreen() {
    await browser.offscreen.createDocument({
        url: "offscreen.html",
        reasons: ["AUDIO_PLAYBACK"],
        justification: "Play background sound notification"
    });

    const exists = await browser.offscreen.hasDocument();
    assertType<boolean>(exists);

    await browser.offscreen.closeDocument();
}

async function testPermissions() {
    const hasPerm = await browser.permissions.contains({
        permissions: ["storage", "tabs"],
        origins: ["https://*/*"]
    });
    assertType<boolean>(hasPerm);

    const currentPerms = await browser.permissions.getAll();
    assertType<browser.Permissions>(currentPerms);

    browser.permissions.onAdded.addListener((perms: browser.Permissions) => {
        assertType<browser.Permissions>(perms);
    });
}

async function testRuntime() {
    const info = await browser.runtime.getPlatformInfo();
    assertType<browser.PlatformInfo>(info);
    const validOs: "mac" | "ios" | "unknown" = info.os;
    const validArch: "arm" | "x86-64" | "unknown" = info.arch;
    assertType<"mac" | "ios" | "unknown">(validOs);
    assertType<"arm" | "x86-64" | "unknown">(validArch);

    const manifest: Record<string, unknown> = browser.runtime.getManifest();
    assertType<Record<string, unknown>>(manifest);

    assertType<Error | undefined>(browser.runtime.lastError);
    assertType<string | undefined>(browser.runtime.lastError?.message);

    browser.runtime.onInstalled.addListener((details) => {
        assertType<"install" | "update" | "browser_update">(details.reason);
        assertType<string | undefined>(details.previousVersion);
    });

    const url: string = browser.runtime.getURL("manifest.json");
    assertType<string>(url);

    const bgPage = await browser.runtime.getBackgroundPage();
    assertType<Window | null>(bgPage);

    // Message passing with optional extensionId
    await browser.runtime.sendMessage({ type: "ping" });
    await browser.runtime.sendMessage("other-ext", { type: "ping" });

    // sendNativeMessage with required applicationID
    await browser.runtime.sendNativeMessage("com.example.host", { query: "hello" });

    browser.runtime.onMessage.addListener((message: unknown, sender: browser.MessageSender, sendResponse: (res?: unknown) => void) => {
        sendResponse({ type: "pong" });
        return true;
    });

    // Ports with optional extensionId
    const port1: browser.runtime.Port = browser.runtime.connect({ name: "background-channel" });
    const port2: browser.runtime.Port = browser.runtime.connect("ext-id", { name: "bg" });
    assertType<browser.runtime.Port>(port1);
    assertType<browser.runtime.Port>(port2);

    // Set to the Error the failed connection reported, absent otherwise.
    assertType<Error | undefined>(port1.error);
    assertType<string | undefined>(port1.error?.message);

    port1.postMessage({ data: "init" });
    port1.onMessage.addListener((msg: unknown) => {
        assertType<unknown>(msg);
    });
    port1.disconnect();
}

async function testScripting() {
    const results = await browser.scripting.executeScript({
        target: { tabId: 1, allFrames: false },
        func: () => document.title
    });
    assertType<browser.InjectionResult[]>(results);

    assertType<"ISOLATED" | "MAIN">(browser.scripting.ExecutionWorld.ISOLATED);

    await browser.scripting.insertCSS({
        target: { tabId: 1 },
        css: "body { background: red; }"
    });

    await browser.scripting.removeCSS({
        target: { tabId: 1 },
        css: "body { background: red; }"
    });

    await browser.scripting.registerContentScripts([
        {
            id: "custom-script",
            matches: ["https://*.example.com/*"],
            js: ["content.js"],
            runAt: "document_idle"
        }
    ]);

    const scripts = await browser.scripting.getRegisteredContentScripts();
    assertType<browser.RegisteredContentScript[]>(scripts);

    await browser.scripting.unregisterContentScripts({ ids: ["custom-script"] });
}

async function testSidebarAndSidePanel() {
    await browser.sidebarAction.setTitle({ title: "My Sidebar" });
    const sidebarTitle = await browser.sidebarAction.getTitle({});
    assertType<string>(sidebarTitle);

    await browser.sidebarAction.open();
    await browser.sidebarAction.close();

    await browser.sidePanel.setOptions({
        path: "sidepanel.html",
        enabled: true
    });
    const sidePanelOpts = await browser.sidePanel.getOptions({});
    assertType<browser.SidePanelOptions>(sidePanelOpts);
}

async function testStorage() {
    await browser.storage.local.set({ theme: "dark", counter: 42 });

    // Promise form
    const data = await browser.storage.local.get<{ theme?: string; counter?: number }>(["theme", "counter"]);
    assertType<{ theme?: string; counter?: number }>(data);

    // Callback-only form (keys omitted)
    browser.storage.local.get((items: Record<string, unknown>) => {
        assertType<Record<string, unknown>>(items);
    });

    // Callback form with keys
    browser.storage.local.get("theme", (items: Record<string, unknown>) => {
        assertType<Record<string, unknown>>(items);
    });

    // getBytesInUse with 0-arg callback overload
    browser.storage.local.getBytesInUse((bytesInUse: number) => {
        assertType<number>(bytesInUse);
    });

    const bytes = await browser.storage.local.getBytesInUse(["theme"]);
    assertType<number>(bytes);

    await browser.storage.local.remove("counter");
    await browser.storage.local.clear();

    const keys = await browser.storage.local.getKeys();
    assertType<string[]>(keys);

    browser.storage.local.getKeys((k: string[]) => {
        assertType<string[]>(k);
    });

    await browser.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });

    assertType<number>(browser.storage.local.QUOTA_BYTES);

    browser.storage.local.onChanged.addListener((changes, areaName: string) => {
        assertType<Record<string, browser.StorageChange>>(changes);
        assertType<string>(areaName);
    });

    await browser.storage.sync.set({ syncedOption: true });
    await browser.storage.session.set({ ephemeralState: "active" });

    // The sync area alone carries the per-item and write-rate limits.
    assertType<number>(browser.storage.sync.QUOTA_BYTES_PER_ITEM);
    assertType<number>(browser.storage.sync.MAX_ITEMS);
    assertType<number>(browser.storage.sync.MAX_WRITE_OPERATIONS_PER_HOUR);
    assertType<number>(browser.storage.sync.MAX_WRITE_OPERATIONS_PER_MINUTE);

    browser.storage.onChanged.addListener((changes, areaName: string) => {
        assertType<string>(areaName);
    });
}

async function testTabs() {
    const tabs = await browser.tabs.query({ active: true, currentWindow: true });
    assertType<browser.Tab[]>(tabs);

    const newTab = await browser.tabs.create({
        url: "https://webkit.org",
        active: true
    });
    assertType<browser.Tab>(newTab);

    // Update with and without tabId
    await browser.tabs.update(newTab.id!, { url: "https://apple.com", pinned: true });
    await browser.tabs.update({ pinned: false });

    // Callback syntax
    browser.tabs.get(newTab.id!, (tab: browser.Tab) => {
        assertType<browser.Tab>(tab);
    });

    // captureVisibleTab overloads
    const cap1 = await browser.tabs.captureVisibleTab();
    assertType<string>(cap1);
    const cap2 = await browser.tabs.captureVisibleTab(1);
    assertType<string>(cap2);
    const cap3 = await browser.tabs.captureVisibleTab(1, { format: "png", quality: 90 });
    assertType<string>(cap3);

    browser.tabs.captureVisibleTab((dataUrl: string) => {
        assertType<string>(dataUrl);
    });

    browser.tabs.captureVisibleTab(1, (dataUrl: string) => {
        assertType<string>(dataUrl);
    });

    await browser.tabs.reload(newTab.id!, { bypassCache: true });
    await browser.tabs.remove(newTab.id!);

    // changeInfo is a Tab holding only the keys that changed.
    browser.tabs.onUpdated.addListener((tabId: number, changeInfo, tab: browser.Tab) => {
        assertType<number>(tabId);
        assertType<browser.Tab>(changeInfo);
        assertType<browser.Tab>(tab);
    });

    browser.tabs.onActivated.addListener((activeInfo) => {
        assertType<number>(activeInfo.previousTabId);
        assertType<number>(activeInfo.tabId);
        assertType<number>(activeInfo.windowId);
    });
}

async function testWebNavigation() {
    // The details argument and the result are different shapes: the argument is
    // the lookup key, the result is what the frame turned out to be.
    const frame = await browser.webNavigation.getFrame({ tabId: 1, frameId: 0 });
    assertType<browser.FrameDetails | null>(frame);
    if (frame) {
        assertType<boolean>(frame.errorOccurred);
        assertType<number>(frame.parentFrameId);
        assertType<string>(frame.url);
        assertType<number | undefined>(frame.frameId);
        assertType<string | undefined>(frame.documentId);
    }

    // Always an array; getAllFrames maps a vector rather than an optional.
    const allFrames = await browser.webNavigation.getAllFrames({ tabId: 1 });
    assertType<browser.FrameDetails[]>(allFrames);

    browser.webNavigation.onCommitted.addListener((details) => {
        assertType<string>(details.url);
        assertType<number>(details.tabId);
        assertType<number>(details.frameId);
        assertType<number>(details.parentFrameId);
        assertType<number>(details.timeStamp);
        assertType<string | undefined>(details.documentId);
    });
}

async function testWebRequest() {
    browser.webRequest.onBeforeRequest.addListener(
        (details: browser.WebRequestDetails) => {
            assertType<browser.WebRequestDetails>(details);
        },
        { urls: ["<all_urls>"] },
        ["blocking"]
    );

    browser.webRequest.onCompleted.addListener((details: browser.WebRequestDetails) => {
        assertType<browser.WebRequestDetails>(details);
    });
}

async function testWindows() {
    const currentWin = await browser.windows.getCurrent({ populate: true });
    assertType<browser.Window>(currentWin);

    const newWin = await browser.windows.create({
        url: "https://apple.com",
        type: "normal",
        state: "maximized",
        focused: true
    });
    assertType<browser.Window | undefined>(newWin);

    if (newWin && newWin.id !== undefined) {
        await browser.windows.update(newWin.id, { state: "fullscreen" });
        await browser.windows.remove(newWin.id);
    }

    const allWindows = await browser.windows.getAll({ populate: false });
    assertType<browser.Window[]>(allWindows);

    browser.windows.onFocusChanged.addListener((windowId: number) => {
        assertType<number>(windowId);
    });
}

async function testChromeAliases() {
    const tabs = await chrome.tabs.query({ active: true });
    assertType<browser.Tab[]>(tabs);

    await chrome.storage.local.set({ enabled: true });

    const info = await chrome.runtime.getPlatformInfo();
    assertType<browser.PlatformInfo>(info);

    chrome.action.setBadgeText({ text: "OK" });
    chrome.contextMenus.create({ id: "ctx-1", title: "Context Menu" });
}

export {
    testAction,
    testAlarms,
    testBookmarks,
    testCommands,
    testCookies,
    testDeclarativeNetRequest,
    testDevTools,
    testExtension,
    testI18n,
    testMenus,
    testNotifications,
    testOffscreen,
    testPermissions,
    testRuntime,
    testScripting,
    testSidebarAndSidePanel,
    testStorage,
    testTabs,
    testWebNavigation,
    testWebRequest,
    testWindows,
    testChromeAliases
};
