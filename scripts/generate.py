#!/usr/bin/env python3
#
# Copyright (C) 2026 Patrick Kettner. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.

"""
Generates TypeScript declarations for Safari WebExtensions from WebKit's
WebExtension WebIDL.

Existence of every declared member is derived from the parsed IDL. Emission
iterates the parsed interface and looks each member up in SIGNATURE_OVERRIDES;
a member the IDL does not declare has nothing to iterate over and therefore
cannot be emitted. Two reconciliation errors close the loop:

  - an override that matched no parsed member fails the build, so a table entry
    naming a member WebKit does not declare aborts generation rather than
    shipping a declaration;
  - a parsed member that produced no output and carries no recorded skip reason
    fails the build, so a member WebKit adds cannot be silently dropped.

Every override carries at least one citation, re-resolved against the same
WebKit revision the declarations are generated from. A claim whose evidence no
longer resolves fails the build.
"""

import argparse
import dataclasses
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request

RAW_BASE_URL = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"

INTERFACES_DIR = "Source/WebKit/WebProcess/Extensions/Interfaces"

KNOWN_IDL_FILES = [
    'WebExtensionAPIAction.idl',
    'WebExtensionAPIAlarms.idl',
    'WebExtensionAPIBookmarks.idl',
    'WebExtensionAPICommands.idl',
    'WebExtensionAPICookies.idl',
    'WebExtensionAPIDeclarativeNetRequest.idl',
    'WebExtensionAPIDevTools.idl',
    'WebExtensionAPIDevToolsExtensionPanel.idl',
    'WebExtensionAPIDevToolsInspectedWindow.idl',
    'WebExtensionAPIDevToolsNetwork.idl',
    'WebExtensionAPIDevToolsPanels.idl',
    'WebExtensionAPIDOM.idl',
    'WebExtensionAPIEvent.idl',
    'WebExtensionAPIExtension.idl',
    'WebExtensionAPILocalization.idl',
    'WebExtensionAPIMenus.idl',
    'WebExtensionAPINamespace.idl',
    'WebExtensionAPINotifications.idl',
    'WebExtensionAPIOffscreen.idl',
    'WebExtensionAPIPermissions.idl',
    'WebExtensionAPIPort.idl',
    'WebExtensionAPIRuntime.idl',
    'WebExtensionAPIScripting.idl',
    'WebExtensionAPISidebarAction.idl',
    'WebExtensionAPISidePanel.idl',
    'WebExtensionAPIStorage.idl',
    'WebExtensionAPIStorageArea.idl',
    'WebExtensionAPITabs.idl',
    'WebExtensionAPITest.idl',
    'WebExtensionAPIWebNavigation.idl',
    'WebExtensionAPIWebNavigationEvent.idl',
    'WebExtensionAPIWebPageNamespace.idl',
    'WebExtensionAPIWebPageRuntime.idl',
    'WebExtensionAPIWebRequest.idl',
    'WebExtensionAPIWebRequestEvent.idl',
    'WebExtensionAPIWindows.idl',
    'WebExtensionAPIWindowsEvent.idl',
]

TYPE_MAP = {
    'DOMString': 'string',
    'boolean': 'boolean',
    'double': 'number',
    'float': 'number',
    'long': 'number',
    'unsigned long': 'number',
    'unsigned short': 'number',
    'short': 'number',
    'any': 'unknown',
    'void': 'void',
    'function': '(...args: never[]) => void',
    'array': 'unknown[]',
    'object': 'Record<string, unknown>',
    'JSONValue': 'unknown',
    'JSValueRef': 'unknown',
    'WebExtensionAPIPort': 'browser.runtime.Port',
    'WebExtensionAPIStorageArea': 'browser.storage.StorageArea',
    'WebExtensionAPIWebPageRuntime': 'unknown',
    'WebExtensionAPITest': 'unknown',
    'WebExtensionAPIDevToolsInspectedWindow': 'browser.devtools.InspectedWindow',
    'WebExtensionAPIDevToolsNetwork': 'browser.devtools.Network',
    'WebExtensionAPIDevToolsPanels': 'browser.devtools.Panels',
}

RESERVED_WORDS = {
    'function': 'func',
    'var': 'variable',
    'default': 'defaultValue',
    'delete': 'deleteArg',
    'in': 'inArg',
}

ROOT_NAMESPACES = {
    'WebExtensionAPIAction': 'action',
    'WebExtensionAPIAlarms': 'alarms',
    'WebExtensionAPIBookmarks': 'bookmarks',
    'WebExtensionAPICommands': 'commands',
    'WebExtensionAPICookies': 'cookies',
    'WebExtensionAPIDeclarativeNetRequest': 'declarativeNetRequest',
    'WebExtensionAPIDevTools': 'devtools',
    'WebExtensionAPIDOM': 'dom',
    'WebExtensionAPIExtension': 'extension',
    'WebExtensionAPILocalization': 'i18n',
    'WebExtensionAPIMenus': 'menus',
    'WebExtensionAPINotifications': 'notifications',
    'WebExtensionAPIOffscreen': 'offscreen',
    'WebExtensionAPIPermissions': 'permissions',
    'WebExtensionAPIRuntime': 'runtime',
    'WebExtensionAPIScripting': 'scripting',
    'WebExtensionAPISidebarAction': 'sidebarAction',
    'WebExtensionAPISidePanel': 'sidePanel',
    'WebExtensionAPIStorage': 'storage',
    'WebExtensionAPITabs': 'tabs',
    'WebExtensionAPITest': 'test',
    'WebExtensionAPIWebNavigation': 'webNavigation',
    'WebExtensionAPIWebRequest': 'webRequest',
    'WebExtensionAPIWindows': 'windows',
}

# Namespace to Primary Entity name mapping for algorithmic derivation
NAMESPACE_PRIMARY_ENTITIES = {
    'action': 'ActionDetails',
    'alarms': 'Alarm',
    'bookmarks': 'BookmarkTreeNode',
    'commands': 'Command',
    'cookies': 'Cookie',
    'declarativeNetRequest': 'DNRRule',
    'extension': 'ViewFilter',
    'menus': 'MenuItemProperties',
    'offscreen': 'OffscreenCreateParameters',
    'permissions': 'Permissions',
    'runtime': 'PlatformInfo',
    'scripting': 'RegisteredContentScript',
    'sidebarAction': 'SidebarActionDetails',
    'sidePanel': 'SidePanelOptions',
    'tabs': 'Tab',
    'webNavigation': 'WebNavigationGetFrameDetails',
    'webRequest': 'WebRequestDetails',
    'windows': 'Window',
}


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Cite:
    """A re-resolvable pointer into WebKit source.

    `path` is repository-relative and `quote` must appear in that file at the
    revision the declarations are generated from. Both sides are compared with
    runs of whitespace collapsed, so reindentation does not break a citation
    but a token change does.

    With `absent` set the test inverts: the quote must NOT appear. That is how a
    claim about something WebKit does not do stays checkable. It only holds for
    a file narrow enough that the quote would have to be there if the behaviour
    existed, so the path carries the weight and belongs in the entry's comment.
    """

    path: str
    quote: str
    absent: bool = False


# Stands for the member's own declaration in the IDL file it was parsed from.
# The quote is taken from the parsed source span rather than transcribed, so
# these citations cannot drift from what the parser actually read.
DECLARATION = Cite('<declaration>', '')


@dataclasses.dataclass(frozen=True)
class Override:
    """A hand-supplied signature for a member the IDL declares.

    `sig` holds the emitted TypeScript lines without leading indentation. It is
    used only when a parsed member matches the table key, so an entry can
    change how a member is declared but can never introduce one.
    """

    sig: tuple
    cites: tuple = (DECLARATION,)
    doc: tuple = ()

    def __init__(self, sig, cites=(DECLARATION,), doc=()):
        if isinstance(sig, str):
            sig = (sig,)
        if isinstance(doc, str):
            doc = (doc,)
        object.__setattr__(self, 'sig', tuple(sig))
        object.__setattr__(self, 'cites', tuple(cites))
        object.__setattr__(self, 'doc', tuple(doc))
        if not self.cites:
            raise ValueError('an override must carry at least one citation')

    def lines(self):
        """The declaration, preceded by its doc comment if it carries one."""
        if not self.doc:
            return self.sig
        out = ['/**']
        out.extend(f' * {line}'.rstrip() for line in self.doc)
        out.append(' */')
        out.extend(self.sig)
        return tuple(out)


class CitationError(RuntimeError):
    pass


class ReconciliationError(RuntimeError):
    pass


def norm_ws(text):
    return ' '.join(text.split())


def normalized_with_lines(text):
    """Whitespace-collapsed text plus the source line each character came from."""
    chars = []
    lines = []
    lineno = 1
    prev_space = True
    for ch in text:
        if ch.isspace():
            if not prev_space:
                chars.append(' ')
                lines.append(lineno)
                prev_space = True
            if ch == '\n':
                lineno += 1
        else:
            chars.append(ch)
            lines.append(lineno)
            prev_space = False
    return ''.join(chars), lines


class SourceResolver:
    """Reads WebKit files at one fixed revision."""

    def read(self, path):
        raise NotImplementedError

    def describe(self):
        raise NotImplementedError


class GitCheckoutResolver(SourceResolver):
    def __init__(self, root, ref):
        self.root = pathlib.Path(root)
        self.ref = ref
        self._cache = {}

    def read(self, path):
        if path not in self._cache:
            result = subprocess.run(
                ['git', '-C', str(self.root), 'show', f'{self.ref}:{path}'],
                capture_output=True,
            )
            if result.returncode != 0:
                raise CitationError(
                    f'{path} does not exist at {self.describe()}: '
                    f'{result.stderr.decode(errors="replace").strip()}'
                )
            self._cache[path] = result.stdout.decode(errors='replace')
        return self._cache[path]

    def describe(self):
        return f'{self.root}@{self.ref}'


class RemoteResolver(SourceResolver):
    def __init__(self, repo, ref, cache_dir=None):
        self.repo = repo
        self.ref = ref
        self.cache_dir = pathlib.Path(cache_dir) if cache_dir else None
        self._cache = {}

    def _cache_path(self, path):
        if not self.cache_dir:
            return None
        safe = re.sub(r'[^A-Za-z0-9._-]', '_', f'{self.repo}@{self.ref}/{path}')
        return self.cache_dir / safe

    def read(self, path):
        if path in self._cache:
            return self._cache[path]

        cached = self._cache_path(path)
        if cached and cached.exists():
            self._cache[path] = cached.read_text(errors='replace')
            return self._cache[path]

        url = RAW_BASE_URL.format(repo=self.repo, ref=self.ref, path=path)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "safari-webextension-types-generator"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode(errors='replace')
        except Exception as e:
            raise CitationError(f'could not read {path} from {self.describe()}: {e}')

        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(text)
        self._cache[path] = text
        return text

    def describe(self):
        return f'{self.repo}@{self.ref}'


class IdlDirResolver(SourceResolver):
    """Serves the IDL directory from a local path, delegating anything else.

    Used by --idl-dir, where the interface files come from disk but citations
    into implementation files still have to resolve somewhere. The delegate is
    reported separately in the provenance so the two revisions cannot be
    conflated by a reader.
    """

    def __init__(self, directory, delegate=None):
        self.directory = pathlib.Path(directory)
        self.delegate = delegate

    def read(self, path):
        if path.startswith(INTERFACES_DIR + '/'):
            local = self.directory / pathlib.PurePosixPath(path).name
            if not local.exists():
                raise CitationError(
                    f'{local} does not exist. --idl-dir supplies every interface '
                    f'file or none; falling back to another revision for one of '
                    f'them would mix two sources in one output.'
                )
            return local.read_text(errors='replace')
        if self.delegate is None:
            raise CitationError(
                f'{path} is outside the IDL directory {self.directory} and no '
                f'--webkit-checkout or remote revision was given to resolve it against'
            )
        return self.delegate.read(path)

    def describe(self):
        if self.delegate is None:
            return str(self.directory)
        return f'{self.directory} (citations outside {INTERFACES_DIR} from {self.delegate.describe()})'


# ---------------------------------------------------------------------------
# Signature overrides
#
# Keyed by (IDL interface, member). An entry is consulted only when the parser
# reports that member, and an entry that matches nothing fails the build.
# ---------------------------------------------------------------------------

API_KEYS = 'Source/WebKit/WebProcess/Extensions/API/WebExtensionAPIKeys.h'
COOKIES_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm'
PORT_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPortCocoa.mm'
RUNTIME_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm'
SCRIPTING_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIScriptingCocoa.mm'
STORAGE_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIStorageCocoa.mm'
STORAGE_AREA_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIStorageAreaCocoa.mm'
NOTIFICATIONS_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPINotificationsCocoa.mm'
TABS_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm'
MENUS_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIMenusCocoa.mm'
DEVTOOLS_INSPECTED_WINDOW_COCOA = (
    'Source/WebKit/WebProcess/Extensions/API/Cocoa/'
    'WebExtensionAPIDevToolsInspectedWindowCocoa.mm')

# Every dispatcher for an API lives in that API's own Cocoa file. The
# notifications file contains no listener invocation at all, which is the whole
# evidence that its two events never fire.
NOTIFICATIONS_NEVER_DISPATCH = Cite(NOTIFICATIONS_COCOA, 'invokeListeners', absent=True)

WEB_NAVIGATION_COCOA = (
    'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWebNavigationCocoa.mm')

# One dictionary is built and handed to whichever of the five navigation events
# fired, so they all carry the same payload.
WEB_NAVIGATION_DETAILS = (
    DECLARATION,
    Cite(WEB_NAVIGATION_COCOA,
         'NSMutableDictionary *navigationDetails = [@{ urlKey: frameURL.string()'
         '.createNSString().get(), tabIdKey: @(toWebAPI(tabID)), frameIdKey: '
         '@(toWebAPI(frameID)), parentFrameIdKey: @(toWebAPI(parentFrameID)), '
         'timeStampKey: @(floor(timestamp.approximate<WallTime>().secondsSinceEpoch()'
         '.milliseconds())) } mutableCopy];'),
    Cite(WEB_NAVIGATION_COCOA,
         'if (frameParameters.documentIdentifier) navigationDetails[documentIdKey] = '
         'frameParameters.documentIdentifier.value().toString().createNSString().get();'),
)

WEB_NAVIGATION_PAYLOAD = (
    'events.Event<(details: { url: string; tabId: number; frameId: number; '
    'parentFrameId: number; timeStamp: number; documentId?: string }) => void>')

# Names the sync area alone exposes, and the test that gates them on it.
SYNC_ONLY_STORAGE_PROPERTIES = Cite(
    STORAGE_AREA_COCOA,
    'static NeverDestroyed<HashSet<AtomString>> syncStorageProperties { HashSet { '
    'AtomString("QUOTA_BYTES_PER_ITEM"_s), AtomString("MAX_ITEMS"_s), '
    'AtomString("MAX_WRITE_OPERATIONS_PER_HOUR"_s), '
    'AtomString("MAX_WRITE_OPERATIONS_PER_MINUTE"_s) } }; '
    'if (syncStorageProperties.get().contains(propertyName)) '
    'return m_type == WebExtensionDataType::Sync;')

SIGNATURE_OVERRIDES = {
    # -- events.Event / events.WebRequestEvent ------------------------------
    ('WebExtensionAPIEvent', 'addListener'): Override(
        'addListener(callback: T): void;'),
    ('WebExtensionAPIEvent', 'removeListener'): Override(
        'removeListener(callback: T): void;'),
    ('WebExtensionAPIEvent', 'hasListener'): Override(
        'hasListener(callback: T): boolean;'),
    ('WebExtensionAPIWebRequestEvent', 'addListener'): Override(
        'addListener(callback: T, filter?: browser.WebRequestFilter, '
        'extraInfoSpec?: string[]): void;'),

    # -- runtime.Port -------------------------------------------------------
    ('WebExtensionAPIPort', 'name'): Override(
        'name: string;'),
    ('WebExtensionAPIPort', 'sender'): Override(
        'sender?: browser.MessageSender;'),
    ('WebExtensionAPIPort', 'onDisconnect'): Override(
        'onDisconnect: events.Event<(port: Port) => void>;'),
    ('WebExtensionAPIPort', 'onMessage'): Override(
        'onMessage: events.Event<(message: unknown, port: Port) => void>;'),
    ('WebExtensionAPIPort', 'postMessage'): Override(
        'postMessage<T = unknown>(message: T): void;'),
    ('WebExtensionAPIPort', 'disconnect'): Override(
        'disconnect(): void;'),
    # WebKit stores whatever reportError() returned, which is a JavaScript Error
    # built from the failure message, and nil until a failure occurs.
    ('WebExtensionAPIPort', 'error'): Override(
        'error?: Error;',
        (DECLARATION,
         Cite(PORT_COCOA, 'JSValue *WebExtensionAPIPort::error() { return m_error.get(); }'),
         Cite(RUNTIME_COCOA,
              'port->setError(protect(runtime())->reportError(result.error()'
              '.createNSString().get(), globalContext.get()));'),
         Cite(RUNTIME_COCOA,
              'auto *result = [JSValue valueWithNewErrorFromMessage:errorMessage'
              '.createNSString().get() inContext:context];'))),

    # -- storage.StorageArea ------------------------------------------------
    ('WebExtensionAPIStorageArea', 'get'): Override((
        'get<T = Record<string, unknown>>(callback: (items: T) => void): void;',
        'get<T = Record<string, unknown>>(keys?: string | string[] | '
        'Record<string, unknown> | null): Promise<T>;',
        'get<T = Record<string, unknown>>(keys: string | string[] | '
        'Record<string, unknown> | null, callback: (items: T) => void): void;',
    )),
    ('WebExtensionAPIStorageArea', 'set'): Override((
        'set(items: Record<string, unknown>): Promise<void>;',
        'set(items: Record<string, unknown>, callback: () => void): void;',
    )),
    ('WebExtensionAPIStorageArea', 'remove'): Override((
        'remove(keys: string | string[]): Promise<void>;',
        'remove(keys: string | string[], callback: () => void): void;',
    )),
    ('WebExtensionAPIStorageArea', 'clear'): Override((
        'clear(): Promise<void>;',
        'clear(callback: () => void): void;',
    )),
    ('WebExtensionAPIStorageArea', 'getBytesInUse'): Override((
        'getBytesInUse(callback: (bytesInUse: number) => void): void;',
        'getBytesInUse(keys?: string | string[] | null): Promise<number>;',
        'getBytesInUse(keys: string | string[] | null, '
        'callback: (bytesInUse: number) => void): void;',
    )),
    ('WebExtensionAPIStorageArea', 'getKeys'): Override((
        'getKeys(callback: (keys: string[]) => void): void;',
        'getKeys(): Promise<string[]>;',
    ), (DECLARATION,
        Cite(STORAGE_AREA_COCOA,
             'Messages::WebExtensionContext::StorageGetKeys(webPageProxyIdentifier, '
             'm_type), [protectedThis = Ref { *this }, callback = WTF::move(callback)]'
             '(Expected<Vector<String>, WebExtensionError>&& result) {'))),
    ('WebExtensionAPIStorageArea', 'setAccessLevel'): Override((
        'setAccessLevel(accessOptions: browser.StorageAccessOptions): Promise<void>;',
        'setAccessLevel(accessOptions: browser.StorageAccessOptions, '
        'callback: () => void): void;',
    ), (DECLARATION,
        Cite(STORAGE_AREA_COCOA,
             'NSString *accessLevelString = accessOptions[accessLevelKey];'))),
    # Both storage.onChanged and the per-area onChanged receive the same two
    # arguments from the same dispatch.
    ('WebExtensionAPIStorageArea', 'onChanged'): Override(
        'onChanged: events.Event<(changes: Record<string, browser.StorageChange>, '
        'areaName: string) => void>;',
        (DECLARATION,
         Cite(STORAGE_COCOA,
              'namespaceObject.storage().storageAreaForType(dataType).onChanged()'
              '.invokeListenersWithArgument(changes, areaName.get());'))),
    ('WebExtensionAPIStorageArea', 'QUOTA_BYTES'): Override(
        'QUOTA_BYTES: number;',
        (DECLARATION,
         Cite(STORAGE_AREA_COCOA,
              'case WebExtensionDataType::Local: return webExtensionStorageAreaLocalQuotaBytes;'))),
    ('WebExtensionAPIStorageArea', 'QUOTA_BYTES_PER_ITEM'): Override(
        'QUOTA_BYTES_PER_ITEM: number;',
        (DECLARATION, SYNC_ONLY_STORAGE_PROPERTIES)),
    ('WebExtensionAPIStorageArea', 'MAX_ITEMS'): Override(
        'MAX_ITEMS: number;',
        (DECLARATION, SYNC_ONLY_STORAGE_PROPERTIES)),
    ('WebExtensionAPIStorageArea', 'MAX_WRITE_OPERATIONS_PER_HOUR'): Override(
        'MAX_WRITE_OPERATIONS_PER_HOUR: number;',
        (DECLARATION, SYNC_ONLY_STORAGE_PROPERTIES)),
    ('WebExtensionAPIStorageArea', 'MAX_WRITE_OPERATIONS_PER_MINUTE'): Override(
        'MAX_WRITE_OPERATIONS_PER_MINUTE: number;',
        (DECLARATION, SYNC_ONLY_STORAGE_PROPERTIES)),
    ('WebExtensionAPIStorage', 'sync'): Override(
        'export const sync: browser.storage.SyncStorageArea;',
        (DECLARATION, SYNC_ONLY_STORAGE_PROPERTIES)),

    # -- devtools sub-interfaces --------------------------------------------
    ('WebExtensionAPIDevToolsInspectedWindow', 'tabId'): Override(
        'tabId: number;'),
    # WebKit calls the callback with one argument, the two-element array
    # [result, exceptionObject], and builds that object with the literal keys
    # "isExceptionKey" and "valueKey". The callback parameter list is left open
    # rather than asserting either shape.
    ('WebExtensionAPIDevToolsInspectedWindow', 'eval'): Override(
        'eval<T = unknown>(expression: string, options?: browser.DevToolsEvalOptions, '
        'callback?: (...args: unknown[]) => void): Promise<T>;',
        (DECLARATION,
         Cite(DEVTOOLS_INSPECTED_WINDOW_COCOA,
              'callback->call(fromArray(globalContext, { Protected(globalContext, '
              'scriptResult.get()), Protected(globalContext, undefinedValue) }));'),
         Cite(DEVTOOLS_INSPECTED_WINDOW_COCOA,
              'SUPPRESS_UNCOUNTED_ARG auto resultObject = fromObject(globalContext, { '
              '{ "isExceptionKey"_s, Protected(globalContext, JSValueMakeBoolean('
              'globalContext, true)) }, { "valueKey"_s, Protected(globalContext, '
              'valueData) } });')),
        doc=('@deprecated The callback receives one argument, a two-element array '
             'of the result and, on failure, an error object. Prefer the promise. '
             'WebKit builds that error object with the literal keys '
             '"isExceptionKey" and "valueKey", which are the names of its key '
             'constants rather than their values.',)),
    ('WebExtensionAPIDevToolsInspectedWindow', 'reload'): Override(
        'reload(reloadOptions?: browser.DevToolsReloadOptions): void;'),
    ('WebExtensionAPIDevToolsNetwork', 'onNavigated'): Override(
        'onNavigated: events.Event<(url: string) => void>;'),
    ('WebExtensionAPIDevToolsPanels', 'themeName'): Override(
        'themeName: string;'),
    ('WebExtensionAPIDevToolsPanels', 'onThemeChanged'): Override(
        'onThemeChanged: events.Event<(themeName: string) => void>;'),
    ('WebExtensionAPIDevToolsPanels', 'create'): Override(
        'create(title: string, iconPath: string, pagePath: string, '
        'callback?: (panel: Record<string, unknown>) => void): void;'),

    # -- root namespace events ----------------------------------------------
    ('WebExtensionAPIAction', 'onClicked'): Override(
        'export const onClicked: events.Event<(tab: browser.Tab) => void>;'),
    ('WebExtensionAPIAlarms', 'onAlarm'): Override(
        'export const onAlarm: events.Event<(alarm: browser.Alarm) => void>;'),
    ('WebExtensionAPICommands', 'onCommand'): Override(
        'export const onCommand: events.Event<(command: string) => void>;'),
    ('WebExtensionAPICommands', 'onChanged'): Override(
        'export const onChanged: events.Event<(changeInfo: { name: string; '
        'oldShortcut: string; newShortcut: string }) => void>;'),
    ('WebExtensionAPICookies', 'onChanged'): Override(
        'export const onChanged: events.Event<(...args: unknown[]) => void>;',
        (DECLARATION,
         Cite(COOKIES_COCOA,
              '// FIXME: <https://webkit.org/b/267514> Add support for changeInfo. '
              'enumerateNamespaceObjects([&](auto& namespaceObject) { '
              'namespaceObject.cookies().onChanged().invokeListeners(); });')),
        doc=('@deprecated Safari fires this event with no arguments. WebKit has '
             'not implemented changeInfo; see https://webkit.org/b/267514. A '
             'listener parameter will be undefined at runtime.',)),
    ('WebExtensionAPIDeclarativeNetRequest', 'onRuleMatchedDebug'): Override(
        'export const onRuleMatchedDebug: events.Event<(info: browser.DNRMatchedRule) '
        '=> void>;'),
    ('WebExtensionAPIMenus', 'onClicked'): Override(
        'export const onClicked: events.Event<(info: { menuItemId: number | string; '
        'parentMenuItemId?: number | string; checked?: boolean; wasChecked?: boolean; '
        'selectionText?: string; srcUrl?: string; mediaType?: "audio" | "image" | "video"; '
        'linkUrl?: string; linkText?: string; editable?: boolean; frameId?: number; '
        'pageUrl?: string; frameUrl?: string }, tab?: browser.Tab) => void>;',
        (DECLARATION,
         Cite(MENUS_COCOA, 'info[menuItemIDKey] = toMenuIdentifierWebAPI(menuItemParameters.identifier);'),
         Cite(MENUS_COCOA,
              'if (menuItemParameters.parentIdentifier) info[parentMenuItemIDKey] = '
              'toMenuIdentifierWebAPI(menuItemParameters.parentIdentifier.value());'),
         Cite(MENUS_COCOA,
              'if (isCheckedType(menuItemParameters.type.value())) { info[checkedKey] = '
              '@(menuItemParameters.checked.value_or(false)); info[wasCheckedKey] = @(wasChecked); }'),
         Cite(MENUS_COCOA,
              'if (!contextParameters.selectionString.isNull()) info[selectionTextKey] = '
              'contextParameters.selectionString.createNSString().get();'),
         Cite(MENUS_COCOA,
              'if (contextParameters.types.contains(WebExtensionMenuItemContextType::Audio)) '
              'info[mediaTypeKey] = audioKey;'),
         Cite(MENUS_COCOA,
              'if (!contextParameters.linkText.isNull()) info[linkTextKey] = '
              'contextParameters.linkText.createNSString().get();'),
         Cite(MENUS_COCOA,
              'if (contextParameters.frameIdentifier && !contextParameters.frameURL.isNull()) { '
              'info[editableKey] = @(contextParameters.editable); info[frameIDKey] = '
              '@(toWebAPI(contextParameters.frameIdentifier.value()));'))),
    # WebExtensionAPINotificationsCocoa.mm is the whole notifications
    # implementation and consists of the two event accessors. Nothing in it
    # invokes a listener, so neither event has a payload to declare.
    ('WebExtensionAPINotifications', 'onClicked'): Override(
        'export const onClicked: events.Event<(...args: unknown[]) => void>;',
        (DECLARATION, NOTIFICATIONS_NEVER_DISPATCH),
        doc=('@deprecated Safari never fires this event. WebKit creates the '
             'event object but no code path invokes its listeners.',)),
    ('WebExtensionAPINotifications', 'onButtonClicked'): Override(
        'export const onButtonClicked: events.Event<(...args: unknown[]) => void>;',
        (DECLARATION, NOTIFICATIONS_NEVER_DISPATCH),
        doc=('@deprecated Safari never fires this event. WebKit creates the '
             'event object but no code path invokes its listeners.',)),
    ('WebExtensionAPIPermissions', 'onAdded'): Override(
        'export const onAdded: events.Event<(permissions: browser.Permissions) => void>;'),
    ('WebExtensionAPIPermissions', 'onRemoved'): Override(
        'export const onRemoved: events.Event<(permissions: browser.Permissions) => void>;'),
    ('WebExtensionAPIRuntime', 'onMessage'): Override(
        'export const onMessage: events.Event<(message: unknown, '
        'sender: browser.MessageSender, sendResponse: (response?: unknown) => void) '
        '=> boolean | void | Promise<unknown>>;'),
    ('WebExtensionAPIRuntime', 'onMessageExternal'): Override(
        'export const onMessageExternal: events.Event<(message: unknown, '
        'sender: browser.MessageSender, sendResponse: (response?: unknown) => void) '
        '=> boolean | void | Promise<unknown>>;'),
    ('WebExtensionAPIRuntime', 'onConnect'): Override(
        'export const onConnect: events.Event<(port: browser.runtime.Port) => void>;'),
    ('WebExtensionAPIRuntime', 'onConnectExternal'): Override(
        'export const onConnectExternal: events.Event<(port: browser.runtime.Port) '
        '=> void>;'),
    ('WebExtensionAPIRuntime', 'onInstalled'): Override(
        'export const onInstalled: events.Event<(details: { reason: "install" | '
        '"update" | "browser_update"; previousVersion?: string }) => void>;',
        (DECLARATION,
         Cite(RUNTIME_COCOA,
              'if (installReason == WebExtensionContext::InstallReason::ExtensionUpdate) '
              'details = @{ reasonKey: toWebAPI(installReason), previousVersionKey: '
              'previousVersion.createNSString().get() }; else details = @{ reasonKey: '
              'toWebAPI(installReason) };'),
         Cite(RUNTIME_COCOA, 'case WebExtensionContext::InstallReason::BrowserUpdate: return @"browser_update";'))),
    ('WebExtensionAPIRuntime', 'onStartup'): Override(
        'export const onStartup: events.Event<() => void>;'),
    ('WebExtensionAPIStorage', 'onChanged'): Override(
        'export const onChanged: events.Event<(changes: Record<string, '
        'browser.StorageChange>, areaName: string) => void>;',
        (DECLARATION,
         Cite(STORAGE_COCOA,
              'namespaceObject.storage().onChanged().invokeListenersWithArgument('
              'changes, areaName.get());'))),
    ('WebExtensionAPITabs', 'onCreated'): Override(
        'export const onCreated: events.Event<(tab: browser.Tab) => void>;'),
    # Both the changed set and the whole tab go through the same toWebAPI, so
    # changeInfo is a Tab carrying only the keys that changed. Every Tab member
    # is already optional.
    ('WebExtensionAPITabs', 'onUpdated'): Override(
        'export const onUpdated: events.Event<(tabId: number, '
        'changeInfo: browser.Tab, tab: browser.Tab) => void>;',
        (DECLARATION,
         Cite(TABS_COCOA,
              'namespaceObject.tabs().onUpdated().invokeListenersWithArgument('
              '@(toWebAPI(parameters.identifier.value())), toWebAPI(changedParameters), '
              'toWebAPI(parameters));'),
         Cite(TABS_COCOA, 'NSDictionary *toWebAPI(const WebExtensionTabParameters& parameters)'))),
    ('WebExtensionAPITabs', 'onMoved'): Override(
        'export const onMoved: events.Event<(tabId: number, moveInfo: '
        '{ windowId: number; fromIndex: number; toIndex: number }) => void>;'),
    ('WebExtensionAPITabs', 'onActivated'): Override(
        'export const onActivated: events.Event<(activeInfo: { previousTabId: number; '
        'tabId: number; windowId: number }) => void>;',
        (DECLARATION,
         Cite(TABS_COCOA,
              'auto *activateInfo = @{ previousTabIdKey: @(toWebAPI('
              'previousActiveTabIdentifier)), tabIdKey: @(toWebAPI('
              'newActiveTabIdentifier)), windowIdKey: @(toWebAPI(windowIdentifier)) };'),
         Cite(API_KEYS, 'static NSString * const previousTabIdKey = @"previousTabId";'))),
    ('WebExtensionAPITabs', 'onHighlighted'): Override(
        'export const onHighlighted: events.Event<(highlightInfo: { windowId: number; '
        'tabIds: number[] }) => void>;'),
    ('WebExtensionAPITabs', 'onDetached'): Override(
        'export const onDetached: events.Event<(tabId: number, detachInfo: '
        '{ oldWindowId: number; oldPosition: number }) => void>;'),
    ('WebExtensionAPITabs', 'onAttached'): Override(
        'export const onAttached: events.Event<(tabId: number, attachInfo: '
        '{ newWindowId: number; newPosition: number }) => void>;'),
    ('WebExtensionAPITabs', 'onRemoved'): Override(
        'export const onRemoved: events.Event<(tabId: number, removeInfo: '
        '{ windowId: number; isWindowClosing: boolean }) => void>;'),
    ('WebExtensionAPITabs', 'onReplaced'): Override(
        'export const onReplaced: events.Event<(addedTabId: number, '
        'removedTabId: number) => void>;'),
    ('WebExtensionAPITest', 'onMessage'): Override(
        'export const onMessage: events.Event<(message: string, argument?: unknown) '
        '=> void>;'),
    ('WebExtensionAPITest', 'onTestStarted'): Override(
        'export const onTestStarted: events.Event<(testName: string) => void>;'),
    ('WebExtensionAPITest', 'onTestFinished'): Override(
        'export const onTestFinished: events.Event<(result: boolean, '
        'message?: string) => void>;'),
    ('WebExtensionAPIWindows', 'onCreated'): Override(
        'export const onCreated: events.Event<(window: browser.Window) => void>;'),
    ('WebExtensionAPIWindows', 'onRemoved'): Override(
        'export const onRemoved: events.Event<(windowId: number) => void>;'),
    ('WebExtensionAPIWindows', 'onFocusChanged'): Override(
        'export const onFocusChanged: events.Event<(windowId: number) => void>;'),

    ('WebExtensionAPIWebNavigation', 'onBeforeNavigate'): Override(
        f'export const onBeforeNavigate: {WEB_NAVIGATION_PAYLOAD};',
        WEB_NAVIGATION_DETAILS),
    ('WebExtensionAPIWebNavigation', 'onCommitted'): Override(
        f'export const onCommitted: {WEB_NAVIGATION_PAYLOAD};',
        WEB_NAVIGATION_DETAILS),
    ('WebExtensionAPIWebNavigation', 'onDOMContentLoaded'): Override(
        f'export const onDOMContentLoaded: {WEB_NAVIGATION_PAYLOAD};',
        WEB_NAVIGATION_DETAILS),
    ('WebExtensionAPIWebNavigation', 'onCompleted'): Override(
        f'export const onCompleted: {WEB_NAVIGATION_PAYLOAD};',
        WEB_NAVIGATION_DETAILS),
    ('WebExtensionAPIWebNavigation', 'onErrorOccurred'): Override(
        f'export const onErrorOccurred: {WEB_NAVIGATION_PAYLOAD};',
        WEB_NAVIGATION_DETAILS),

    # -- root namespace properties ------------------------------------------
    ('WebExtensionAPIRuntime', 'lastError'): Override(
        'export const lastError: Error | undefined;',
        (DECLARATION,
         Cite(RUNTIME_COCOA,
              'auto *result = [JSValue valueWithNewErrorFromMessage:errorMessage'
              '.createNSString().get() inContext:context];'),
         Cite(RUNTIME_COCOA, 'm_lastError = result;'))),
    ('WebExtensionAPIScripting', 'ExecutionWorld'): Override(
        'export const ExecutionWorld: { readonly ISOLATED: "ISOLATED"; '
        'readonly MAIN: "MAIN" };',
        (DECLARATION,
         Cite(SCRIPTING_COCOA,
              'static NSDictionary *worlds = @{ @"ISOLATED": @"ISOLATED", @"MAIN": @"MAIN", };'))),

    # -- root namespace operations ------------------------------------------
    ('WebExtensionAPIRuntime', 'getManifest'): Override(
        'export function getManifest(): Record<string, unknown>;'),
    ('WebExtensionAPIMenus', 'create'): Override(
        'export function create(createProperties: browser.MenuItemProperties, '
        'callback?: () => void): number | string;'),
    ('WebExtensionAPIExtension', 'getBackgroundPage'): Override(
        'export function getBackgroundPage(): globalThis.Window | null;'),
    ('WebExtensionAPIExtension', 'getViews'): Override(
        'export function getViews(fetchProperties?: browser.ViewFilter): '
        'globalThis.Window[];'),
    ('WebExtensionAPIRuntime', 'sendMessage'): Override((
        'export function sendMessage<T = unknown, R = unknown>(extensionID: string, '
        'message: T, options: browser.MessageOptions, callback: (result: R) => void): void;',
        'export function sendMessage<T = unknown, R = unknown>(extensionID: string, '
        'message: T, callback: (result: R) => void): void;',
        'export function sendMessage<T = unknown, R = unknown>(extensionID: string, '
        'message: T, options?: browser.MessageOptions): Promise<R>;',
        'export function sendMessage<T = unknown, R = unknown>(message: T, '
        'options: browser.MessageOptions, callback: (result: R) => void): void;',
        'export function sendMessage<T = unknown, R = unknown>(message: T, '
        'callback: (result: R) => void): void;',
        'export function sendMessage<T = unknown, R = unknown>(message: T, '
        'options?: browser.MessageOptions): Promise<R>;',
    )),
    ('WebExtensionAPITabs', 'sendMessage'): Override((
        'export function sendMessage<T = unknown, R = unknown>(tabID: number, '
        'message: T, options: browser.MessageOptions, callback: (result: R) => void): void;',
        'export function sendMessage<T = unknown, R = unknown>(tabID: number, '
        'message: T, callback: (result: R) => void): void;',
        'export function sendMessage<T = unknown, R = unknown>(tabID: number, '
        'message: T, options?: browser.MessageOptions): Promise<R>;',
    )),
    ('WebExtensionAPIRuntime', 'sendNativeMessage'): Override((
        'export function sendNativeMessage<T = unknown, R = unknown>('
        'applicationID: string, message: T, callback: (result: R) => void): void;',
        'export function sendNativeMessage<T = unknown, R = unknown>('
        'applicationID: string, message: T): Promise<R>;',
    )),
    ('WebExtensionAPIRuntime', 'connect'): Override((
        'export function connect(connectInfo?: browser.ConnectOptions): '
        'browser.runtime.Port;',
        'export function connect(extensionId: string, '
        'connectInfo?: browser.ConnectOptions): browser.runtime.Port;',
    )),
    ('WebExtensionAPIScripting', 'executeScript'): Override((
        'export function executeScript(details: browser.ScriptInjection, '
        'callback: (result: browser.InjectionResult[]) => void): void;',
        'export function executeScript(details: browser.ScriptInjection): '
        'Promise<browser.InjectionResult[]>;',
    )),

    # -- test namespace -----------------------------------------------------
    # The IDL types these as `any function` / `any`, which the general path
    # would resolve to a callback parameter. They are ordinary arguments.
    ('WebExtensionAPITest', 'assertEq'): Override(
        'export function assertEq<T>(actualValue: T, expectedValue: T, '
        'message?: string): void;'),
    ('WebExtensionAPITest', 'assertDeepEq'): Override(
        'export function assertDeepEq<T>(actualValue: T, expectedValue: T, '
        'message?: string): void;'),
    ('WebExtensionAPITest', 'assertRejects'): Override(
        'export function assertRejects<T>(promise: Promise<T>, '
        'expectedError?: unknown, message?: string): Promise<T>;'),
    ('WebExtensionAPITest', 'assertResolves'): Override(
        'export function assertResolves<T>(promise: Promise<T>, '
        'expectedError?: unknown, message?: string): Promise<T>;'),
    ('WebExtensionAPITest', 'assertThrows'): Override(
        'export function assertThrows(func: (...args: unknown[]) => unknown, '
        'expectedError?: unknown, message?: string): void;'),
    ('WebExtensionAPITest', 'assertSafe'): Override(
        'export function assertSafe<T>(func: (...args: unknown[]) => T, '
        'message?: string): T;'),
    ('WebExtensionAPITest', 'assertSafeResolve'): Override(
        'export function assertSafeResolve<T>(func: (...args: unknown[]) => T, '
        'message?: string): T;'),
    ('WebExtensionAPITest', 'log'): Override(
        'export function log(message: unknown): void;'),
    ('WebExtensionAPITest', 'sendMessage'): Override(
        'export function sendMessage(message: string, argument?: unknown): void;'),
    ('WebExtensionAPITest', 'runWithUserGesture'): Override(
        'export function runWithUserGesture<T>(func: () => T): T;'),
    ('WebExtensionAPITest', 'addTest'): Override(
        'export function addTest(func: () => void | Promise<void>): void;'),
    ('WebExtensionAPITest', 'runTests'): Override(
        'export function runTests(tests: (() => void | Promise<void>)[]): void;'),
}


# Parsed members that deliberately produce no declaration. Every entry states
# why, and an entry that matches no parsed member fails the build in the same
# way an unused override does.
MEMBER_SKIPS = {
    ('WebExtensionAPIWebRequestEvent', 'removeListener'):
        'inherited from events.Event, which WebRequestEvent extends',
    ('WebExtensionAPIWebRequestEvent', 'hasListener'):
        'inherited from events.Event, which WebRequestEvent extends',
}


# Parsed interfaces that produce no declaration of their own. Members of a
# skipped interface are not reconciled, so a reason here is a broader claim
# than a member skip and is worded accordingly.
INTERFACE_SKIPS = {
    'WebExtensionAPINamespace':
        'the global browser object; its members are the root namespaces, each '
        'declared from its own interface',
    'WebExtensionAPIWebPageNamespace':
        'the browser object exposed to web pages, not to extension contexts',
    'WebExtensionAPIWebPageRuntime':
        'the runtime object exposed to web pages, not to extension contexts',
    'WebExtensionAPIWebNavigationEvent':
        'declared as events.Event; its addListener filter parameter is not '
        'represented, so webNavigation events under-declare that argument',
    'WebExtensionAPIWindowsEvent':
        'declared as events.Event; its addListener filter parameter is not '
        'represented, so windows events under-declare that argument',
    'WebExtensionAPIDevToolsExtensionPanel':
        'the panel object devtools.panels.create yields; the callback parameter '
        'is declared as Record<string, unknown> rather than this interface',
}


# ---------------------------------------------------------------------------
# Package-local entity types
#
# These are not IDL interfaces. Each member is a claim about what WebKit's
# implementation puts in a dictionary, so each carries its own citation and no
# member may be declared without one.
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class EntityMember:
    sig: str
    cites: tuple

    def __init__(self, sig, cites):
        object.__setattr__(self, 'sig', sig)
        object.__setattr__(self, 'cites', tuple(cites))
        if not self.cites:
            raise ValueError(f'entity member {sig!r} carries no citation')


@dataclasses.dataclass(frozen=True)
class EntityType:
    name: str
    decl: str
    members: tuple


COOKIE_STORE_CONSTRUCTION = Cite(
    COOKIES_COCOA,
    '[result addObject:@{ idKey: toWebAPI(entry.key), tabIdsKey: tabIdentifiers, '
    'incognitoKey: @(incognito) }];')

REGISTERED_SCRIPT_TO_WEB_API = Cite(
    SCRIPTING_COCOA,
    'NSDictionary *toWebAPI(const WebExtensionRegisteredScriptParameters& parameters)')

ENTITY_TYPES = (
    EntityType('CookieStore', 'export interface CookieStore', (
        EntityMember('id: string;', (
            COOKIE_STORE_CONSTRUCTION,
            Cite(API_KEYS, 'static NSString * const idKey = @"id";'))),
        EntityMember('tabIds: number[];', (
            COOKIE_STORE_CONSTRUCTION,
            Cite(API_KEYS, 'static NSString * const tabIdsKey = @"tabIds";'))),
        EntityMember('incognito: boolean;', (
            COOKIE_STORE_CONSTRUCTION,
            Cite(API_KEYS, 'static NSString * const incognitoKey = @"incognito";'))),
    )),
    EntityType('PlatformInfo', 'export interface PlatformInfo', (
        EntityMember('os: "mac" | "ios" | "unknown";', (
            Cite(RUNTIME_COCOA,
                 '{ "os"_s, Protected(globalContext, JSValueMakeString(globalContext, '
                 'toJSString(osValue).get())) },'),
            Cite(RUNTIME_COCOA,
                 '#if PLATFORM(MAC) static constexpr auto osValue = "mac"_s; '
                 '#elif PLATFORM(IOS_FAMILY) static constexpr auto osValue = "ios"_s; '
                 '#else static constexpr auto osValue = "unknown"_s; #endif'))),
        EntityMember('arch: "arm" | "x86-64" | "unknown";', (
            Cite(RUNTIME_COCOA,
                 '{ "arch"_s, Protected(globalContext, JSValueMakeString(globalContext, '
                 'toJSString(archValue).get())) }'),
            Cite(RUNTIME_COCOA,
                 '#if CPU(X86_64) static constexpr auto archValue = "x86-64"_s; '
                 '#elif CPU(ARM) || CPU(ARM64) static constexpr auto archValue = "arm"_s; '
                 '#else static constexpr auto archValue = "unknown"_s; #endif'))),
    )),
    EntityType('InjectionResult', 'export interface InjectionResult<T = unknown>', (
        EntityMember('documentId?: string;', (
            Cite(SCRIPTING_COCOA,
                 'result[@"documentId"] = parameters.documentIdentifier.value()'
                 '.toString().createNSString().get();'),)),
        EntityMember('frameId?: number;', (
            Cite(SCRIPTING_COCOA,
                 'result[@"frameId"] = @(WebKit::toWebAPI(parameters.frameIdentifier'
                 '.value()));'),)),
        # Always set, to null when the script produced no value.
        EntityMember('result: T | null;', (
            Cite(SCRIPTING_COCOA, 'result[@"result"] = value ?: NSNull.null;'),)),
        EntityMember('error?: string;', (
            Cite(SCRIPTING_COCOA,
                 'result[@"error"] = parameters.error.value().createNSString().get();'),)),
    )),
    EntityType('RegisteredContentScript', 'export interface RegisteredContentScript', (
        EntityMember('id: string;', (
            Cite(SCRIPTING_COCOA,
                 'result[@"id"] = parameters.identifier.createNSString().get();'),)),
        EntityMember('matches: string[];', (
            Cite(SCRIPTING_COCOA,
                 'result[matchesKey] = createNSArray(parameters.matchPatterns.value()).get();'),
            Cite(API_KEYS, 'static NSString * const matchesKey = @"matches";'))),
        EntityMember('persistAcrossSessions?: boolean;', (
            Cite(SCRIPTING_COCOA,
                 'result[persistAcrossSessionsKey] = parameters.persistent.value() '
                 '? @YES : @NO;'),
            Cite(API_KEYS,
                 'static NSString * const persistAcrossSessionsKey = @"persistAcrossSessions";'))),
        EntityMember('css?: string[];', (
            Cite(SCRIPTING_COCOA,
                 'if (parameters.css) result[cssKey] = createNSArray(parameters.css.value()).get();'),
            Cite(API_KEYS, 'static NSString * const cssKey = @"css";'))),
        EntityMember('js?: string[];', (
            Cite(SCRIPTING_COCOA,
                 'if (parameters.js) result[jsKey] = createNSArray(parameters.js.value()).get();'),
            Cite(API_KEYS, 'static NSString * const jsKey = @"js";'))),
        EntityMember('excludeMatches?: string[];', (
            Cite(SCRIPTING_COCOA,
                 'if (parameters.excludeMatchPatterns) result[excludeMatchesKey] = '
                 'createNSArray(parameters.excludeMatchPatterns.value()).get();'),
            Cite(API_KEYS, 'static NSString * const excludeMatchesKey = @"excludeMatches";'))),
        EntityMember('allFrames?: boolean;', (
            Cite(SCRIPTING_COCOA,
                 'if (parameters.allFrames) result[allFramesKey] = '
                 'parameters.allFrames.value() ? @YES : @NO;'),
            Cite(API_KEYS, 'static NSString * const allFramesKey = @"allFrames";'))),
        EntityMember('matchOriginAsFallback?: boolean;', (
            Cite(SCRIPTING_COCOA,
                 'if (parameters.matchParentFrame) result[matchOriginAsFallbackKey] ='),
            Cite(API_KEYS,
                 'static NSString * const matchOriginAsFallbackKey = @"matchOriginAsFallback";'))),
        EntityMember('runAt?: "document_start" | "document_end" | "document_idle";', (
            Cite(SCRIPTING_COCOA,
                 'if (parameters.injectionTime) result[runAtKey] = '
                 'toWebAPI(parameters.injectionTime.value()).createNSString().get();'),
            Cite(API_KEYS, 'static NSString * const documentEnd = @"document_end";'),
            Cite(API_KEYS, 'static NSString * const documentIdle = @"document_idle";'),
            Cite(API_KEYS, 'static NSString * const documentStart = @"document_start";'))),
        EntityMember('cssOrigin?: "author" | "user";', (
            Cite(SCRIPTING_COCOA,
                 'if (parameters.styleLevel) result[cssOriginKey] = parameters.styleLevel'
                 '.value() == WebCore::UserStyleLevel::User ? userValue : authorValue;'),
            Cite(API_KEYS, 'static NSString * const userValue = @"user";'),
            Cite(API_KEYS, 'static NSString * const authorValue = @"author";'))),
        # Reads return the lowercase constants mainWorld/isolatedWorld. Writes
        # are lowercased before comparison, so the uppercase spellings that
        # scripting.ExecutionWorld yields are accepted on the way in.
        EntityMember('world?: "main" | "isolated" | "MAIN" | "ISOLATED";', (
            Cite(SCRIPTING_COCOA,
                 'if (parameters.world) result[worldKey] = parameters.world.value() == '
                 'WebExtensionContentWorldType::Main ? mainWorld : isolatedWorld;'),
            Cite(API_KEYS, 'static NSString * const mainWorld = @"main";'),
            Cite(API_KEYS, 'static NSString * const isolatedWorld = @"isolated";'),
            Cite(SCRIPTING_COCOA,
                 'if (NSString *world = objectForKey<NSString>(script, worldKey)'
                 '.lowercaseString) {'))),
    )),
)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def blank_out(match):
    """Replaces a comment with spaces so later spans keep their file offsets."""
    return re.sub(r'\S', ' ', match.group(0))


def clean_type(raw_type):
    raw_type = re.sub(r'\[[^\]]*\]', '', raw_type).strip()
    raw_type = raw_type.replace('required', '').strip()
    raw_type = re.sub(r'\bunsigned\s+long\b', 'number', raw_type)
    raw_type = re.sub(r'\bunsigned\s+short\b', 'number', raw_type)
    raw_type = re.sub(r'\blong\b', 'number', raw_type)
    raw_type = re.sub(r'\bshort\b', 'number', raw_type)
    if raw_type.startswith('sequence<') and raw_type.endswith('>'):
        inner = raw_type[9:-1].strip()
        return f"{clean_type(inner)}[]"
    if raw_type.startswith('Promise<') and raw_type.endswith('>'):
        inner = raw_type[8:-1].strip()
        return f"Promise<{clean_type(inner)}>"
    if raw_type in TYPE_MAP:
        return TYPE_MAP[raw_type]
    if raw_type.startswith('WebExtensionAPI'):
        sub = raw_type[15:]
        return f"browser.{sub}" if sub else 'unknown'
    if raw_type.startswith('WebExtension'):
        return f"browser.{raw_type[12:]}"
    return raw_type


def split_args(args_str):
    """Splits argument strings respecting brackets, angle brackets, and parentheses."""
    args = []
    curr = []
    depth_bracket = 0
    depth_angle = 0
    depth_paren = 0
    for char in args_str:
        if char == '[':
            depth_bracket += 1
        elif char == ']':
            depth_bracket -= 1
        elif char == '<':
            depth_angle += 1
        elif char == '>':
            depth_angle -= 1
        elif char == '(':
            depth_paren += 1
        elif char == ')':
            depth_paren -= 1
        elif char == ',' and depth_bracket == 0 and depth_angle == 0 and depth_paren == 0:
            args.append(''.join(curr).strip())
            curr = []
            continue
        curr.append(char)
    if curr:
        args.append(''.join(curr).strip())
    return [a for a in args if a]


def split_statements(body, offset):
    """Yields (statement, absolute start offset) for each `;`-terminated chunk."""
    start = 0
    for i, char in enumerate(body):
        if char == ';':
            yield body[start:i], offset + start
            start = i + 1
    tail = body[start:]
    if tail.strip():
        yield tail, offset + start


def parse_idl_file(filepath, repo_path=None):
    original = filepath.read_text(errors='ignore')
    content = re.sub(r'/\*.*?\*/', blank_out, original, flags=re.DOTALL)
    content = re.sub(r'//[^\n]*', blank_out, content)

    repo_path = repo_path or f'{INTERFACES_DIR}/{filepath.name}'
    line_starts = [0]
    for i, ch in enumerate(original):
        if ch == '\n':
            line_starts.append(i + 1)

    def source_span(start, end):
        text = original[start:end].strip()
        lineno = 1
        for n, s in enumerate(line_starts):
            if s > start:
                break
            lineno = n + 1
        return {'path': repo_path, 'quote': text, 'line': lineno}

    enums = {}
    for m in re.finditer(r'enum\s+(\w+)\s*\{([^}]+)\};', content):
        name = m.group(1)
        raw_vals = m.group(2)
        vals = [re.sub(r'[\"\'\s]', '', v) for v in raw_vals.split(',') if v.strip()]
        enums[name] = [v for v in vals if v]

    dictionaries = {}
    for m in re.finditer(r'dictionary\s+(\w+)(?:\s*:\s*(\w+))?\s*\{([^}]+)\};', content):
        dict_name, parent_name, members_raw = m.group(1), m.group(2), m.group(3)
        members = {}
        for line, _ in split_statements(members_raw, m.start(3)):
            line = line.strip()
            if not line:
                continue
            is_required = bool(re.search(r'\brequired\b', line))
            clean_line = re.sub(r'\[[^\]]*\]', '', line)
            clean_line = re.sub(r'\brequired\b', '', clean_line).strip()
            clean_line = re.sub(r'=.*$', '', clean_line).strip()
            parts = clean_line.split()
            if len(parts) >= 2:
                m_name = parts[-1]
                m_name = RESERVED_WORDS.get(m_name, m_name)
                members[m_name] = {
                    'type': ' '.join(parts[:-1]),
                    'required': is_required,
                }
        dictionaries[dict_name] = {'parent': parent_name, 'members': members}

    interfaces = {}
    for m in re.finditer(
        r'(?:\[(.*?)\]\s*)?interface\s+(\w+)(?:\s*:\s*(\w+))?\s*\{([^}]+)\};',
        content,
        flags=re.DOTALL,
    ):
        attrs_raw, iface_name, parent_name, body_raw = (
            m.group(1) or '', m.group(2), m.group(3), m.group(4)
        )
        attributes = []
        operations = []
        constants = []
        for line, start in split_statements(body_raw, m.start(4)):
            stripped = line.strip()
            if not stripped:
                continue
            declaration = source_span(start, start + len(line))
            if stripped.startswith('const '):
                m_const = re.search(r'const\s+([\w\s<>]+)\s+(\w+)\s*=\s*(.*)', stripped)
                if m_const:
                    constants.append({
                        'type': clean_type(m_const.group(1).strip()),
                        'name': m_const.group(2).strip(),
                        'value': m_const.group(3).strip(),
                        'declaration': declaration,
                    })
            elif 'attribute' in stripped:
                m_attr = re.search(
                    r'(?:\[(.*?)\]\s*)?(?:readonly\s+)?attribute\s+(.+?)\s+(\w+)\s*$',
                    stripped,
                )
                if m_attr:
                    a_name = m_attr.group(3)
                    a_name = RESERVED_WORDS.get(a_name, a_name)
                    attributes.append({
                        'attrs': m_attr.group(1) or '',
                        'type': clean_type(m_attr.group(2).strip()),
                        'name': a_name,
                        'declaration': declaration,
                    })
            elif '(' in stripped and ')' in stripped:
                # Use [\w\s<>]+ to match multi-word WebIDL return types (e.g. unsigned long)
                m_op = re.search(
                    r'(?:\[(.*?)\]\s*)?([\w\s<>]+?)\s+(\w+)\s*\((.*?)\)',
                    stripped,
                    flags=re.DOTALL,
                )
                if m_op:
                    op_attrs = m_op.group(1) or ''
                    op_ret = m_op.group(2).strip()
                    op_name = m_op.group(3).strip()
                    raw_args = m_op.group(4).strip()
                    args = []
                    for a_str in split_args(raw_args):
                        is_opt = 'optional' in a_str or 'Optional' in a_str
                        is_cb = (
                            '[ReturnValue, Callback]' in a_str
                            or '[Callback]' in a_str
                            or '[Optional, CallbackHandler]' in a_str
                            or '[CallbackHandler]' in a_str
                            or 'callback' in a_str.lower()
                        )
                        a_clean = re.sub(r'\[[^\]]*\]', '', a_str)
                        a_clean = a_clean.replace('optional', '').replace('Optional', '').strip()
                        parts = a_clean.split()
                        if len(parts) >= 2:
                            arg_name = parts[-1]
                            arg_name = RESERVED_WORDS.get(arg_name, arg_name)
                            args.append({
                                'name': arg_name,
                                'type': ' '.join(parts[:-1]),
                                'optional': is_opt,
                                'callback': is_cb,
                            })
                    operations.append({
                        'attrs': op_attrs,
                        'returnType': op_ret,
                        'name': op_name,
                        'args': args,
                        'declaration': declaration,
                    })
        interfaces[iface_name] = {
            'attrs': attrs_raw,
            'parent': parent_name,
            'attributes': attributes,
            'operations': operations,
            'constants': constants,
            'path': repo_path,
        }

    return enums, dictionaries, interfaces


# ---------------------------------------------------------------------------
# Algorithmic resolution
# ---------------------------------------------------------------------------


def resolve_algorithmic_param_type(ns_name, op_name, arg_name, raw_type, available_dicts):
    """
    Algorithmic parameter type resolver that dynamically matches method parameters
    to WebIDL dictionaries based on naming conventions and WebIDL AST structure.
    """
    # 1. Structural multi-target identifiers
    if arg_name in ('tabIDs', 'idOrIdList'):
        return 'number | number[]' if 'tab' in arg_name.lower() else 'string | string[]'
    if ns_name == 'menus' and arg_name in ('identifier', 'id'):
        return 'number | string'
    if arg_name == 'target' and ns_name == 'runtime':
        return 'browser.MessageSender | globalThis.Window'
    if arg_name == 'substitutions' and ns_name == 'i18n':
        return 'string | string[]'

    # Capitalized names for composition
    ns_cap = ns_name[0].upper() + ns_name[1:]
    op_cap = op_name[0].upper() + op_name[1:]
    arg_cap = arg_name[0].upper() + arg_name[1:]

    # Candidate dictionary names to search in available WebIDL dictionaries
    candidates = [
        # Exact method + arg combos (e.g. TabCreateProperties, CookieSetDetails, WindowCreateData)
        f"{ns_cap}{op_cap}{arg_cap}",
        f"{ns_cap}{op_cap}Details",
        f"{ns_cap}{op_cap}Properties",
        f"{ns_cap}{op_cap}Options",
        f"{ns_cap}{op_cap}Parameters",
        f"{ns_cap}{op_cap}Data",
        f"{ns_cap}{op_cap}Info",
        f"{ns_cap}{op_cap}",
        # Namespace + arg combos (e.g. CookieDetails, SidebarActionDetails, ViewFilter)
        f"{ns_cap}{arg_cap}",
        f"{ns_cap}Details",
        f"{ns_cap}Properties",
        f"{ns_cap}Options",
        # Generic standalone matches (e.g. Permissions, DNRRule, ConnectInfo)
        arg_cap,
        f"{arg_cap}Info",
        f"{arg_cap}Options",
        f"{arg_cap}Parameters",
    ]

    # Special namespace alias mappings
    if ns_name == 'extension' and arg_name == 'fetchProperties':
        candidates.insert(0, 'ViewFilter')
    if ns_name == 'offscreen' and arg_name in ('parameters', 'options'):
        candidates.insert(0, 'OffscreenCreateParameters')
    if ns_name == 'declarativeNetRequest' and 'ruleset' in arg_name.lower():
        candidates.insert(0, 'DNRUpdateRuleOptions')
    if ns_name == 'declarativeNetRequest' and 'matched' in op_name.lower():
        candidates.insert(0, 'DNRMatchedRulesFilter')
    if ns_name == 'scripting' and 'scripts' in arg_name.lower():
        return 'browser.RegisteredContentScript[]'

    # Check candidates against available dictionaries
    for c in candidates:
        if c in available_dicts or f"WebExtension{c}" in available_dicts:
            return f"browser.{c}"

    cleaned = clean_type(raw_type)
    if cleaned == 'unknown' and arg_name in ('details', 'info', 'options', 'properties'):
        return 'Record<string, unknown>'
    return cleaned


def resolve_algorithmic_return_type(ns_name, op_name, available_dicts):
    """
    Algorithmic return type resolver for asynchronous WebIDL operations based on
    operation semantics and primary entity dictionaries.
    """
    # Special exact methods
    if ns_name == 'menus' and op_name == 'create':
        return 'number | string'
    if ns_name == 'extension' and op_name == 'getViews':
        return 'globalThis.Window[]'
    if ns_name == 'extension' and op_name == 'getBackgroundPage':
        return 'globalThis.Window | null'
    if ns_name == 'runtime' and op_name == 'getBackgroundPage':
        return 'globalThis.Window | null'
    if ns_name == 'runtime' and op_name == 'getPlatformInfo':
        return 'browser.PlatformInfo'
    if ns_name == 'declarativeNetRequest':
        if op_name in ('getDynamicRules', 'getSessionRules'):
            return 'Record<string, unknown>[]'
        if op_name == 'getMatchedRules':
            return '{ rulesMatchedInfo: browser.DNRMatchedRule[] }'
        if op_name == 'getEnabledRulesets':
            return 'string[]'
        if op_name == 'isRegexSupported':
            return '{ isSupported: boolean; reason?: string }'
    if ns_name == 'scripting':
        if op_name == 'executeScript':
            return 'browser.InjectionResult[]'
        if op_name in ('getRegisteredContentScripts', 'registerContentScripts', 'updateContentScripts'):
            return 'browser.RegisteredContentScript[]' if 'get' in op_name else 'void'
    if ns_name == 'cookies' and op_name == 'getAllCookieStores':
        return 'browser.CookieStore[]'
    if ns_name == 'i18n' and op_name in ('getAcceptLanguages', 'getPreferredSystemLanguages'):
        return 'string[]'
    if ns_name == 'i18n' and op_name == 'getSystemUILanguage':
        return 'string'

    # Primary entity for namespace
    primary = NAMESPACE_PRIMARY_ENTITIES.get(ns_name)

    # Special namespace exact returns
    if ns_name == 'permissions' and op_name == 'getAll':
        return 'browser.Permissions'
    if ns_name == 'sidePanel' and op_name == 'getOptions':
        return 'browser.SidePanelOptions'
    if ns_name == 'sidePanel' and op_name == 'getPanel':
        return 'string'
    if ns_name == 'sidePanel' and op_name == 'getPanelBehavior':
        return 'browser.SidePanelBehavior'
    if ns_name == 'webNavigation':
        if op_name == 'getFrame':
            return 'browser.WebNavigationGetFrameDetails | null'
        if op_name == 'getAllFrames':
            return 'browser.WebNavigationGetFrameDetails[] | null'

    # Verb-based rules
    if op_name.startswith('is') or op_name.startswith('has') or op_name in ('clear', 'clearAll', 'contains', 'request', 'remove'):
        if op_name in ('contains', 'request', 'remove') and ns_name == 'permissions':
            return 'boolean'
        if op_name in ('clear', 'clearAll') and ns_name == 'alarms':
            return 'boolean'
        if op_name in ('isAllowedIncognitoAccess', 'isAllowedFileSchemeAccess', 'hasDocument'):
            return 'boolean'
        if op_name == 'isEnabled':
            return 'boolean'
        if op_name == 'isOpen':
            return 'boolean'

    if op_name == 'getAll':
        return f"browser.{primary}[]" if primary else 'unknown[]'

    if op_name in ('get', 'getCurrent', 'getSelected', 'duplicate'):
        if primary:
            nullable = " | null" if ns_name == 'cookies' else (" | undefined" if (ns_name == 'alarms' or (ns_name == 'tabs' and op_name != 'get')) else "")
            return f"browser.{primary}{nullable}"

    if op_name == 'create':
        if primary:
            nullable = " | undefined" if ns_name == 'windows' else ""
            return f"browser.{primary}{nullable}"

    if op_name in ('update', 'move'):
        return f"browser.{primary}" if primary else 'void'

    if op_name in ('getChildren', 'getRecent', 'getTree', 'getSubTree', 'search'):
        return f"browser.{primary}[]" if primary else 'unknown[]'

    if op_name == 'query' and ns_name == 'tabs':
        return 'browser.Tab[]'

    # Scalar getters
    if op_name in ('getTitle', 'getPopup', 'getBadgeText', 'getPanel', 'detectLanguage'):
        return 'string'
    if op_name in ('getZoom',):
        return 'number'
    if op_name == 'getBadgeBackgroundColor':
        return 'number[]'
    if op_name == 'captureVisibleTab':
        return 'string'
    if op_name == 'executeScript' and ns_name == 'tabs':
        return 'unknown[]'

    return 'void'


def format_param_list(ns_name, op_name, args_list, available_dicts):
    """Formats a list of args ensuring no required parameter follows an optional parameter."""
    last_req_idx = -1
    for i, a in enumerate(args_list):
        if not a['optional']:
            last_req_idx = i

    params = []
    for i, a in enumerate(args_list):
        m_type = resolve_algorithmic_param_type(ns_name, op_name, a['name'], a['type'], available_dicts)
        if i <= last_req_idx:
            params.append(f"{a['name']}: {m_type}")
        else:
            params.append(f"{a['name']}?: {m_type}")
    return ', '.join(params)


def emit_cb_overloads(ns_name, op_name, args_list, cb_sig, available_dicts):
    """Emits callback overload declarations generating all valid positional prefixes."""
    lines = []
    cb_param = f"callback: {cb_sig}"

    if not args_list:
        lines.append(f"export function {op_name}({cb_param}): void;")
        return lines

    all_req = [f"{a['name']}: {resolve_algorithmic_param_type(ns_name, op_name, a['name'], a['type'], available_dicts)}" for a in args_list]
    lines.append(f"export function {op_name}({', '.join(all_req)}, {cb_param}): void;")

    for prefix_len in range(len(args_list) - 1, -1, -1):
        dropped = args_list[prefix_len:]
        if all(a['optional'] for a in dropped):
            kept = args_list[:prefix_len]
            kept_req = [f"{a['name']}: {resolve_algorithmic_param_type(ns_name, op_name, a['name'], a['type'], available_dicts)}" for a in kept]
            if kept_req:
                lines.append(f"export function {op_name}({', '.join(kept_req)}, {cb_param}): void;")
            else:
                lines.append(f"export function {op_name}({cb_param}): void;")

    seen = set()
    deduped = []
    for l in lines:
        if l not in seen:
            seen.add(l)
            deduped.append(l)
    return deduped


def derive_attribute_lines(ns_name, attr):
    """Declares a namespace attribute from its parsed IDL type alone."""
    a_name = attr['name']
    a_type = attr['type']

    if 'WebRequestEvent' in a_type:
        return [f'export const {a_name}: events.WebRequestEvent<(details: browser.WebRequestDetails) => void>;'], 'attribute-type:WebRequestEvent'
    if 'Event' in a_type:
        return [f'export const {a_name}: events.Event<(...args: never[]) => void>;'], 'attribute-type:Event'
    # Interface-valued attributes (storage areas, the devtools sub-objects) need
    # no special case: TYPE_MAP already resolves them to the declared type name.
    return [f'export const {a_name}: {a_type};'], 'attribute-type'


def derive_operation_lines(ns_name, op, available_dicts):
    """Declares a namespace operation from its parsed IDL signature alone."""
    op_name = op['name']
    op_ret = clean_type(op['returnType'])
    lines = []

    cb_arg = next((a for a in op['args'] if a['callback'] or 'callback' in a['name'].lower()), None)
    non_cb_args = [a for a in op['args'] if a is not cb_arg]

    # True optional leading check: if first argument is optional, allow omitting it
    has_leading_optional = len(non_cb_args) >= 2 and non_cb_args[0]['optional']

    if cb_arg and op_ret == 'void':
        cb_payload_type = resolve_algorithmic_return_type(ns_name, op_name, available_dicts)

        if cb_payload_type != 'void':
            cb_sig = f'(result: {cb_payload_type}) => void'
            prom_ret = f'Promise<{cb_payload_type}>'
        else:
            cb_sig = '() => void'
            prom_ret = 'Promise<void>'

        if has_leading_optional:
            full_args = [dict(a, optional=False) if i == 0 else a for i, a in enumerate(non_cb_args)]
            lines.extend(emit_cb_overloads(ns_name, op_name, full_args, cb_sig, available_dicts))
            lines.append(f'export function {op_name}({format_param_list(ns_name, op_name, full_args, available_dicts)}): {prom_ret};')

            rest_args = non_cb_args[1:]
            lines.extend(emit_cb_overloads(ns_name, op_name, rest_args, cb_sig, available_dicts))
            lines.append(f'export function {op_name}({format_param_list(ns_name, op_name, rest_args, available_dicts)}): {prom_ret};')
        else:
            lines.extend(emit_cb_overloads(ns_name, op_name, non_cb_args, cb_sig, available_dicts))
            lines.append(f'export function {op_name}({format_param_list(ns_name, op_name, non_cb_args, available_dicts)}): {prom_ret};')
    else:
        if has_leading_optional:
            full_args = [dict(a, optional=False) if i == 0 else a for i, a in enumerate(op['args'])]
            lines.append(f'export function {op_name}({format_param_list(ns_name, op_name, full_args, available_dicts)}): {op_ret};')
            rest_args = op['args'][1:]
            lines.append(f'export function {op_name}({format_param_list(ns_name, op_name, rest_args, available_dicts)}): {op_ret};')
        else:
            lines.append(f'export function {op_name}({format_param_list(ns_name, op_name, op["args"], available_dicts)}): {op_ret};')

    return lines, 'operation-signature'


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


class Reconciler:
    """Records where every declaration came from and what every member did.

    Nothing here decides what to emit. It observes emission so that the two
    error conditions can be checked once generation has finished: a table entry
    that never fired, and a parsed member that never produced output.
    """

    def __init__(self):
        self.used_overrides = set()
        self.used_skips = set()
        self.members = []
        self.declared = {}
        self.accounted = set()

    def declare(self, iface, kind, name):
        """Registers a parsed member that emission is expected to account for."""
        self.declared.setdefault((iface, name), kind)

    def record(self, iface, member, kind, origin, lines, cites=(), declaration=None):
        resolved = []
        for cite in cites:
            if cite is DECLARATION:
                if not declaration:
                    raise CitationError(
                        f'{iface}.{member} cites its own IDL declaration, but the '
                        f'parser recorded no source span for it.'
                    )
                cite = Cite(declaration['path'], declaration['quote'])
            resolved.append(dataclasses.asdict(cite))
        self.accounted.add((iface, member))
        if lines and not resolved:
            raise CitationError(
                f'{iface}.{member} is declared with no citation. Every emitted '
                f'member must point at source that can be re-resolved.'
            )
        self.members.append({
            'interface': iface,
            'member': member,
            'kind': kind,
            'origin': origin,
            'declarations': list(lines),
            'idl': declaration,
            'citations': resolved,
        })

    def check(self):
        errors = []

        unused = sorted(set(SIGNATURE_OVERRIDES) - self.used_overrides)
        for iface, member in unused:
            errors.append(
                f'SIGNATURE_OVERRIDES[{iface!r}, {member!r}] matched no parsed member. '
                f'WebKit does not declare it at this revision, or the interface is skipped.'
            )

        unused_skips = sorted(set(MEMBER_SKIPS) - self.used_skips)
        for iface, member in unused_skips:
            errors.append(
                f'MEMBER_SKIPS[{iface!r}, {member!r}] matched no parsed member. '
                f'The reason it records no longer applies to anything.'
            )

        unaccounted = sorted(
            (iface, member, kind)
            for (iface, member), kind in self.declared.items()
            if (iface, member) not in self.accounted
        )
        for iface, member, kind in unaccounted:
            errors.append(
                f'{iface}.{member} ({kind}) is declared by WebKit but produced no '
                f'output. Add a SIGNATURE_OVERRIDES entry to declare it, or a '
                f'MEMBER_SKIPS entry stating why it is left out.'
            )

        if errors:
            raise ReconciliationError(
                'reconciliation against the parsed IDL failed:\n  '
                + '\n  '.join(errors)
            )


def verify_citations(reconciler, resolver):
    """Re-resolves every citation against the revision being generated from."""
    checked = 0
    for entry in reconciler.members:
        for cite in entry['citations']:
            text = resolver.read(cite['path'])
            normalized, line_of = normalized_with_lines(text)
            needle = norm_ws(cite['quote'])
            index = normalized.find(needle)
            if cite.get('absent'):
                if index >= 0:
                    raise CitationError(
                        f"{entry['interface']}.{entry['member']}: the declaration rests "
                        f"on {cite['quote']!r} being absent from {cite['path']}, but it "
                        f"appears there at {resolver.describe()} on line {line_of[index]}."
                    )
            elif index < 0:
                raise CitationError(
                    f"{entry['interface']}.{entry['member']}: cited text is not present "
                    f"in {cite['path']} at {resolver.describe()}:\n    {cite['quote']}"
                )
            else:
                cite['line'] = line_of[index]
            checked += 1
    return checked


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------


def indent(lines, spaces):
    pad = ' ' * spaces
    return [f'{pad}{line}' for line in lines]


def interface_members(iface_data):
    return (
        [('attribute', a) for a in iface_data['attributes']]
        + [('operation', o) for o in iface_data['operations']]
        + [('constant', c) for c in iface_data['constants']]
    )


def emit_interface_members(out, sub, iface_data, reconciler, spaces):
    """Emits a sub-interface body. Members come from the override table only."""
    for kind, member in interface_members(iface_data):
        if not sub.covers(member['name']):
            continue
        key = (sub.iface, member['name'])
        override = SIGNATURE_OVERRIDES.get(key)
        if override:
            reconciler.used_overrides.add(key)
            out.extend(indent(override.lines(), spaces))
            reconciler.record(sub.iface, member['name'], kind, 'override',
                              override.sig, override.cites, member.get('declaration'))
        elif key in MEMBER_SKIPS:
            reconciler.used_skips.add(key)
            reconciler.record(sub.iface, member['name'], kind, 'skipped', [],
                              declaration=member.get('declaration'))


def emit_namespace_members(out, iface_name, iface_data, ns_name, reconciler, available_dicts):
    for c in iface_data['constants']:
        key = (iface_name, c['name'])
        override = SIGNATURE_OVERRIDES.get(key)
        if override:
            reconciler.used_overrides.add(key)
            lines = list(override.lines())
            origin, cites = 'override', override.cites
        elif key in MEMBER_SKIPS:
            reconciler.used_skips.add(key)
            reconciler.record(iface_name, c['name'], 'constant', 'skipped', [],
                              declaration=c.get('declaration'))
            continue
        else:
            lines = [f'export const {c["name"]}: {c["type"]};']
            origin, cites = 'constant-type', (DECLARATION,)
        out.extend(indent(lines, 8))
        reconciler.record(iface_name, c['name'], 'constant', origin, lines, cites,
                          c.get('declaration'))

    for attr in iface_data['attributes']:
        key = (iface_name, attr['name'])
        override = SIGNATURE_OVERRIDES.get(key)
        if override:
            reconciler.used_overrides.add(key)
            lines = list(override.lines())
            origin, cites = 'override', override.cites
        elif key in MEMBER_SKIPS:
            reconciler.used_skips.add(key)
            reconciler.record(iface_name, attr['name'], 'attribute', 'skipped', [],
                              declaration=attr.get('declaration'))
            continue
        else:
            lines, origin = derive_attribute_lines(ns_name, attr)
            cites = (DECLARATION,)
        out.extend(indent(lines, 8))
        reconciler.record(iface_name, attr['name'], 'attribute', origin, lines, cites,
                          attr.get('declaration'))

    for op in iface_data['operations']:
        key = (iface_name, op['name'])
        override = SIGNATURE_OVERRIDES.get(key)
        if override:
            reconciler.used_overrides.add(key)
            lines = list(override.lines())
            origin, cites = 'override', override.cites
        elif key in MEMBER_SKIPS:
            reconciler.used_skips.add(key)
            reconciler.record(iface_name, op['name'], 'operation', 'skipped', [],
                              declaration=op.get('declaration'))
            continue
        else:
            lines, origin = derive_operation_lines(ns_name, op, available_dicts)
            cites = (DECLARATION,)
        out.extend(indent(lines, 8))
        reconciler.record(iface_name, op['name'], 'operation', origin, lines, cites,
                          op.get('declaration'))


def generate_dts(idl_dir: pathlib.Path, reconciler: 'Reconciler', source: str) -> str:
    all_enums = {}
    all_dicts = {}
    all_ifaces = {}

    for p in sorted(idl_dir.glob('*.idl')):
        e, d, i = parse_idl_file(p)
        all_enums.update(e)
        all_dicts.update(d)
        all_ifaces.update(i)

    declared_sub_interfaces = {
        sub.iface for _, subs in SUB_INTERFACE_GROUPS for sub in subs
    }
    unknown_interfaces = sorted(
        name for name in all_ifaces
        if name not in ROOT_NAMESPACES
        and name not in INTERFACE_SKIPS
        and name not in declared_sub_interfaces
    )
    if unknown_interfaces:
        raise ReconciliationError(
            'WebKit declares interfaces this generator has no disposition for:\n  '
            + '\n  '.join(unknown_interfaces)
            + '\nAdd each to ROOT_NAMESPACES, SUB_INTERFACE_GROUPS, or INTERFACE_SKIPS.'
        )

    for name, data in all_ifaces.items():
        if name in INTERFACE_SKIPS:
            continue
        for kind, member in interface_members(data):
            reconciler.declare(name, kind, member['name'])

    # Index short names of all parsed WebIDL dictionaries
    dict_short_names = set()
    for d in all_dicts:
        dict_short_names.add(d[12:] if d.startswith('WebExtension') else d)
        dict_short_names.add(d)

    lines = []
    lines.append('// Type definitions for Safari WebExtensions')
    lines.append('// Project: https://github.com/patrickkettner/safari-webextension-types')
    lines.append('// Definitions generated directly from WebKit WebIDL declarations')
    lines.append(f'// Source: {source}')
    lines.append('//')
    lines.append('// Generated automatically by safari-webextension-types generator.')
    lines.append('// Do not edit directly.')
    lines.append('')
    lines.append('declare namespace browser {')
    lines.append('')

    def emit_group(group_name, entries):
        if group_name:
            lines.append(f'    export namespace {group_name} {{')
            body_indent, member_indent = 8, 12
        else:
            body_indent, member_indent = 4, 8
        for sub in entries:
            if sub.iface not in all_ifaces:
                raise ReconciliationError(
                    f'{sub.iface} is declared as a sub-interface but no parsed IDL '
                    f'file contains it at this revision.'
                )
            lines.append(f'{" " * body_indent}{sub.decl} {{')
            emit_interface_members(lines, sub, all_ifaces[sub.iface],
                                   reconciler, member_indent)
            lines.append(f'{" " * body_indent}}}')
        if group_name:
            lines.append('    }')
        for sub in entries:
            if sub.alias:
                lines.append(f'    {sub.alias}')
        lines.append('')

    # Events namespace (contravariant zero-any constraint)
    emit_group(*SUB_INTERFACE_GROUPS[0])

    for position, entity in enumerate(ENTITY_TYPES):
        if position:
            lines.append('')
        lines.append(f'    {entity.decl} {{')
        for member in entity.members:
            lines.append(f'        {member.sig}')
            reconciler.record(entity.name, member.sig.split(':')[0].rstrip('?'),
                              'entity-member', 'entity', [member.sig], member.cites)
        lines.append('    }')
        dict_short_names.add(entity.name)

    # Enums from WebIDL
    for enum_name, values in sorted(all_enums.items()):
        short_name = enum_name[12:] if enum_name.startswith('WebExtension') else enum_name
        val_str = ' | '.join(f'"{v}"' for v in values)
        lines.append(f'    export type {short_name} = {val_str};')
    lines.append('')

    # Dictionaries from WebIDL
    for dict_name, dict_data in sorted(all_dicts.items()):
        short_name = dict_name[12:] if dict_name.startswith('WebExtension') else dict_name
        parent = dict_data['parent']
        parent_str = f' extends {clean_type(parent)}' if parent else ''
        lines.append(f'    export interface {short_name}{parent_str} {{')
        for m_name, m_info in sorted(dict_data['members'].items()):
            opt = '' if m_info['required'] else '?'
            m_type = clean_type(m_info['type'])
            lines.append(f'        {m_name}{opt}: {m_type};')
        lines.append('    }')
        lines.append('')

    for group in SUB_INTERFACE_GROUPS[1:]:
        emit_group(*group)

    # Root Namespaces
    for iface_name, iface_data in sorted(all_ifaces.items()):
        if iface_name not in ROOT_NAMESPACES:
            continue

        ns_name = ROOT_NAMESPACES[iface_name]
        lines.append(f'    export namespace {ns_name} {{')
        emit_namespace_members(lines, iface_name, iface_data, ns_name, reconciler,
                               dict_short_names)
        lines.append('    }')
        lines.append('')

    lines.append('}')
    lines.append('')

    # Chrome namespace alias
    lines.append('declare namespace chrome {')
    lines.append('    export import action = browser.action;')
    lines.append('    export import alarms = browser.alarms;')
    lines.append('    export import bookmarks = browser.bookmarks;')
    lines.append('    export import browserAction = browser.action;')
    lines.append('    export import cookies = browser.cookies;')
    lines.append('    export import commands = browser.commands;')
    lines.append('    export import contextMenus = browser.menus;')
    lines.append('    export import declarativeNetRequest = browser.declarativeNetRequest;')
    lines.append('    export import devtools = browser.devtools;')
    lines.append('    export import dom = browser.dom;')
    lines.append('    export import extension = browser.extension;')
    lines.append('    export import i18n = browser.i18n;')
    lines.append('    export import menus = browser.menus;')
    lines.append('    export import notifications = browser.notifications;')
    lines.append('    export import offscreen = browser.offscreen;')
    lines.append('    export import pageAction = browser.action;')
    lines.append('    export import permissions = browser.permissions;')
    lines.append('    export import runtime = browser.runtime;')
    lines.append('    export import scripting = browser.scripting;')
    lines.append('    export import sidebarAction = browser.sidebarAction;')
    lines.append('    export import sidePanel = browser.sidePanel;')
    lines.append('    export import storage = browser.storage;')
    lines.append('    export import tabs = browser.tabs;')
    lines.append('    export import test = browser.test;')
    lines.append('    export import webNavigation = browser.webNavigation;')
    lines.append('    export import webRequest = browser.webRequest;')
    lines.append('    export import windows = browser.windows;')
    lines.append('}')
    lines.append('')

    return '\n'.join(lines)


# Members WebKit exposes only on storage.sync. isPropertyAllowed answers false
# for them on every other area, so they are declared on a separate interface
# rather than on every storage area.
SYNC_ONLY_STORAGE_MEMBERS = (
    'QUOTA_BYTES_PER_ITEM',
    'MAX_ITEMS',
    'MAX_WRITE_OPERATIONS_PER_HOUR',
    'MAX_WRITE_OPERATIONS_PER_MINUTE',
)


@dataclasses.dataclass(frozen=True)
class SubInterface:
    """A parsed IDL interface declared as a TypeScript interface.

    `only` and `excluding` let one IDL interface be split across more than one
    declaration, for members WebKit exposes conditionally. Every parsed member
    still has to land in exactly one of them or reconciliation fails.
    """

    iface: str
    decl: str
    alias: str = None
    only: tuple = ()
    excluding: tuple = ()

    def covers(self, name):
        if self.only:
            return name in self.only
        return name not in self.excluding


# Grouped by the namespace they are nested in, and emitted in this order.
SUB_INTERFACE_GROUPS = [
    ('events', [
        SubInterface(
            'WebExtensionAPIEvent',
            'export interface Event<T extends (...args: never[]) => void>'),
        SubInterface(
            'WebExtensionAPIWebRequestEvent',
            'export interface WebRequestEvent<T extends (...args: never[]) => void> '
            'extends Event<T>'),
    ]),
    ('runtime', [
        SubInterface('WebExtensionAPIPort', 'export interface Port',
                     alias='export type Port = runtime.Port;'),
    ]),
    ('storage', [
        SubInterface('WebExtensionAPIStorageArea', 'export interface StorageArea',
                     alias='export type StorageArea = storage.StorageArea;',
                     excluding=SYNC_ONLY_STORAGE_MEMBERS),
        SubInterface('WebExtensionAPIStorageArea',
                     'export interface SyncStorageArea extends StorageArea',
                     only=SYNC_ONLY_STORAGE_MEMBERS),
    ]),
    ('devtools', [
        SubInterface('WebExtensionAPIDevToolsInspectedWindow',
                     'export interface InspectedWindow'),
        SubInterface('WebExtensionAPIDevToolsNetwork', 'export interface Network'),
        SubInterface('WebExtensionAPIDevToolsPanels', 'export interface Panels'),
    ]),
]


def build_resolver(args):
    remote = RemoteResolver(args.repo, args.ref, cache_dir=args.cache_dir)
    if args.webkit_checkout:
        base = GitCheckoutResolver(args.webkit_checkout, args.ref)
    else:
        base = remote
    if args.idl_dir:
        return IdlDirResolver(args.idl_dir, delegate=base)
    return base


def fetch_upstream_idls(target_dir: pathlib.Path, resolver: SourceResolver):
    """Writes every known IDL file out of the resolver. Fails fast on error."""
    target_dir.mkdir(parents=True, exist_ok=True)
    idl_files = sorted(set(KNOWN_IDL_FILES))

    print(f"Reading {len(idl_files)} WebIDL files from {resolver.describe()}...")
    errors = []
    for name in idl_files:
        try:
            (target_dir / name).write_text(resolver.read(f'{INTERFACES_DIR}/{name}'))
        except Exception as e:
            errors.append(f'{name}: {e}')

    if errors:
        for err in errors:
            print(f"  Error: {err}", file=sys.stderr)
        raise RuntimeError(
            f"Failed to read {len(errors)} WebIDL files from {resolver.describe()}."
        )

    print(f"Successfully read all {len(idl_files)} IDL files.")


def resolve_pr_head(pr_number: int, base_repo: str):
    """Resolves a GitHub PR number to its head repository and ref."""
    api_url = f"https://api.github.com/repos/{base_repo}/pulls/{pr_number}"
    req = urllib.request.Request(
        api_url, headers={"User-Agent": "safari-webextension-types-generator"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        pr_data = json.loads(resp.read().decode("utf-8"))
    head_repo = pr_data.get("head", {}).get("repo", {}).get("full_name")
    head_sha = pr_data.get("head", {}).get("sha")
    if not head_repo or not head_sha:
        raise RuntimeError(f"PR #{pr_number} metadata does not contain head repository/sha.")
    print(f"Resolved WebKit PR #{pr_number} -> {head_repo}@{head_sha}")
    return head_repo, head_sha


def main():
    parser = argparse.ArgumentParser(
        description='Generate TypeScript declarations for Safari WebExtensions directly from WebKit WebIDL interfaces'
    )
    parser.add_argument(
        '--pr',
        type=int,
        default=None,
        help='WebKit GitHub PR number to resolve and fetch IDLs from (e.g. --pr 71593)'
    )
    parser.add_argument(
        '--idl-dir',
        type=pathlib.Path,
        default=None,
        help='Path to local directory containing WebExtensionAPI*.idl files (if specified, skips remote fetch)'
    )
    parser.add_argument(
        '--webkit-checkout',
        type=pathlib.Path,
        default=None,
        help='Path to a local WebKit checkout to read sources and citations from, instead of github.com'
    )
    parser.add_argument(
        '--repo',
        default='WebKit/WebKit',
        help='Specific GitHub repository to fetch IDLs from (default: WebKit/WebKit)'
    )
    parser.add_argument(
        '--ref',
        # A commit, not a branch. Every citation is re-resolved against this
        # revision, so a moving ref would mean the declarations and the evidence
        # for them come from different source, and two builds of the same
        # generator commit could disagree with nothing recording why.
        default='0136fa2b7cf669ab6bc8e715727e6a78bf5f24ba',
        help='Git commit SHA to read WebKit sources and resolve citations at'
    )
    parser.add_argument(
        '--cache-dir',
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent.parent / '.idls-cache',
        help='Directory to cache fetched WebKit sources in'
    )
    parser.add_argument(
        '--provenance',
        type=pathlib.Path,
        default=None,
        help='Write a JSON record of where every declaration came from to this path'
    )
    parser.add_argument(
        '--output', '-o',
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent.parent / 'index.d.ts',
        help='Output path for emitted .d.ts file (default: index.d.ts)'
    )

    args = parser.parse_args()

    if args.pr:
        args.repo, args.ref = resolve_pr_head(args.pr, args.repo)

    resolver = build_resolver(args)
    reconciler = Reconciler()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        fetch_upstream_idls(tmp_path, resolver)
        dts_content = generate_dts(tmp_path, reconciler, f'{args.repo}@{args.ref}')

    reconciler.check()
    checked = verify_citations(reconciler, resolver)
    print(f"Re-resolved {checked} citation(s) against {resolver.describe()}.")

    # Enforce strict zero-any policy on generated declarations
    any_lines = [(i + 1, l.strip()) for i, l in enumerate(dts_content.splitlines()) if 'any' in l]
    if any_lines:
        print(f"ERROR: Zero-any policy violation! Found {len(any_lines)} lines with 'any' in generated output:", file=sys.stderr)
        for num, line in any_lines:
            print(f"  L{num}: {line}", file=sys.stderr)
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dts_content)
    line_count = len(dts_content.splitlines())
    print(f"Successfully generated {line_count} lines of TypeScript declarations (0 'any') -> {args.output}")

    if args.provenance:
        args.provenance.write_text(json.dumps({
            'source': resolver.describe(),
            'repository': args.repo,
            'ref': args.ref,
            'members': reconciler.members,
            'interfaceSkips': INTERFACE_SKIPS,
        }, indent=2, sort_keys=True) + '\n')
        print(f"Wrote provenance for {len(reconciler.members)} member(s) -> {args.provenance}")


if __name__ == '__main__':
    main()
