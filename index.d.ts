// Type definitions for Safari WebExtensions
// Project: https://github.com/patrickkettner/safari-webextension-types
// Definitions generated directly from WebKit WebIDL declarations
// Source: WebKit/WebKit@0136fa2b7cf669ab6bc8e715727e6a78bf5f24ba
//
// Generated automatically by safari-webextension-types generator.
// Do not edit directly.

declare namespace browser {

    export namespace events {
        export interface Event<T extends (...args: never[]) => void> {
            addListener(callback: T): void;
            removeListener(callback: T): void;
            hasListener(callback: T): boolean;
        }
        export interface WebRequestEvent<T extends (...args: never[]) => void> extends Event<T> {
            addListener(callback: T, filter?: browser.WebRequestFilter, extraInfoSpec?: string[]): void;
        }
    }

    export interface CookieStore {
        id: string;
        tabIds: number[];
        incognito: boolean;
    }

    export interface PlatformInfo {
        os: "mac" | "ios" | "unknown";
        arch: "arm" | "x86-64" | "unknown";
    }

    export interface InjectionResult<T = unknown> {
        documentId?: string;
        frameId?: number;
        result: T | null;
        error?: string;
    }

    export interface MenuItemUpdateProperties {
        checked?: boolean;
        command?: string;
        contexts?: string[];
        documentUrlPatterns?: string[];
        enabled?: boolean;
        icons?: string | Record<string, unknown> | null;
        iconVariants?: Record<string, unknown>[] | null;
        id?: string | number;
        onclick?: (...args: never[]) => void;
        parentId?: string | number;
        targetUrlPatterns?: string[];
        title?: string;
        type?: string;
        visible?: boolean;
    }

    export interface InjectionTarget {
        tabId: number;
        allFrames?: boolean;
        documentIds?: string[];
        frameIds?: number[];
    }

    export interface CSSInjection {
        target: browser.InjectionTarget;
        css?: string;
        files?: string[];
        origin?: string;
    }

    export interface TabUpdateOptions {
        active?: boolean;
        highlighted?: boolean;
        muted?: boolean;
        openerTabId?: number;
        pinned?: boolean;
        selected?: boolean;
        url?: string;
    }

    export interface TabQueryOptions {
        active?: boolean;
        audible?: boolean;
        currentWindow?: boolean;
        hidden?: boolean;
        highlighted?: boolean;
        index?: number;
        lastFocusedWindow?: boolean;
        muted?: boolean;
        pinned?: boolean;
        selected?: boolean;
        status?: browser.TabStatus;
        title?: string;
        url?: string | string[];
        windowId?: number;
        windowType?: browser.WindowType;
    }

    export interface TabScriptInjection {
        allFrames?: boolean;
        code?: string;
        documentId?: string;
        file?: string;
        frameId?: number;
        tabId?: number;
    }

    export interface WindowQueryOptions {
        populate?: boolean;
        windowTypes?: browser.WindowType[];
    }

    export interface WindowUpdateOptions {
        state?: browser.WindowState;
        focused?: boolean;
        top?: number;
        left?: number;
        width?: number;
        height?: number;
    }

    export interface FrameDetails {
        errorOccurred: boolean;
        parentFrameId: number;
        url: string;
        frameId?: number;
        documentId?: string;
    }

    export interface RegisteredContentScript {
        id: string;
        matches: string[];
        persistAcrossSessions?: boolean;
        css?: string[];
        js?: string[];
        excludeMatches?: string[];
        allFrames?: boolean;
        matchOriginAsFallback?: boolean;
        runAt?: "document_start" | "document_end" | "document_idle";
        cssOrigin?: "author" | "user";
        world?: "main" | "isolated" | "MAIN" | "ISOLATED";
    }
    export type CSSOrigin = "USER" | "AUTHOR";
    export type CookieSameSiteStatus = "no_restriction" | "lax" | "strict";
    export type MenuItemContextType = "all" | "page" | "frame" | "selection" | "link" | "editable" | "image" | "video" | "audio" | "action" | "browser_action" | "page_action" | "tab";
    export type MenuItemType = "normal" | "checkbox" | "radio" | "separator";
    export type OffscreenReason = "TESTING" | "AUDIO_PLAYBACK" | "IFRAME_SCRIPTING" | "DOM_SCRAPING" | "BLOBS" | "DOM_PARSER" | "USER_GESTURE" | "DISPLAY_MEDIA" | "WEB_RTC" | "CLIPBOARD" | "LOCAL_STORAGE" | "WORKERS" | "BATTERY_STATUS" | "MATCH_MEDIA" | "GEOLOCATION";
    export type PortDisconnectReason = "disconnect" | "connection_error";
    export type ScriptInjectionExecutionWorld = "ISOLATED" | "MAIN";
    export type TabStatus = "loading" | "complete";
    export type WebRequestResourceType = "main_frame" | "sub_frame" | "stylesheet" | "script" | "image" | "font" | "object" | "xmlhttprequest" | "ping" | "csp_report" | "media" | "websocket" | "other";
    export type WindowState = "normal" | "minimized" | "maximized" | "fullscreen";
    export type WindowType = "normal" | "popup";

    export interface ActionDetails {
        tabId?: number;
        windowId?: number;
    }

    export interface ActionOpenPopupOptions {
        windowId?: number;
    }

    export interface ActionSetBadgeBackgroundColorDetails {
        color?: unknown;
        tabId?: number;
        windowId?: number;
    }

    export interface ActionSetBadgeTextDetails {
        tabId?: number;
        text?: string;
        windowId?: number;
    }

    export interface ActionSetIconDetails {
        imageData?: unknown;
        path?: unknown;
        tabId?: number;
        windowId?: number;
    }

    export interface ActionSetPopupDetails {
        popup?: string;
        tabId?: number;
        windowId?: number;
    }

    export interface ActionSetTitleDetails {
        tabId?: number;
        title?: string;
        windowId?: number;
    }

    export interface Alarm {
        name?: string;
        periodInMinutes?: number;
        scheduledTime?: number;
    }

    export interface AlarmCreateInfo {
        delayInMinutes?: number;
        name?: string;
        periodInMinutes?: number;
        when?: number;
    }

    export interface BookmarkChanges {
        title?: string;
        url?: string;
    }

    export interface BookmarkCreateDetails {
        index?: number;
        parentId?: string;
        title?: string;
        url?: string;
    }

    export interface BookmarkDestination {
        index?: number;
        parentId?: string;
    }

    export interface BookmarkSearchQuery {
        query?: string;
        title?: string;
        url?: string;
    }

    export interface BookmarkTreeNode {
        children?: browser.BookmarkTreeNode[];
        dateAdded?: number;
        dateGroupModified?: number;
        id?: string;
        index?: number;
        parentId?: string;
        title?: string;
        url?: string;
    }

    export interface CSSInjection {
        css?: string;
        files?: string[];
        origin?: string;
        target: browser.ScriptInjectionTarget;
    }

    export interface Command {
        description?: string;
        name?: string;
        shortcut?: string;
    }

    export interface ConnectOptions {
        name?: string;
    }

    export interface Cookie {
        domain?: string;
        expirationDate?: number;
        hostOnly?: boolean;
        httpOnly?: boolean;
        name?: string;
        path?: string;
        sameSite?: browser.CookieSameSiteStatus;
        secure?: boolean;
        session?: boolean;
        storeId?: string;
        value?: string;
    }

    export interface CookieDetails {
        name?: string;
        storeId?: string;
        url?: string;
    }

    export interface CookieGetAllDetails {
        domain?: string;
        name?: string;
        path?: string;
        secure?: boolean;
        session?: boolean;
        storeId?: string;
        url?: string;
    }

    export interface CookieSetDetails {
        domain?: string;
        expirationDate?: number;
        httpOnly?: boolean;
        name?: string;
        path?: string;
        sameSite?: string;
        secure?: boolean;
        storeId?: string;
        url?: string;
        value?: string;
    }

    export interface DNRMatchedRule {
        ruleId?: number;
        rulesetId?: string;
    }

    export interface DNRMatchedRulesFilter {
        minTimeStamp?: number;
        tabId?: number;
    }

    export interface DNRTabUpdateOptions {
        increment: number;
        tabId: number;
    }

    export interface DNRUpdateRuleOptions {
        disableRulesetIds?: string[];
        enableRulesetIds?: string[];
    }

    export interface DevToolsEvalOptions {
        frameURL?: string;
    }

    export interface DevToolsReloadOptions {
        ignoreCache?: boolean;
    }

    export interface LanguageDetectionResult {
        isReliable?: boolean;
        languages?: unknown[];
    }

    export interface MenuItemProperties {
        checked?: boolean;
        command?: string;
        contexts?: string[];
        documentUrlPatterns?: string[];
        enabled?: boolean;
        icons?: unknown;
        id?: unknown;
        onclick?: unknown;
        parentId?: unknown;
        targetUrlPatterns?: string[];
        title?: string;
        type?: browser.MenuItemType;
        visible?: boolean;
    }

    export interface MessageOptions {
        includeTlsChannelId?: boolean;
    }

    export interface MessageSender {
        frameId?: number;
        id?: string;
        tab?: browser.Tab;
        tlsChannelId?: string;
        url?: string;
    }

    export interface OffscreenCreateParameters {
        justification?: string;
        reasons?: string[];
        url?: string;
    }

    export interface Permissions {
        origins?: string[];
        permissions?: string[];
    }

    export interface ScriptInjection {
        args?: unknown[];
        files?: string[];
        func?: unknown;
        target: browser.ScriptInjectionTarget;
        world?: string;
    }

    export interface ScriptInjectionTarget {
        allFrames?: boolean;
        documentIds?: string[];
        frameIds?: number[];
        tabId: number;
    }

    export interface SendMessageOptions {
        includeTlsChannelId?: boolean;
    }

    export interface SidePanelBehavior {
        openPanelOnActionClick?: boolean;
    }

    export interface SidePanelOptions {
        enabled?: boolean;
        path?: string;
        tabId?: number;
        windowId?: number;
    }

    export interface SidebarActionDetails {
        tabId?: number;
        windowId?: number;
    }

    export interface SidebarActionSetIconDetails {
        imageData?: unknown;
        path?: unknown;
        tabId?: number;
        windowId?: number;
    }

    export interface SidebarActionSetPanelDetails {
        panel?: string;
        tabId?: number;
        windowId?: number;
    }

    export interface SidebarActionSetTitleDetails {
        tabId?: number;
        title?: string;
        windowId?: number;
    }

    export interface StorageAccessOptions {
        accessLevel?: string;
    }

    export interface StorageChange {
        newValue?: unknown;
        oldValue?: unknown;
    }

    export interface Tab {
        active?: boolean;
        audible?: boolean;
        height?: number;
        highlighted?: boolean;
        id?: number;
        incognito?: boolean;
        index?: number;
        isArticle?: boolean;
        isInReaderMode?: boolean;
        mutedInfo?: browser.TabMutedInfo;
        openerTabId?: number;
        pinned?: boolean;
        selected?: boolean;
        status?: browser.TabStatus;
        title?: string;
        url?: string;
        width?: number;
        windowId?: number;
    }

    export interface TabCreateProperties {
        active?: boolean;
        highlighted?: boolean;
        index?: number;
        muted?: boolean;
        openInReaderMode?: boolean;
        openerTabId?: number;
        pinned?: boolean;
        selected?: boolean;
        title?: string;
        url?: string;
        windowId?: number;
    }

    export interface TabMutedInfo {
        muted?: boolean;
    }

    export interface ViewFilter {
        tabId?: number;
        type?: string;
        windowId?: number;
    }

    export interface WebNavigationGetAllFramesDetails {
        tabId?: number;
    }

    export interface WebNavigationGetFrameDetails {
        frameId?: number;
        processId?: string;
        tabId?: number;
    }

    export interface WebRequestDetails {
        documentId?: string;
        error?: string;
        frameId?: number;
        frameType?: string;
        initiator?: string;
        method?: string;
        parentFrameId?: number;
        proxyInfo?: string;
        redirectUrl?: string;
        requestHeaders?: unknown[];
        requestId?: string;
        responseHeaders?: unknown[];
        statusCode?: number;
        statusLine?: string;
        tabId?: number;
        timeStamp?: number;
        type?: string;
        url?: string;
    }

    export interface WebRequestFilter {
        tabId?: number;
        types?: string[];
        urls?: string[];
        windowId?: number;
    }

    export interface Window {
        alwaysOnTop?: boolean;
        focused?: boolean;
        height?: number;
        id?: number;
        incognito?: boolean;
        left?: number;
        state?: browser.WindowState;
        tabs?: browser.Tab[];
        top?: number;
        type?: browser.WindowType;
        width?: number;
    }

    export interface WindowCreateData {
        focused?: boolean;
        height?: number;
        incognito?: boolean;
        left?: number;
        state?: string;
        tabId?: number;
        top?: number;
        type?: string;
        url?: unknown;
        width?: number;
    }

    export interface WindowGetInfo {
        populate?: boolean;
        windowTypes?: string[];
    }

    export interface WindowUpdateInfo {
        focused?: boolean;
        height?: number;
        left?: number;
        state?: string;
        top?: number;
        width?: number;
    }

    export namespace runtime {
        export interface Port {
            name: string;
            sender?: browser.MessageSender;
            error?: Error;
            onDisconnect: events.Event<(port: Port) => void>;
            onMessage: events.Event<(message: unknown, port: Port) => void>;
            postMessage<T = unknown>(message: T): void;
            disconnect(): void;
        }
    }
    export type Port = runtime.Port;

    export namespace storage {
        export interface StorageArea {
            onChanged: events.Event<(changes: Record<string, browser.StorageChange>, areaName: string) => void>;
            QUOTA_BYTES: number;
            get<T = Record<string, unknown>>(callback: (items: T) => void): void;
            get<T = Record<string, unknown>>(keys?: string | string[] | Record<string, unknown> | null): Promise<T>;
            get<T = Record<string, unknown>>(keys: string | string[] | Record<string, unknown> | null, callback: (items: T) => void): void;
            getKeys(callback: (keys: string[]) => void): void;
            getKeys(): Promise<string[]>;
            getBytesInUse(callback: (bytesInUse: number) => void): void;
            getBytesInUse(keys?: string | string[] | null): Promise<number>;
            getBytesInUse(keys: string | string[] | null, callback: (bytesInUse: number) => void): void;
            set(items: Record<string, unknown>): Promise<void>;
            set(items: Record<string, unknown>, callback: () => void): void;
            remove(keys: string | string[]): Promise<void>;
            remove(keys: string | string[], callback: () => void): void;
            clear(): Promise<void>;
            clear(callback: () => void): void;
            setAccessLevel(accessOptions: { accessLevel: "TRUSTED_CONTEXTS" | "TRUSTED_AND_UNTRUSTED_CONTEXTS" }): Promise<void>;
            setAccessLevel(accessOptions: { accessLevel: "TRUSTED_CONTEXTS" | "TRUSTED_AND_UNTRUSTED_CONTEXTS" }, callback: () => void): void;
        }
        export interface SyncStorageArea extends StorageArea {
            QUOTA_BYTES_PER_ITEM: number;
            MAX_ITEMS: number;
            MAX_WRITE_OPERATIONS_PER_HOUR: number;
            MAX_WRITE_OPERATIONS_PER_MINUTE: number;
        }
    }
    export type StorageArea = storage.StorageArea;

    export namespace devtools {
        export interface InspectedWindow {
            tabId: number;
            /**
             * The callback parameter list is left open because WebKit calls it with one argument, a two-element array of the result and, on failure, an error object. Prefer the promise. WebKit builds that error object with the literal keys "isExceptionKey" and "valueKey", which are the names of its key constants rather than their values.
             */
            eval<T = unknown>(expression: string, options?: browser.DevToolsEvalOptions, callback?: (...args: unknown[]) => void): Promise<T>;
            reload(reloadOptions?: browser.DevToolsReloadOptions): void;
        }
        export interface Network {
            onNavigated: events.Event<(url: string) => void>;
        }
        export interface Panels {
            themeName: string;
            onThemeChanged: events.Event<(themeName: string) => void>;
            create(title: string, iconPath: string, pagePath: string, callback?: (panel: Record<string, unknown>) => void): void;
        }
    }

    export namespace action {
        export const onClicked: events.Event<(tab: browser.Tab) => void>;
        export function getTitle(details: browser.ActionDetails, callback: (result: string) => void): void;
        export function getTitle(callback: (result: string) => void): void;
        export function getTitle(details?: browser.ActionDetails): Promise<string>;
        export function setTitle(details: browser.ActionSetTitleDetails, callback: () => void): void;
        export function setTitle(details: browser.ActionSetTitleDetails): Promise<void>;
        export function getBadgeText(details: browser.ActionDetails, callback: (result: string) => void): void;
        export function getBadgeText(callback: (result: string) => void): void;
        export function getBadgeText(details?: browser.ActionDetails): Promise<string>;
        export function setBadgeText(details: browser.ActionSetBadgeTextDetails, callback: () => void): void;
        export function setBadgeText(details: browser.ActionSetBadgeTextDetails): Promise<void>;
        export function getBadgeBackgroundColor(details: browser.ActionDetails, callback: (result: number[]) => void): void;
        export function getBadgeBackgroundColor(callback: (result: number[]) => void): void;
        export function getBadgeBackgroundColor(details?: browser.ActionDetails): Promise<number[]>;
        export function setBadgeBackgroundColor(details: browser.ActionSetBadgeBackgroundColorDetails, callback: () => void): void;
        export function setBadgeBackgroundColor(details: browser.ActionSetBadgeBackgroundColorDetails): Promise<void>;
        export function enable(tabId: number, callback: () => void): void;
        export function enable(callback: () => void): void;
        export function enable(tabId?: number): Promise<void>;
        export function disable(tabId: number, callback: () => void): void;
        export function disable(callback: () => void): void;
        export function disable(tabId?: number): Promise<void>;
        export function isEnabled(details: browser.ActionDetails, callback: (result: boolean) => void): void;
        export function isEnabled(callback: (result: boolean) => void): void;
        export function isEnabled(details?: browser.ActionDetails): Promise<boolean>;
        export function setIcon(details: browser.ActionSetIconDetails, callback: () => void): void;
        export function setIcon(details: browser.ActionSetIconDetails): Promise<void>;
        export function setPopup(details: browser.ActionSetPopupDetails, callback: () => void): void;
        export function setPopup(details: browser.ActionSetPopupDetails): Promise<void>;
        export function getPopup(details: browser.ActionDetails, callback: (result: string) => void): void;
        export function getPopup(callback: (result: string) => void): void;
        export function getPopup(details?: browser.ActionDetails): Promise<string>;
        export function openPopup(options: browser.ActionDetails, callback: () => void): void;
        export function openPopup(callback: () => void): void;
        export function openPopup(options?: browser.ActionDetails): Promise<void>;
    }

    export namespace alarms {
        export const onAlarm: events.Event<(alarm: browser.Alarm) => void>;
        export function create(name: string, info: { name?: string; when?: number; delayInMinutes?: number; periodInMinutes?: number }, callback: () => void): void;
        export function create(name: string, info: { name?: string; when?: number; delayInMinutes?: number; periodInMinutes?: number }): Promise<void>;
        export function create(info: { name?: string; when?: number; delayInMinutes?: number; periodInMinutes?: number }, callback: () => void): void;
        export function create(info: { name?: string; when?: number; delayInMinutes?: number; periodInMinutes?: number }): Promise<void>;
        export function get(name: string, callback: (result: browser.Alarm | undefined) => void): void;
        export function get(callback: (result: browser.Alarm | undefined) => void): void;
        export function get(name?: string): Promise<browser.Alarm | undefined>;
        export function getAll(callback: (result: browser.Alarm[]) => void): void;
        export function getAll(): Promise<browser.Alarm[]>;
        export function clear(name: string, callback: (result: boolean) => void): void;
        export function clear(callback: (result: boolean) => void): void;
        export function clear(name?: string): Promise<boolean>;
        export function clearAll(callback: (result: boolean) => void): void;
        export function clearAll(): Promise<boolean>;
    }

    export namespace bookmarks {
        export function create(bookmark: unknown, callback: (result: browser.BookmarkTreeNode) => void): void;
        export function create(bookmark: unknown): Promise<browser.BookmarkTreeNode>;
        export function getChildren(id: string, callback: (result: browser.BookmarkTreeNode[]) => void): void;
        export function getChildren(id: string): Promise<browser.BookmarkTreeNode[]>;
        export function getRecent(numberOfItems: number, callback: (result: browser.BookmarkTreeNode[]) => void): void;
        export function getRecent(numberOfItems: number): Promise<browser.BookmarkTreeNode[]>;
        export function getSubTree(id: string, callback: (result: browser.BookmarkTreeNode[]) => void): void;
        export function getSubTree(id: string): Promise<browser.BookmarkTreeNode[]>;
        export function getTree(callback: (result: browser.BookmarkTreeNode[]) => void): void;
        export function getTree(): Promise<browser.BookmarkTreeNode[]>;
        export function get(idOrIdList: string | string[], callback: (result: browser.BookmarkTreeNode[]) => void): void;
        export function get(idOrIdList: string | string[]): Promise<browser.BookmarkTreeNode[]>;
        export function remove(id: string, callback: () => void): void;
        export function remove(id: string): Promise<void>;
        export function removeTree(id: string, callback: () => void): void;
        export function removeTree(id: string): Promise<void>;
        export function search(query: unknown, callback: (result: browser.BookmarkTreeNode[]) => void): void;
        export function search(query: unknown): Promise<browser.BookmarkTreeNode[]>;
        export function update(id: string, changes: unknown, callback: (result: browser.BookmarkTreeNode) => void): void;
        export function update(id: string, changes: unknown): Promise<browser.BookmarkTreeNode>;
        export function move(id: string, destination: unknown, callback: (result: browser.BookmarkTreeNode) => void): void;
        export function move(id: string, destination: unknown): Promise<browser.BookmarkTreeNode>;
    }

    export namespace commands {
        export const onCommand: events.Event<(command: string) => void>;
        export const onChanged: events.Event<(changeInfo: { name: string; oldShortcut: string; newShortcut: string }) => void>;
        export function getAll(callback: (result: browser.Command[]) => void): void;
        export function getAll(): Promise<browser.Command[]>;
    }

    export namespace cookies {
        /**
         * No payload is declared because Safari fires this event with no arguments. changeInfo is not implemented yet; see https://webkit.org/b/267514. A listener parameter will be undefined at runtime.
         */
        export const onChanged: events.Event<(...args: unknown[]) => void>;
        export function get(details: { name: string; url: string; storeId?: string }, callback: (result: browser.Cookie | null) => void): void;
        export function get(details: { name: string; url: string; storeId?: string }): Promise<browser.Cookie | null>;
        export function getAll(details: { name?: string; url?: string; storeId?: string; domain?: string; path?: string; secure?: boolean; session?: boolean }, callback: (result: browser.Cookie[]) => void): void;
        export function getAll(details: { name?: string; url?: string; storeId?: string; domain?: string; path?: string; secure?: boolean; session?: boolean }): Promise<browser.Cookie[]>;
        export function set(details: { url: string; name?: string; storeId?: string; domain?: string; path?: string; value?: string; expirationDate?: number; httpOnly?: boolean; secure?: boolean; sameSite?: browser.CookieSameSiteStatus }, callback: (result: browser.Cookie | null) => void): void;
        export function set(details: { url: string; name?: string; storeId?: string; domain?: string; path?: string; value?: string; expirationDate?: number; httpOnly?: boolean; secure?: boolean; sameSite?: browser.CookieSameSiteStatus }): Promise<browser.Cookie | null>;
        export function remove(details: { name: string; url: string; storeId?: string }, callback: (result: browser.Cookie | null) => void): void;
        export function remove(details: { name: string; url: string; storeId?: string }): Promise<browser.Cookie | null>;
        export function getAllCookieStores(callback: (result: browser.CookieStore[]) => void): void;
        export function getAllCookieStores(): Promise<browser.CookieStore[]>;
    }

    export namespace dom {
        export function openOrClosedShadowRoot(element: unknown): unknown;
    }

    export namespace declarativeNetRequest {
        export const onRuleMatchedDebug: events.Event<(info: browser.DNRMatchedRule) => void>;
        export const MAX_NUMBER_OF_STATIC_RULESETS: number;
        export const MAX_NUMBER_OF_ENABLED_STATIC_RULESETS: number;
        export const MAX_NUMBER_OF_DYNAMIC_AND_SESSION_RULES: number;
        export function updateEnabledRulesets(options: { enableRulesetIds?: string[]; disableRulesetIds?: string[] }, callback: () => void): void;
        export function updateEnabledRulesets(options: { enableRulesetIds?: string[]; disableRulesetIds?: string[] }): Promise<void>;
        export function getEnabledRulesets(callback: (result: string[]) => void): void;
        export function getEnabledRulesets(): Promise<string[]>;
        export function updateDynamicRules(options: { addRules?: Record<string, unknown>[]; removeRuleIds?: number[] }, callback: () => void): void;
        export function updateDynamicRules(options: { addRules?: Record<string, unknown>[]; removeRuleIds?: number[] }): Promise<void>;
        export function getDynamicRules(filter: unknown, callback: (result: Record<string, unknown>[]) => void): void;
        export function getDynamicRules(callback: (result: Record<string, unknown>[]) => void): void;
        export function getDynamicRules(filter?: unknown): Promise<Record<string, unknown>[]>;
        export function updateSessionRules(options: { addRules?: Record<string, unknown>[]; removeRuleIds?: number[] }, callback: () => void): void;
        export function updateSessionRules(options: { addRules?: Record<string, unknown>[]; removeRuleIds?: number[] }): Promise<void>;
        export function getSessionRules(filter: unknown, callback: (result: Record<string, unknown>[]) => void): void;
        export function getSessionRules(callback: (result: Record<string, unknown>[]) => void): void;
        export function getSessionRules(filter?: unknown): Promise<Record<string, unknown>[]>;
        export function getMatchedRules(filter: browser.DNRMatchedRulesFilter, callback: (result: { rulesMatchedInfo: browser.DNRMatchedRule[] }) => void): void;
        export function getMatchedRules(callback: (result: { rulesMatchedInfo: browser.DNRMatchedRule[] }) => void): void;
        export function getMatchedRules(filter?: browser.DNRMatchedRulesFilter): Promise<{ rulesMatchedInfo: browser.DNRMatchedRule[] }>;
        export function isRegexSupported(regexOptions: { regex: string; isCaseSensitive?: boolean; requireCapturing?: boolean }, callback: (result: { isSupported: boolean; reason?: string }) => void): void;
        export function isRegexSupported(regexOptions: { regex: string; isCaseSensitive?: boolean; requireCapturing?: boolean }): Promise<{ isSupported: boolean; reason?: string }>;
        export function setExtensionActionOptions(options: { displayActionCountAsBadgeText?: boolean; tabUpdate?: { tabId: number; increment: number } }, callback: () => void): void;
        export function setExtensionActionOptions(options: { displayActionCountAsBadgeText?: boolean; tabUpdate?: { tabId: number; increment: number } }): Promise<void>;
    }

    export namespace devtools {
        export const inspectedWindow: browser.devtools.InspectedWindow;
        export const network: browser.devtools.Network;
        export const panels: browser.devtools.Panels;
    }

    export namespace extension {
        export const inIncognitoContext: boolean;
        export function getURL(resourcePath: string): string;
        export function getBackgroundPage(): globalThis.Window | null;
        export function getViews(fetchProperties?: browser.ViewFilter): globalThis.Window[];
        export function isAllowedIncognitoAccess(callback: (result: boolean) => void): void;
        export function isAllowedIncognitoAccess(): Promise<boolean>;
        export function isAllowedFileSchemeAccess(callback: (result: boolean) => void): void;
        export function isAllowedFileSchemeAccess(): Promise<boolean>;
    }

    export namespace i18n {
        export function getMessage(name: string, substitutions?: string | string[]): string;
        export function getUILanguage(): string;
        export function getAcceptLanguages(callback: (result: string[]) => void): void;
        export function getAcceptLanguages(): Promise<string[]>;
        export function getPreferredSystemLanguages(callback: (result: string[]) => void): void;
        export function getPreferredSystemLanguages(): Promise<string[]>;
        export function getSystemUILanguage(callback: (result: string) => void): void;
        export function getSystemUILanguage(): Promise<string>;
    }

    export namespace menus {
        export const onClicked: events.Event<(info: { menuItemId: number | string; parentMenuItemId?: number | string; checked?: boolean; wasChecked?: boolean; selectionText?: string; srcUrl?: string; mediaType?: "audio" | "image" | "video"; linkUrl?: string; linkText?: string; editable?: boolean; frameId?: number; pageUrl?: string; frameUrl?: string }, tab?: browser.Tab) => void>;
        export const ACTION_MENU_TOP_LEVEL_LIMIT: number;
        export function create(createProperties: browser.MenuItemProperties, callback?: () => void): number | string;
        export function update(identifier: number | string, properties: browser.MenuItemUpdateProperties, callback: () => void): void;
        export function update(identifier: number | string, properties: browser.MenuItemUpdateProperties): Promise<void>;
        export function remove(identifier: number | string, callback: () => void): void;
        export function remove(identifier: number | string): Promise<void>;
        export function removeAll(callback: () => void): void;
        export function removeAll(): Promise<void>;
    }

    export namespace notifications {
        /**
         * No payload is declared because Safari does not fire this event yet. WebKit creates the event object, and no code path invokes its listeners.
         */
        export const onClicked: events.Event<(...args: unknown[]) => void>;
        /**
         * No payload is declared because Safari does not fire this event yet. WebKit creates the event object, and no code path invokes its listeners.
         */
        export const onButtonClicked: events.Event<(...args: unknown[]) => void>;
    }

    export namespace offscreen {
        export function createDocument(options: { url: string; justification: string; reasons: string[] }, callback: () => void): void;
        export function createDocument(options: { url: string; justification: string; reasons: string[] }): Promise<void>;
        export function closeDocument(callback: () => void): void;
        export function closeDocument(): Promise<void>;
        export function hasDocument(callback: (result: boolean) => void): void;
        export function hasDocument(): Promise<boolean>;
    }

    export namespace permissions {
        export const onAdded: events.Event<(permissions: browser.Permissions) => void>;
        export const onRemoved: events.Event<(permissions: browser.Permissions) => void>;
        export function getAll(callback: (result: browser.Permissions) => void): void;
        export function getAll(): Promise<browser.Permissions>;
        export function contains(permissions: browser.Permissions, callback: (result: boolean) => void): void;
        export function contains(permissions: browser.Permissions): Promise<boolean>;
        export function request(permissions: browser.Permissions, callback: (result: boolean) => void): void;
        export function request(permissions: browser.Permissions): Promise<boolean>;
        export function remove(permissions: browser.Permissions, callback: (result: boolean) => void): void;
        export function remove(permissions: browser.Permissions): Promise<boolean>;
    }

    export namespace runtime {
        export const id: string;
        export const lastError: Error | undefined;
        export const onConnect: events.Event<(port: browser.runtime.Port) => void>;
        export const onMessage: events.Event<(message: unknown, sender: browser.MessageSender, sendResponse: (response?: unknown) => void) => boolean | void | Promise<unknown>>;
        export const onConnectExternal: events.Event<(port: browser.runtime.Port) => void>;
        export const onMessageExternal: events.Event<(message: unknown, sender: browser.MessageSender, sendResponse: (response?: unknown) => void) => boolean | void | Promise<unknown>>;
        export const onStartup: events.Event<() => void>;
        export const onInstalled: events.Event<(details: { reason: "install" | "update" | "browser_update"; previousVersion?: string }) => void>;
        export function getURL(resourcePath: string): string;
        export function getManifest(): Record<string, unknown>;
        export function getVersion(): string;
        export function getFrameId(target: globalThis.Window | globalThis.HTMLIFrameElement | globalThis.HTMLFrameElement): number;
        export function getDocumentId(target: globalThis.Window | globalThis.HTMLIFrameElement | globalThis.HTMLFrameElement): string;
        export function getPlatformInfo(callback: (result: browser.PlatformInfo) => void): void;
        export function getPlatformInfo(): Promise<browser.PlatformInfo>;
        export function getBackgroundPage(callback: (result: globalThis.Window | null) => void): void;
        export function getBackgroundPage(): Promise<globalThis.Window | null>;
        export function setUninstallURL(url: string, callback: () => void): void;
        export function setUninstallURL(url: string): Promise<void>;
        export function openOptionsPage(callback: () => void): void;
        export function openOptionsPage(): Promise<void>;
        export function reload(): void;
        export function sendMessage<T = unknown, R = unknown>(extensionID: string, message: T, options: browser.MessageOptions, callback: (result: R) => void): void;
        export function sendMessage<T = unknown, R = unknown>(extensionID: string, message: T, callback: (result: R) => void): void;
        export function sendMessage<T = unknown, R = unknown>(extensionID: string, message: T, options?: browser.MessageOptions): Promise<R>;
        export function sendMessage<T = unknown, R = unknown>(message: T, options: browser.MessageOptions, callback: (result: R) => void): void;
        export function sendMessage<T = unknown, R = unknown>(message: T, callback: (result: R) => void): void;
        export function sendMessage<T = unknown, R = unknown>(message: T, options?: browser.MessageOptions): Promise<R>;
        export function connect(connectInfo?: browser.ConnectOptions): browser.runtime.Port;
        export function connect(extensionId: string, connectInfo?: browser.ConnectOptions): browser.runtime.Port;
        export function sendNativeMessage<T = unknown, R = unknown>(applicationID: string, message: T, callback: (result: R) => void): void;
        export function sendNativeMessage<T = unknown, R = unknown>(applicationID: string, message: T): Promise<R>;
        export function connectNative(applicationID?: string): browser.runtime.Port;
    }

    export namespace scripting {
        export const ExecutionWorld: { readonly ISOLATED: "ISOLATED"; readonly MAIN: "MAIN" };
        export function executeScript(details: browser.ScriptInjection, callback: (result: browser.InjectionResult[]) => void): void;
        export function executeScript(details: browser.ScriptInjection): Promise<browser.InjectionResult[]>;
        export function insertCSS(details: browser.CSSInjection, callback: () => void): void;
        export function insertCSS(details: browser.CSSInjection): Promise<void>;
        export function removeCSS(details: browser.CSSInjection, callback: () => void): void;
        export function removeCSS(details: browser.CSSInjection): Promise<void>;
        export function registerContentScripts(scripts: browser.RegisteredContentScript[], callback: () => void): void;
        export function registerContentScripts(scripts: browser.RegisteredContentScript[]): Promise<void>;
        export function getRegisteredContentScripts(filter: unknown, callback: (result: browser.RegisteredContentScript[]) => void): void;
        export function getRegisteredContentScripts(callback: (result: browser.RegisteredContentScript[]) => void): void;
        export function getRegisteredContentScripts(filter?: unknown): Promise<browser.RegisteredContentScript[]>;
        export function unregisterContentScripts(filter: unknown, callback: () => void): void;
        export function unregisterContentScripts(callback: () => void): void;
        export function unregisterContentScripts(filter?: unknown): Promise<void>;
        export function updateContentScripts(scripts: browser.RegisteredContentScript[], callback: () => void): void;
        export function updateContentScripts(scripts: browser.RegisteredContentScript[]): Promise<void>;
    }

    export namespace sidePanel {
        export function getOptions(options: { tabId?: number }, callback: (result: browser.SidePanelOptions) => void): void;
        export function getOptions(options: { tabId?: number }): Promise<browser.SidePanelOptions>;
        export function setOptions(options: browser.SidePanelOptions, callback: () => void): void;
        export function setOptions(options: browser.SidePanelOptions): Promise<void>;
        export function getPanelBehavior(callback: (result: browser.SidePanelBehavior) => void): void;
        export function getPanelBehavior(): Promise<browser.SidePanelBehavior>;
        export function setPanelBehavior(behavior: browser.SidePanelBehavior, callback: () => void): void;
        export function setPanelBehavior(behavior: browser.SidePanelBehavior): Promise<void>;
        export function open(options: { tabId?: number; windowId?: number }, callback: () => void): void;
        export function open(options: { tabId?: number; windowId?: number }): Promise<void>;
    }

    export namespace sidebarAction {
        export function open(callback: () => void): void;
        export function open(): Promise<void>;
        export function close(callback: () => void): void;
        export function close(): Promise<void>;
        export function toggle(callback: () => void): void;
        export function toggle(): Promise<void>;
        export function isOpen(details: { windowId?: number }, callback: (result: boolean) => void): void;
        export function isOpen(details: { windowId?: number }): Promise<boolean>;
        export function getPanel(details: browser.SidebarActionDetails, callback: (result: string) => void): void;
        export function getPanel(details: browser.SidebarActionDetails): Promise<string>;
        export function setPanel(details: browser.SidebarActionSetPanelDetails, callback: () => void): void;
        export function setPanel(details: browser.SidebarActionSetPanelDetails): Promise<void>;
        export function getTitle(details: browser.SidebarActionDetails, callback: (result: string) => void): void;
        export function getTitle(details: browser.SidebarActionDetails): Promise<string>;
        export function setTitle(details: browser.SidebarActionSetTitleDetails, callback: () => void): void;
        export function setTitle(details: browser.SidebarActionSetTitleDetails): Promise<void>;
        export function setIcon(details: browser.SidebarActionSetIconDetails, callback: () => void): void;
        export function setIcon(details: browser.SidebarActionSetIconDetails): Promise<void>;
    }

    export namespace storage {
        export const local: browser.storage.StorageArea;
        export const session: browser.storage.StorageArea;
        export const sync: browser.storage.SyncStorageArea;
        export const onChanged: events.Event<(changes: Record<string, browser.StorageChange>, areaName: string) => void>;
    }

    export namespace tabs {
        export const TAB_ID_NONE: number;
        export const onActivated: events.Event<(activeInfo: { previousTabId: number; tabId: number; windowId: number }) => void>;
        export const onAttached: events.Event<(tabId: number, attachInfo: { newWindowId: number; newPosition: number }) => void>;
        export const onCreated: events.Event<(tab: browser.Tab) => void>;
        export const onDetached: events.Event<(tabId: number, detachInfo: { oldWindowId: number; oldPosition: number }) => void>;
        export const onHighlighted: events.Event<(highlightInfo: { windowId: number; tabIds: number[] }) => void>;
        export const onMoved: events.Event<(tabId: number, moveInfo: { windowId: number; fromIndex: number; toIndex: number }) => void>;
        export const onRemoved: events.Event<(tabId: number, removeInfo: { windowId: number; isWindowClosing: boolean }) => void>;
        export const onReplaced: events.Event<(addedTabId: number, removedTabId: number) => void>;
        export const onUpdated: events.Event<(tabId: number, changeInfo: browser.Tab, tab: browser.Tab) => void>;
        export function create(properties: browser.TabUpdateOptions & { index?: number; openInReaderMode?: boolean; title?: string; windowId?: number }, callback: (result: browser.Tab) => void): void;
        export function create(properties: browser.TabUpdateOptions & { index?: number; openInReaderMode?: boolean; title?: string; windowId?: number }): Promise<browser.Tab>;
        export function query(info: browser.TabQueryOptions, callback: (result: browser.Tab[]) => void): void;
        export function query(info: browser.TabQueryOptions): Promise<browser.Tab[]>;
        export function get(tabID: number, callback: (result: browser.Tab) => void): void;
        export function get(tabID: number): Promise<browser.Tab>;
        export function getCurrent(callback: (result: browser.Tab | undefined) => void): void;
        export function getCurrent(): Promise<browser.Tab | undefined>;
        export function getSelected(windowID: number, callback: (result: browser.Tab | undefined) => void): void;
        export function getSelected(callback: (result: browser.Tab | undefined) => void): void;
        export function getSelected(windowID?: number): Promise<browser.Tab | undefined>;
        export function duplicate(tabID: number, properties: { active?: boolean; index?: number }, callback: (result: browser.Tab | undefined) => void): void;
        export function duplicate(tabID: number, callback: (result: browser.Tab | undefined) => void): void;
        export function duplicate(tabID: number, properties?: { active?: boolean; index?: number }): Promise<browser.Tab | undefined>;
        export function update(tabID: number, properties: browser.TabUpdateOptions, callback: (result: browser.Tab) => void): void;
        export function update(tabID: number, properties: browser.TabUpdateOptions): Promise<browser.Tab>;
        export function update(properties: browser.TabUpdateOptions, callback: (result: browser.Tab) => void): void;
        export function update(properties: browser.TabUpdateOptions): Promise<browser.Tab>;
        export function move(tabIDs: number | number[], properties: { index: number; windowId?: number }, callback: (result: browser.Tab | browser.Tab[]) => void): void;
        export function move(tabIDs: number | number[], properties: { index: number; windowId?: number }): Promise<browser.Tab | browser.Tab[]>;
        export function remove(tabIDs: number | number[], callback: () => void): void;
        export function remove(tabIDs: number | number[]): Promise<void>;
        export function reload(tabID: number, properties: { bypassCache?: boolean }, callback: () => void): void;
        export function reload(tabID: number, callback: () => void): void;
        export function reload(tabID: number, properties?: { bypassCache?: boolean }): Promise<void>;
        export function reload(properties: { bypassCache?: boolean }, callback: () => void): void;
        export function reload(callback: () => void): void;
        export function reload(properties?: { bypassCache?: boolean }): Promise<void>;
        export function goBack(tabID: number, callback: () => void): void;
        export function goBack(callback: () => void): void;
        export function goBack(tabID?: number): Promise<void>;
        export function goForward(tabID: number, callback: () => void): void;
        export function goForward(callback: () => void): void;
        export function goForward(tabID?: number): Promise<void>;
        export function getZoom(tabID: number, callback: (result: number) => void): void;
        export function getZoom(callback: (result: number) => void): void;
        export function getZoom(tabID?: number): Promise<number>;
        export function setZoom(tabID: number, zoomFactor: number, callback: () => void): void;
        export function setZoom(tabID: number, zoomFactor: number): Promise<void>;
        export function setZoom(zoomFactor: number, callback: () => void): void;
        export function setZoom(zoomFactor: number): Promise<void>;
        export function detectLanguage(tabID: number, callback: (result: string) => void): void;
        export function detectLanguage(callback: (result: string) => void): void;
        export function detectLanguage(tabID?: number): Promise<string>;
        export function toggleReaderMode(tabID: number, callback: () => void): void;
        export function toggleReaderMode(callback: () => void): void;
        export function toggleReaderMode(tabID?: number): Promise<void>;
        export function captureVisibleTab(windowID: number, options: { format?: string; quality?: number }, callback: (result: string) => void): void;
        export function captureVisibleTab(windowID: number, callback: (result: string) => void): void;
        export function captureVisibleTab(windowID: number, options?: { format?: string; quality?: number }): Promise<string>;
        export function captureVisibleTab(options: { format?: string; quality?: number }, callback: (result: string) => void): void;
        export function captureVisibleTab(callback: (result: string) => void): void;
        export function captureVisibleTab(options?: { format?: string; quality?: number }): Promise<string>;
        export function executeScript(tabID: number, details: browser.TabScriptInjection, callback: (result: unknown[]) => void): void;
        export function executeScript(tabID: number, details: browser.TabScriptInjection): Promise<unknown[]>;
        export function executeScript(details: browser.TabScriptInjection, callback: (result: unknown[]) => void): void;
        export function executeScript(details: browser.TabScriptInjection): Promise<unknown[]>;
        export function insertCSS(tabID: number, details: browser.TabScriptInjection, callback: () => void): void;
        export function insertCSS(tabID: number, details: browser.TabScriptInjection): Promise<void>;
        export function insertCSS(details: browser.TabScriptInjection, callback: () => void): void;
        export function insertCSS(details: browser.TabScriptInjection): Promise<void>;
        export function removeCSS(tabID: number, details: browser.TabScriptInjection, callback: () => void): void;
        export function removeCSS(tabID: number, details: browser.TabScriptInjection): Promise<void>;
        export function removeCSS(details: browser.TabScriptInjection, callback: () => void): void;
        export function removeCSS(details: browser.TabScriptInjection): Promise<void>;
        export function sendMessage<T = unknown, R = unknown>(tabID: number, message: T, options: browser.MessageOptions, callback: (result: R) => void): void;
        export function sendMessage<T = unknown, R = unknown>(tabID: number, message: T, callback: (result: R) => void): void;
        export function sendMessage<T = unknown, R = unknown>(tabID: number, message: T, options?: browser.MessageOptions): Promise<R>;
        export function connect(tabID: number, options?: { frameId?: number; documentId?: string; name?: string }): browser.runtime.Port;
    }

    export namespace test {
        export const onMessage: events.Event<(message: string, argument?: unknown) => void>;
        export const onTestStarted: events.Event<(testName: string) => void>;
        export const onTestFinished: events.Event<(result: boolean, message?: string) => void>;
        export function notifyFail(message?: string): void;
        export function notifyPass(message?: string): void;
        export function sendMessage(message: string, argument?: unknown): void;
        export function runWithUserGesture<T>(func: () => T): T;
        export function isProcessingUserGesture(): boolean;
        export function log(message: unknown): void;
        export function fail(message?: string): void;
        export function succeed(message?: string): void;
        export function assertTrue(actualValue: boolean, message?: string): void;
        export function assertFalse(actualValue: boolean, message?: string): void;
        export function assertDeepEq<T>(actualValue: T, expectedValue: T, message?: string): void;
        export function assertEq<T>(actualValue: T, expectedValue: T, message?: string): void;
        export function assertRejects<T>(promise: Promise<T>, expectedError?: unknown, message?: string): Promise<T>;
        export function assertResolves<T>(promise: Promise<T>, expectedError?: unknown, message?: string): Promise<T>;
        export function assertThrows(func: (...args: unknown[]) => unknown, expectedError?: unknown, message?: string): void;
        export function assertSafe<T>(func: (...args: unknown[]) => T, message?: string): T;
        export function assertSafeResolve<T>(func: (...args: unknown[]) => T, message?: string): T;
        export function addTest(func: () => void | Promise<void>): void;
        export function runTests(tests: (() => void | Promise<void>)[]): void;
    }

    export namespace webNavigation {
        export const onBeforeNavigate: events.Event<(details: { url: string; tabId: number; frameId: number; parentFrameId: number; timeStamp: number; documentId?: string }) => void>;
        export const onCommitted: events.Event<(details: { url: string; tabId: number; frameId: number; parentFrameId: number; timeStamp: number; documentId?: string }) => void>;
        export const onDOMContentLoaded: events.Event<(details: { url: string; tabId: number; frameId: number; parentFrameId: number; timeStamp: number; documentId?: string }) => void>;
        export const onCompleted: events.Event<(details: { url: string; tabId: number; frameId: number; parentFrameId: number; timeStamp: number; documentId?: string }) => void>;
        export const onErrorOccurred: events.Event<(details: { url: string; tabId: number; frameId: number; parentFrameId: number; timeStamp: number; documentId?: string }) => void>;
        export function getFrame(details: { tabId: number; frameId: number }, callback: (result: browser.FrameDetails | null) => void): void;
        export function getFrame(details: { tabId: number; frameId: number }): Promise<browser.FrameDetails | null>;
        export function getAllFrames(details: { tabId: number }, callback: (result: browser.FrameDetails[]) => void): void;
        export function getAllFrames(details: { tabId: number }): Promise<browser.FrameDetails[]>;
    }

    export namespace webRequest {
        export const onBeforeRequest: events.WebRequestEvent<(details: browser.WebRequestDetails & { requestBody?: { formData?: Record<string, unknown[]>; raw?: { bytes?: unknown }[]; error?: string } }) => void>;
        export const onBeforeSendHeaders: events.WebRequestEvent<(details: browser.WebRequestDetails) => void>;
        export const onSendHeaders: events.WebRequestEvent<(details: browser.WebRequestDetails) => void>;
        export const onHeadersReceived: events.WebRequestEvent<(details: browser.WebRequestDetails) => void>;
        export const onAuthRequired: events.WebRequestEvent<(details: browser.WebRequestDetails) => void>;
        export const onBeforeRedirect: events.WebRequestEvent<(details: browser.WebRequestDetails) => void>;
        export const onResponseStarted: events.WebRequestEvent<(details: browser.WebRequestDetails) => void>;
        export const onCompleted: events.WebRequestEvent<(details: browser.WebRequestDetails) => void>;
        export const onErrorOccurred: events.WebRequestEvent<(details: browser.WebRequestDetails) => void>;
    }

    export namespace windows {
        export const WINDOW_ID_NONE: number;
        export const WINDOW_ID_CURRENT: number;
        export const onCreated: events.Event<(window: browser.Window) => void>;
        export const onRemoved: events.Event<(windowId: number) => void>;
        export const onFocusChanged: events.Event<(windowId: number) => void>;
        export function create(info: browser.WindowUpdateOptions & { type?: browser.WindowType; incognito?: boolean; url?: string | string[]; tabId?: number }, callback: (result: browser.Window | undefined) => void): void;
        export function create(callback: (result: browser.Window | undefined) => void): void;
        export function create(info?: browser.WindowUpdateOptions & { type?: browser.WindowType; incognito?: boolean; url?: string | string[]; tabId?: number }): Promise<browser.Window | undefined>;
        export function get(windowID: number, properties: browser.WindowQueryOptions, callback: (result: browser.Window) => void): void;
        export function get(windowID: number, callback: (result: browser.Window) => void): void;
        export function get(windowID: number, properties?: browser.WindowQueryOptions): Promise<browser.Window>;
        export function getCurrent(info: browser.WindowQueryOptions, callback: (result: browser.Window) => void): void;
        export function getCurrent(callback: (result: browser.Window) => void): void;
        export function getCurrent(info?: browser.WindowQueryOptions): Promise<browser.Window>;
        export function getLastFocused(info: browser.WindowQueryOptions, callback: (result: browser.Window) => void): void;
        export function getLastFocused(callback: (result: browser.Window) => void): void;
        export function getLastFocused(info?: browser.WindowQueryOptions): Promise<browser.Window>;
        export function getAll(info: browser.WindowQueryOptions, callback: (result: browser.Window[]) => void): void;
        export function getAll(callback: (result: browser.Window[]) => void): void;
        export function getAll(info?: browser.WindowQueryOptions): Promise<browser.Window[]>;
        export function update(windowID: number, properties: browser.WindowUpdateOptions, callback: (result: browser.Window) => void): void;
        export function update(windowID: number, properties: browser.WindowUpdateOptions): Promise<browser.Window>;
        export function remove(windowID: number, callback: () => void): void;
        export function remove(windowID: number): Promise<void>;
    }

}

declare namespace chrome {
    export import action = browser.action;
    export import alarms = browser.alarms;
    export import bookmarks = browser.bookmarks;
    export import browserAction = browser.action;
    export import cookies = browser.cookies;
    export import commands = browser.commands;
    export import contextMenus = browser.menus;
    export import declarativeNetRequest = browser.declarativeNetRequest;
    export import devtools = browser.devtools;
    export import dom = browser.dom;
    export import extension = browser.extension;
    export import i18n = browser.i18n;
    export import menus = browser.menus;
    export import notifications = browser.notifications;
    export import offscreen = browser.offscreen;
    export import pageAction = browser.action;
    export import permissions = browser.permissions;
    export import runtime = browser.runtime;
    export import scripting = browser.scripting;
    export import sidebarAction = browser.sidebarAction;
    export import sidePanel = browser.sidePanel;
    export import storage = browser.storage;
    export import tabs = browser.tabs;
    export import test = browser.test;
    export import webNavigation = browser.webNavigation;
    export import webRequest = browser.webRequest;
    export import windows = browser.windows;
}
