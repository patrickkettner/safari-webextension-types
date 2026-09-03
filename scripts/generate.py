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

CHROME_NAMESPACE_ALIASES = (
    ('action', 'browser.action'),
    ('alarms', 'browser.alarms'),
    ('bookmarks', 'browser.bookmarks'),
    ('browserAction', 'browser.action'),
    ('cookies', 'browser.cookies'),
    ('commands', 'browser.commands'),
    ('contextMenus', 'browser.menus'),
    ('declarativeNetRequest', 'browser.declarativeNetRequest'),
    ('devtools', 'browser.devtools'),
    ('dom', 'browser.dom'),
    ('extension', 'browser.extension'),
    ('i18n', 'browser.i18n'),
    ('menus', 'browser.menus'),
    ('notifications', 'browser.notifications'),
    ('offscreen', 'browser.offscreen'),
    ('pageAction', 'browser.action'),
    ('permissions', 'browser.permissions'),
    ('runtime', 'browser.runtime'),
    ('scripting', 'browser.scripting'),
    ('sidebarAction', 'browser.sidebarAction'),
    ('sidePanel', 'browser.sidePanel'),
    ('storage', 'browser.storage'),
    ('tabs', 'browser.tabs'),
    ('test', 'browser.test'),
    ('webNavigation', 'browser.webNavigation'),
    ('webRequest', 'browser.webRequest'),
    ('windows', 'browser.windows'),
)

# Namespaces whose WebExtensionAPI<Ns>Cocoa.mm has been read end to end, every
# operation checked against its callback->call. Membership here is the only
# thing that makes a verb-rule type trustworthy, because the verb table has
# been wrong for rule-matched operations, not just fall-throughs: menus.update
# and bookmarks.get both matched a rule and both were wrong.
#
# Add a namespace only after reading it. Everything outside this set is listed
# in unverified-returns.txt, which only shrinks.
READ_NAMESPACES = {
    'action',
    'alarms',
    'commands',
    'bookmarks',
    'cookies',
    'declarativeNetRequest',
    'dom',
    'extension',
    'menus',
    'permissions',
    'offscreen',
    'runtime',
    'scripting',
    'sidePanel',
    'i18n',
    'sidebarAction',
    'tabs',
    'test',
    'webNavigation',
    'windows',
}

# Operations whose implementation was read at the pinned revision and reaches
# callback->call() with no argument. A void here is a reading, unlike the
# resolver's fall-through, which is a guess and is tracked in
# unresolved-payloads.txt. Add to this only after reading the .mm; see
# RETURN-SHAPES-WORKLIST.md for which chunk covered each namespace.

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
    'webNavigation': 'FrameDetails',
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

    def list_idl_files(self):
        """Every .idl in the interfaces directory at this revision."""
        raise NotImplementedError

    def resolve_ref(self):
        """The commit this resolver reads, as a sha.

        Resolved once and reused, so a branch cannot move between the listing,
        the fetch and the citation checks and leave three revisions in one
        build. Returns None where there is nothing to resolve.
        """
        return None

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

    def resolve_ref(self):
        result = subprocess.run(
            ['git', '-C', str(self.root), 'rev-parse', f'{self.ref}^{{commit}}'],
            capture_output=True, text=True)
        if result.returncode != 0:
            raise CitationError(
                f'{self.ref} does not resolve in {self.root}: {result.stderr.strip()}')
        return result.stdout.strip()

    def list_idl_files(self):
        result = subprocess.run(
            ['git', '-C', str(self.root), 'ls-tree', '--name-only',
             self.ref, f'{INTERFACES_DIR}/'],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise CitationError(
                f'could not list {INTERFACES_DIR} at {self.describe()}: '
                f'{result.stderr.strip()}')
        return {pathlib.PurePosixPath(line).name
                for line in result.stdout.split() if line.endswith('.idl')}

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

    def resolve_ref(self):
        url = f'https://api.github.com/repos/{self.repo}/commits/{self.ref}'
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "safari-webextension-types-generator",
                              "Accept": "application/vnd.github.sha"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode('utf-8').strip()
        except Exception as e:
            raise CitationError(f'{self.ref} does not resolve in {self.repo}: {e}')

    def list_idl_files(self):
        url = (f'https://api.github.com/repos/{self.repo}/contents/'
               f'{INTERFACES_DIR}?ref={self.ref}')
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "safari-webextension-types-generator"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                entries = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            raise CitationError(
                f'could not list {INTERFACES_DIR} at {self.describe()}: {e}')
        return {e['name'] for e in entries if e.get('name', '').endswith('.idl')}

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

    def resolve_ref(self):
        return self.delegate.resolve_ref() if self.delegate else None

    def list_idl_files(self):
        # A local directory is whatever the caller put there, so listing it
        # says nothing about the revision. Defer to the delegate, which does,
        # so the file-list gate is a real check even in this mode. With no
        # delegate there is nothing to check against; say so rather than pass.
        if self.delegate is None:
            raise CitationError(
                f'--idl-dir with no --webkit-checkout or remote revision: the '
                f'interface file list cannot be reconciled against anything, so '
                f'this mode cannot claim it is complete.')
        return self.delegate.list_idl_files()

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
WINDOWS_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm'
DNR_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm'
STORAGE_AREA_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIStorageAreaCocoa.mm'
NOTIFICATIONS_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPINotificationsCocoa.mm'
SIDEBAR_ACTION_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm'
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

# Operations that call back with no argument, each citing the line that proves
# it: the IPC reply this operation waits on, resolving Expected<void>. A void
# recorded here is a reading the build re-checks, not an attestation. An entry
# whose quote stops resolving fails the build.
#
# Every quote was extracted from the implementation at the pinned revision and
# verified to occur exactly once in its file, so it identifies this operation
# rather than merely appearing somewhere nearby.
CONFIRMED_EMPTY_CALLBACKS = {
    ('action', 'disable'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::ActionSetEnabled(tabIdentifer, false), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('action', 'enable'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::ActionSetEnabled(tabIdentifer, true), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('action', 'openPopup'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::ActionOpenPopup(webPageProxyIdentifier, windowIdentifier, tabIdentifier), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('action', 'setBadgeBackgroundColor'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
        "// FIXME: <rdar://problem/57666368> Implement getting/setting the extension toolbar item's badge background color. callback->call();"),
    ('action', 'setBadgeText'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::ActionSetBadgeText(windowIdentifier, tabIdentifier, text), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('action', 'setIcon'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::ActionSetIcon(windowIdentifier, tabIdentifier, iconsJSON), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('action', 'setPopup'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::ActionSetPopup(windowIdentifier, tabIdentifier, popup), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('action', 'setTitle'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::ActionSetTitle(windowIdentifier, tabIdentifier, title), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('alarms', 'create'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/WebExtensionAPIAlarms.cpp',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::AlarmsCreate(!alarmName.isEmpty() ? alarmName : emptyAlarmName, initialInterval, repeatInterval), [protectedThis = Ref { *this }, callback = WTF::move(callback)]() {'),
    ('bookmarks', 'remove'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
        'Messages::WebExtensionContext::BookmarksRemove(bookmarkIdentifier), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('bookmarks', 'removeTree'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
        'Messages::WebExtensionContext::BookmarksRemoveTree(bookmarkIdentifier), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('declarativeNetRequest', 'setExtensionActionOptions'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::DeclarativeNetRequestIncrementActionCount(tabIdentifier.value(), objectForKey<NSNumber>(tabUpdateDictionary, actionCountIncrementKey).doubleValue), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('declarativeNetRequest', 'updateDynamicRules'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::DeclarativeNetRequestUpdateDynamicRules(WTF::move(rulesToAddJSON), WTF::move(ruleIDsToRemove)), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('declarativeNetRequest', 'updateEnabledRulesets'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::DeclarativeNetRequestUpdateEnabledRulesets(rulesetsToEnable, rulesetsToDisable), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('declarativeNetRequest', 'updateSessionRules'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::DeclarativeNetRequestUpdateSessionRules(WTF::move(rulesToAddJSON), WTF::move(ruleIDsToRemove)), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('menus', 'remove'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIMenusCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::MenusRemove(identifierString), [this, protectedThis = Ref { *this }, callback = WTF::move(callback), identifier = String(identifierString)](Expected<void, WebExtensionError>&& result) {'),
    ('menus', 'removeAll'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIMenusCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::MenusRemoveAll(), [this, protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('menus', 'update'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIMenusCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::MenusUpdate(identifierString, parameters.value()), [this, protectedThis = Ref { *this }, callback = WTF::move(callback), clickCallback = WTF::move(clickCallback), newIdentifier = parameters.value().identifier, oldIdentifier = String(identifierString)](Expected<void, WebExtensionError>&& result) mutable {'),
    ('offscreen', 'closeDocument'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIOffscreenCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::OffscreenCloseDocument(), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('offscreen', 'createDocument'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIOffscreenCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::OffscreenCreateDocument(parameters), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('runtime', 'openOptionsPage'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::RuntimeOpenOptionsPage(), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('runtime', 'setUninstallURL'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
        '// FIXME: rdar://58000001 Consider implementing runtime.setUninstallURL(), matching the behavior of other browsers. callback->call();'),
    ('scripting', 'insertCSS'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIScriptingCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::ScriptingInsertCSS(WTF::move(parameters)), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('scripting', 'registerContentScripts'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIScriptingCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::ScriptingRegisterContentScripts(WTF::move(parameters)), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('scripting', 'removeCSS'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIScriptingCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::ScriptingRemoveCSS(WTF::move(parameters)), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('scripting', 'unregisterContentScripts'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIScriptingCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::ScriptingUnregisterContentScripts(WTF::move(scriptIDs)), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('scripting', 'updateContentScripts'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIScriptingCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::ScriptingUpdateRegisteredScripts(WTF::move(parameters)), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('sidePanel', 'open'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::SidebarOpen(windowId, tabId), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('sidePanel', 'setOptions'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::SidebarSetOptions(std::nullopt, tabIdentifierResult.value(), panelPath, enabledValue), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('sidePanel', 'setPanelBehavior'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::SidebarSetActionClickBehavior(*maybeClickBehavior), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('sidebarAction', 'close'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::SidebarClose(), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('sidebarAction', 'open'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::SidebarOpen(std::nullopt, std::nullopt), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('sidebarAction', 'setIcon'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
        'static NSString * const apiName = @"sidebarAction.setIcon()";'),
    ('sidebarAction', 'setPanel'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::SidebarSetOptions(windowId, tabId, panelPath, std::nullopt), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('sidebarAction', 'setTitle'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::SidebarSetTitle(windowId, tabId, title), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('sidebarAction', 'toggle'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::SidebarToggle(), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('tabs', 'goBack'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::TabsGoBack(webPageProxyIdentifier, tabIdentifer), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('tabs', 'goForward'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::TabsGoForward(webPageProxyIdentifier, tabIdentifer), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('tabs', 'reload'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::TabsReload(webPageProxyIdentifier, tabIdentifer, reloadFromOrigin), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('tabs', 'remove'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::TabsRemove(WTF::move(identifiers)), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('tabs', 'setZoom'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::TabsSetZoom(webPageProxyIdentifier, tabIdentifer, zoomFactor), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('tabs', 'toggleReaderMode'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::TabsToggleReaderMode(webPageProxyIdentifier, tabIdentifer), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
    ('windows', 'remove'): Cite(
        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::WindowsRemove(windowIdentifer.value()), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),
}

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
              'Messages::WebExtensionContext::RuntimeConnect(extensionID, port->channelIdentifier(), resolvedName, senderParameters, userGesture), [=, this, protectedThis = Ref { *this }, globalContext = JSRetainPtr { JSContextGetGlobalContext(context) }](Expected<void, WebExtensionError>&& result) { if (result) return; port->setError(protect(runtime())->reportError(result.error().createNSString().get(), globalContext.get()));'),
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
        'setAccessLevel(accessOptions: { accessLevel: "TRUSTED_CONTEXTS" | '
        '"TRUSTED_AND_UNTRUSTED_CONTEXTS" }): Promise<void>;',
        'setAccessLevel(accessOptions: { accessLevel: "TRUSTED_CONTEXTS" | '
        '"TRUSTED_AND_UNTRUSTED_CONTEXTS" }, callback: () => void): void;',
    ), (DECLARATION,
        Cite(STORAGE_AREA_COCOA,
             'static auto *requiredKeys = @[ accessLevelKey, ];'),
        Cite(STORAGE_AREA_COCOA,
             '@"it must specify either \'TRUSTED_CONTEXTS\' or '
             '\'TRUSTED_AND_UNTRUSTED_CONTEXTS\'"'))),
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
        doc=('The callback parameter list is left open because WebKit calls it '
             'with one argument, a two-element array of the result and, on '
             'failure, an error object. Prefer the promise. WebKit builds that '
             'error object with the literal keys "isExceptionKey" and '
             '"valueKey", which are the names of its key constants rather than '
             'their values.',)),
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
        doc=('No payload is declared because Safari fires this event with no '
             'arguments. changeInfo is not implemented yet; see '
             'https://webkit.org/b/267514. A listener parameter will be '
             'undefined at runtime.',)),
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
        doc=('No payload is declared because Safari does not fire this event '
             'yet. WebKit creates the event object, and no code path invokes '
             'its listeners.',)),
    ('WebExtensionAPINotifications', 'onButtonClicked'): Override(
        'export const onButtonClicked: events.Event<(...args: unknown[]) => void>;',
        (DECLARATION, NOTIFICATIONS_NEVER_DISPATCH),
        doc=('No payload is declared because Safari does not fire this event '
             'yet. WebKit creates the event object, and no code path invokes '
             'its listeners.',)),
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
# Manifest V3 gates
#
# WebKit's isPropertyAllowed hides some members from every MV3 extension, in
# two shapes: a name gated in its own `if` branch, or several names sharing
# one `removedInManifestVersion3` HashSet. derive_mv3_removed_names parses
# either shape at the generation ref and returns {name: verbatim gate text}.
# ---------------------------------------------------------------------------

# Candidate paths for the namespace gate, newest first.
NAMESPACE_GATE_PATHS = (
    'Source/WebKit/WebProcess/Extensions/API/WebExtensionAPINamespace.cpp',
    'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPINamespaceCocoa.mm',
)
EXTENSION_COCOA = 'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIExtensionCocoa.mm'

_MV3_DIRECT_GATE_RE = re.compile(
    r'if \(name == "(?P<name>\w+)"_s\)\s*\n\s*'
    r'return (?P<gate>![^;\n]*supportsManifestVersion\(3\)[^;\n]*);'
)
_MV3_SET_GATE_RE = re.compile(
    r'static NeverDestroyed<HashSet<AtomString>> removedInManifestVersion3 '
    r'\{ HashSet \{ (?P<names>AtomString\("\w+"_s\)(?:, AtomString\("\w+"_s\))*) \} \};'
    r'\s*\n\s*if \(removedInManifestVersion3\.get\(\)\.contains\(name\)\)\s*\n\s*'
    r'return (?P<gate>![^;\n]*supportsManifestVersion\(3\)[^;\n]*);'
)
_ATOM_STRING_RE = re.compile(r'AtomString\("(\w+)"_s\)')


def derive_mv3_removed_names(text):
    """Takes an isPropertyAllowed body; returns {name: verbatim gate text}."""
    found = {}
    for m in _MV3_DIRECT_GATE_RE.finditer(text):
        found[m.group('name')] = m.group(0)
    for m in _MV3_SET_GATE_RE.finditer(text):
        gate_text = m.group(0)
        for name in _ATOM_STRING_RE.findall(m.group('names')):
            found[name] = gate_text
    return found


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
    # What a frame lookup yields. Distinct from WebNavigationGetFrameDetails,
    # which the IDL declares for the details argument going the other way.
    EntityType('MenuItemUpdateProperties',
               'export interface MenuItemUpdateProperties', (
        EntityMember('checked?: boolean;', (Cite(MENUS_COCOA, 'checkedKey: @YES.class,'),)),
        EntityMember('command?: string;', (Cite(MENUS_COCOA, 'commandKey: NSString.class,'),)),
        EntityMember('contexts?: string[];', (Cite(MENUS_COCOA, 'contextsKey: @[ NSString.class ],'),)),
        EntityMember('documentUrlPatterns?: string[];', (
            Cite(MENUS_COCOA, 'documentURLPatternsKey: @[ NSString.class ],'),
            Cite(API_KEYS, 'static NSString * const documentURLPatternsKey = @"documentUrlPatterns";'))),
        EntityMember('enabled?: boolean;', (Cite(MENUS_COCOA, 'enabledKey: @YES.class,'),)),
        EntityMember('icons?: string | Record<string, unknown> | null;', (
            Cite(MENUS_COCOA,
                 'iconsKey: [NSOrderedSet orderedSetWithObjects:NSString.class, '
                 'NSDictionary.class, NSNull.class, nil],'),)),
        EntityMember('iconVariants?: Record<string, unknown>[] | null;', (
            Cite(MENUS_COCOA,
                 'iconVariantsKey: [NSOrderedSet orderedSetWithObjects:'
                 '@[ NSDictionary.class ], NSNull.class, nil],'),)),
        EntityMember('id?: string | number;', (
            Cite(MENUS_COCOA,
                 'idKey: [NSOrderedSet orderedSetWithObjects:NSString.class, '
                 'NSNumber.class, nil],'),)),
        EntityMember('onclick?: (...args: never[]) => void;', (
            Cite(MENUS_COCOA, 'onclickKey: JSValue.class,'),)),
        EntityMember('parentId?: string | number;', (
            Cite(MENUS_COCOA,
                 'parentIdKey: [NSOrderedSet orderedSetWithObjects:NSString.class, '
                 'NSNumber.class, nil],'),)),
        EntityMember('targetUrlPatterns?: string[];', (
            Cite(MENUS_COCOA, 'targetURLPatternsKey: @[ NSString.class ],'),
            Cite(API_KEYS, 'static NSString * const targetURLPatternsKey = @"targetUrlPatterns";'))),
        EntityMember('title?: string;', (Cite(MENUS_COCOA, 'titleKey: NSString.class,'),)),
        EntityMember('type?: string;', (Cite(MENUS_COCOA, '@"type": NSString.class,'),)),
        EntityMember('visible?: boolean;', (Cite(MENUS_COCOA, 'visibleKey: @YES.class,'),)),
    )),
    EntityType('InjectionTarget', 'export interface InjectionTarget', (
        EntityMember('tabId: number;', (Cite(SCRIPTING_COCOA, 'tabIDKey: NSNumber.class,'),
                                        Cite(SCRIPTING_COCOA, 'static auto *requiredKeys = @[ tabIDKey, ];'))),
        EntityMember('allFrames?: boolean;', (Cite(SCRIPTING_COCOA, 'allFramesKey: @YES.class, documentIDsKey'),)),
        EntityMember('documentIds?: string[];', (Cite(SCRIPTING_COCOA, 'documentIDsKey: @[ NSString.class ],'),)),
        EntityMember('frameIds?: number[];', (Cite(SCRIPTING_COCOA, 'frameIDsKey: @[ NSNumber.class ],'),)),
    )),
    EntityType('CSSInjection', 'export interface CSSInjection', (
        EntityMember('target: browser.InjectionTarget;', (
            Cite(SCRIPTING_COCOA, 'cssKey: NSString.class, filesKey: @[ NSString.class ], @"origin": NSString.class, targetKey: NSDictionary.class,'),
            Cite(SCRIPTING_COCOA, 'parseCSSInjectionOptions(NSDictionary *cssInfo, WebExtensionScriptInjectionParameters& parameters, NSString **outExceptionString) { static NSArray<NSString *> *requiredKeys = @[ targetKey, ];'))),
        EntityMember('css?: string;', (Cite(SCRIPTING_COCOA, 'cssKey: NSString.class,'),)),
        EntityMember('files?: string[];', (Cite(SCRIPTING_COCOA, 'cssKey: NSString.class, filesKey: @[ NSString.class ],'),)),
        EntityMember('origin?: string;', (Cite(SCRIPTING_COCOA, '@"origin": NSString.class,'),)),
    )),
    EntityType('TabUpdateOptions', 'export interface TabUpdateOptions', (
        EntityMember('active?: boolean;', (Cite(TABS_COCOA, 'activeKey: @YES.class, highlightedKey: @YES.class, mutedKey: @YES.class, openerTabIdKey'),)),
        EntityMember('highlighted?: boolean;', (Cite(TABS_COCOA, 'highlightedKey: @YES.class, mutedKey: @YES.class, openerTabIdKey'),)),
        EntityMember('muted?: boolean;', (Cite(TABS_COCOA, 'mutedKey: @YES.class, openerTabIdKey: NSNumber.class,'),)),
        EntityMember('openerTabId?: number;', (Cite(TABS_COCOA, 'openerTabIdKey: NSNumber.class,'),)),
        EntityMember('pinned?: boolean;', (Cite(TABS_COCOA, 'openerTabIdKey: NSNumber.class, pinnedKey: @YES.class,'),)),
        EntityMember('selected?: boolean;', (Cite(TABS_COCOA, 'pinnedKey: @YES.class, selectedKey: @YES.class, urlKey: NSString.class,'),)),
        EntityMember('url?: string;', (Cite(TABS_COCOA, 'urlKey: NSString.class,'),)),
    )),
    EntityType('TabQueryOptions', 'export interface TabQueryOptions', (
        EntityMember('active?: boolean;', (Cite(TABS_COCOA, 'activeKey: @YES.class, audibleKey: @YES.class,'),)),
        EntityMember('audible?: boolean;', (Cite(TABS_COCOA, 'audibleKey: @YES.class,'),)),
        EntityMember('currentWindow?: boolean;', (Cite(TABS_COCOA, 'currentWindowKey: @YES.class,'),)),
        EntityMember('hidden?: boolean;', (Cite(TABS_COCOA, 'hiddenKey: @YES.class,'),)),
        EntityMember('highlighted?: boolean;', (Cite(TABS_COCOA, 'hiddenKey: @YES.class, highlightedKey: @YES.class,'),)),
        EntityMember('index?: number;', (Cite(TABS_COCOA, 'indexKey: NSNumber.class, lastFocusedWindowKey'),)),
        EntityMember('lastFocusedWindow?: boolean;', (Cite(TABS_COCOA, 'lastFocusedWindowKey: @YES.class,'),)),
        EntityMember('muted?: boolean;', (Cite(TABS_COCOA, 'lastFocusedWindowKey: @YES.class, mutedKey: @YES.class,'),)),
        EntityMember('pinned?: boolean;', (Cite(TABS_COCOA, 'mutedKey: @YES.class, pinnedKey: @YES.class, selectedKey: @YES.class, statusKey'),)),
        EntityMember('selected?: boolean;', (Cite(TABS_COCOA, 'selectedKey: @YES.class, statusKey: NSString.class,'),)),
        EntityMember('status?: browser.TabStatus;', (Cite(TABS_COCOA, 'statusKey: NSString.class,'),)),
        EntityMember('title?: string;', (Cite(TABS_COCOA, 'statusKey: NSString.class, titleKey: NSString.class,'),)),
        EntityMember('url?: string | string[];', (
            Cite(TABS_COCOA,
                 'urlKey: [NSOrderedSet orderedSetWithObjects:NSString.class, '
                 '@[ NSString.class ], nil],'),)),
        EntityMember('windowId?: number;', (Cite(TABS_COCOA, 'windowIdKey: NSNumber.class, windowTypeKey: NSString.class,'),)),
        EntityMember('windowType?: browser.WindowType;', (Cite(TABS_COCOA, 'windowTypeKey: NSString.class,'),)),
    )),
    EntityType('TabScriptInjection', 'export interface TabScriptInjection', (
        EntityMember('allFrames?: boolean;', (Cite(TABS_COCOA, 'allFramesKey: @YES.class,'),)),
        EntityMember('code?: string;', (Cite(TABS_COCOA, 'codeKey: NSString.class,'),)),
        EntityMember('documentId?: string;', (Cite(TABS_COCOA, 'codeKey: NSString.class, documentIdKey: NSString.class,'),)),
        EntityMember('file?: string;', (Cite(TABS_COCOA, 'fileKey: NSString.class,'),)),
        EntityMember('frameId?: number;', (Cite(TABS_COCOA, 'fileKey: NSString.class, frameIdKey: NSNumber.class,'),)),
        EntityMember('tabId?: number;', (Cite(TABS_COCOA, 'tabIdKey: NSNumber.class,'),)),
    )),
    EntityType('WindowQueryOptions', 'export interface WindowQueryOptions', (
        EntityMember('populate?: boolean;', (
            Cite(WINDOWS_COCOA, 'populateKey: @YES.class,'),)),
        EntityMember('windowTypes?: browser.WindowType[];', (
            Cite(WINDOWS_COCOA, 'windowTypesKey: @[ NSString.class ],'),)),
    )),
    EntityType('WindowUpdateOptions', 'export interface WindowUpdateOptions', (
        EntityMember('state?: browser.WindowState;', (
            Cite(WINDOWS_COCOA, 'stateKey: NSString.class,'),)),
        EntityMember('focused?: boolean;', (
            Cite(WINDOWS_COCOA, 'focusedKey: @YES.class,'),)),
        EntityMember('top?: number;', (Cite(WINDOWS_COCOA, 'topKey: NSNumber.class,'),)),
        EntityMember('left?: number;', (Cite(WINDOWS_COCOA, 'leftKey: NSNumber.class,'),)),
        EntityMember('width?: number;', (Cite(WINDOWS_COCOA, 'widthKey: NSNumber.class,'),)),
        EntityMember('height?: number;', (Cite(WINDOWS_COCOA, 'heightKey: NSNumber.class,'),)),
    )),
    EntityType('FrameDetails', 'export interface FrameDetails', (
        EntityMember('errorOccurred: boolean;', (
            Cite(WEB_NAVIGATION_COCOA,
                 'result[errorOccurredKey] = @(frameInfo.errorOccurred);'),
            Cite(WEB_NAVIGATION_COCOA,
                 'static NSString *errorOccurredKey = @"errorOccurred";'))),
        EntityMember('parentFrameId: number;', (
            Cite(WEB_NAVIGATION_COCOA,
                 'result[parentFrameIdKey] = @(toWebAPI(frameInfo.parentFrameIdentifier));'),
            Cite(WEB_NAVIGATION_COCOA,
                 'static NSString *parentFrameIdKey = @"parentFrameId";'))),
        EntityMember('url: string;', (
            Cite(WEB_NAVIGATION_COCOA,
                 'result[urlKey] = frameInfo.url && !frameInfo.url.value().isNull() ? '
                 'frameInfo.url.value().string().createNSString().get() : emptyURLValue;'),
            Cite(WEB_NAVIGATION_COCOA, 'static NSString *urlKey = @"url";'))),
        EntityMember('frameId?: number;', (
            Cite(WEB_NAVIGATION_COCOA,
                 'if (frameInfo.frameIdentifier) result[frameIdKey] = '
                 '@(toWebAPI(frameInfo.frameIdentifier.value()));'),
            Cite(WEB_NAVIGATION_COCOA, 'static NSString *frameIdKey = @"frameId";'))),
        EntityMember('documentId?: string;', (
            Cite(WEB_NAVIGATION_COCOA,
                 'if (frameInfo.documentIdentifier) result[documentIdKey] = '
                 'frameInfo.documentIdentifier.value().toString().createNSString().get();'),
            Cite(WEB_NAVIGATION_COCOA,
                 'static NSString *documentIdKey = @"documentId";'))),
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


# Lines of each IDL that a parse rule accounted for, keyed by repo path.
# Populated during parsing; check_parse_coverage turns anything left over into a
# build failure so upstream syntax the parser does not understand is loud rather
# than silently dropped.
PARSE_COVERAGE = {}

# Structure the parser reads without producing a member: declaration headers,
# the extended-attribute block above an interface, and closing braces.
IGNORABLE_IDL = [
    re.compile(r'^\s*$'),
    re.compile(r'^\s*(enum|dictionary|interface)\s+\w+'),
    re.compile(r'^\s*\]?\s*(partial\s+)?interface\s+\w+'),
    re.compile(r'^\s*[\[\]{}]+\s*;?\s*$'),
    re.compile(r'^\s*\};\s*$'),
    re.compile(r'^\s*\w+(=[\w&|\s]+)?,?\s*$'),
    re.compile(r'^\s*"[^"]*"\s*,?\s*$'),
]


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

    consumed = set()

    def line_of(offset):
        lineno = 1
        for n, start in enumerate(line_starts):
            if start > offset:
                break
            lineno = n + 1
        return lineno

    def source_span(start, end):
        # Skip leading whitespace: a statement begins after the previous
        # statement's semicolon, so its raw offset lands on the previous line
        # and would mark that line parsed.
        lead = len(original[start:end]) - len(original[start:end].lstrip())
        start += lead
        return {
            'path': repo_path,
            'quote': original[start:end].strip(),
            'line': line_of(start),
            'endLine': line_of(max(start, end - 1)),
        }

    def consume(span):
        """Marks a span parsed. Called only where a rule produced a member, so
        that syntax no rule matched stays visible to check_parse_coverage."""
        consumed.update(range(span['line'], span['endLine'] + 1))
        return span

    enums = {}
    for m in re.finditer(r'enum\s+(\w+)\s*\{([^}]+)\};', content):
        name = m.group(1)
        raw_vals = m.group(2)
        vals = [re.sub(r'[\"\'\s]', '', v) for v in raw_vals.split(',') if v.strip()]
        enums[name] = [v for v in vals if v]
        consume(source_span(m.start(2), m.end(2)))

    dictionaries = {}
    for m in re.finditer(r'dictionary\s+(\w+)(?:\s*:\s*(\w+))?\s*\{([^}]+)\};', content):
        dict_name, parent_name, members_raw = m.group(1), m.group(2), m.group(3)
        members = {}
        for line, start in split_statements(members_raw, m.start(3)):
            member_span = source_span(start, start + len(line))
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
                consume(member_span)
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
                    consume(declaration)
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
                    consume(declaration)
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
                    consume(declaration)
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

    PARSE_COVERAGE[repo_path] = {
        'consumed': consumed,
        'lines': content.splitlines(),
    }
    return enums, dictionaries, interfaces


# ---------------------------------------------------------------------------
# Algorithmic resolution
# ---------------------------------------------------------------------------


WEB_REQUEST_COCOA = (
    'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWebRequestCocoa.mm')
WEB_REQUEST_EVENT_COCOA = (
    'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWebRequestEventCocoa.mm')

# Payloads for event attributes whose IDL type alone does not say what listeners
# receive. Anything Event-typed and absent here falls back to an open argument
# list, which claims nothing, so this table is the only place an event payload
# can be asserted.
#
# webRequest listeners get one argument. The tab, window and resource-load
# values passed alongside it reach enumerateListeners for filtering and never
# the callback. requestBody is intersected in because the implementation sets it
# and WebExtensionWebRequestDetails does not declare it.
EVENT_PAYLOADS = {
    'WebRequestEvent': (
        'events.WebRequestEvent<(details: browser.WebRequestDetails) => void>',
        (Cite(WEB_REQUEST_EVENT_COCOA,
              'listener.call(toJSValueRef(listener.globalContext(), argument.get()));'),),
    ),
}

# Payloads for one attribute that differ from the rest of its IDL type. Only
# onBeforeRequest can carry requestBody: requestBodyKey is set at exactly one
# dispatch in the implementation, inside onBeforeRequest's enumerateListeners.
# The other eight WebRequestEvent attributes never see it, so declaring it on
# them would be an optional key that never appears.
ATTRIBUTE_PAYLOADS = {
    ('WebExtensionAPIWebRequest', 'onBeforeRequest'): (
        'events.WebRequestEvent<(details: browser.WebRequestDetails & '
        '{ requestBody?: { formData?: Record<string, unknown[]>; '
        'raw?: { bytes?: unknown }[]; error?: string } }) => void>',
        (Cite(WEB_REQUEST_COCOA,
              'namespaceObject.webRequest().onBeforeRequest().enumerateListeners('
              'tabID, windowID, resourceLoad, [&](auto& listener, auto& extraInfo) { '
              'if (formData && extraInfo.contains(String(requestBodyKey))) {'),
         Cite(WEB_REQUEST_COCOA, 'result[formDataKey] = [formDataDictionary copy];'),
         Cite(WEB_REQUEST_COCOA, 'result[rawKey] = [rawArray copy];'),
         Cite(WEB_REQUEST_COCOA,
              'result[errorKey] = @"Request body data is malformed or unsupported.";')),
    ),
}

# Parameter types read from the operation's own validation in the
# implementation, rather than guessed by composing a dictionary name. This is
# how an entry leaves unverified-parameters.txt.
#
# Each value is (type, citations). The first citation must occur exactly once
# in its file and identifies the operation, usually its signature; any further
# citation is the validation line the operation reaches, which may be shared
# between operations and only has to be present. Together they say "this
# operation reads this table", which is the claim the type rests on. Every quote
# was extracted at the pinned revision; the build rejects one that stops
# resolving.
#
# action: every operation taking details routes it through parseActionDetails,
# which accepts {tabId, windowId}; setters validate one further key on top, and
# the IDL dictionaries already carry all three. openPopup is the exception: it
# validates through parseActionDetails alone, so it accepts tabId, while
# WebExtensionActionOpenPopupOptions declares only windowId.
PARAMETER_TYPES = {
    ('action', 'getBadgeBackgroundColor', 'details'): (
        'browser.ActionDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::getBadgeBackgroundColor(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'if (auto actionDetailsResult = parseActionDetails(details, windowIdentifier, tabIdentifier); !actionDetailsResult) {'),)),
    ('action', 'getBadgeText', 'details'): (
        'browser.ActionDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::getBadgeText(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'if (auto actionDetailsResult = parseActionDetails(details, windowIdentifier, tabIdentifier); !actionDetailsResult) {'),)),
    ('action', 'getPopup', 'details'): (
        'browser.ActionDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::getPopup(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'if (auto actionDetailsResult = parseActionDetails(details, windowIdentifier, tabIdentifier); !actionDetailsResult) {'),)),
    ('action', 'getTitle', 'details'): (
        'browser.ActionDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::getTitle(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, String& outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'if (auto actionDetailsResult = parseActionDetails(details, windowIdentifier, tabIdentifier); !actionDetailsResult) {'),)),
    ('action', 'isEnabled', 'details'): (
        'browser.ActionDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::isEnabled(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'if (auto actionDetailsResult = parseActionDetails(details, windowIdentifier, tabIdentifier); !actionDetailsResult) {'),)),
    ('action', 'openPopup', 'options'): (
        'browser.ActionDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::openPopup(WebPageProxyIdentifier webPageProxyIdentifier, NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'if (auto actionDetailsResult = parseActionDetails(details, windowIdentifier, tabIdentifier); !actionDetailsResult) {'),)),
    ('action', 'setBadgeBackgroundColor', 'details'): (
        'browser.ActionSetBadgeBackgroundColorDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::setBadgeBackgroundColor(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'if (auto actionDetailsResult = parseActionDetails(details, windowIdentifier, tabIdentifier); !actionDetailsResult) {'),)),
    ('action', 'setBadgeText', 'details'): (
        'browser.ActionSetBadgeTextDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::setBadgeText(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'if (!validateDictionary(details, @"details", requiredKeys, types, outExceptionString))'),)),
    ('action', 'setIcon', 'details'): (
        'browser.ActionSetIconDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::setIcon(WebFrame& frame, NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'if (auto actionDetailsResult = parseActionDetails(details, windowIdentifier, tabIdentifier); !actionDetailsResult) {'),)),
    ('action', 'setPopup', 'details'): (
        'browser.ActionSetPopupDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::setPopup(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'if (!validateDictionary(details, @"details", requiredKeys, types, outExceptionString))'),)),
    ('action', 'setTitle', 'details'): (
        'browser.ActionSetTitleDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::setTitle(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, String& outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'if (!validateDictionary(details, @"details", requiredKeys, types, &cocoaExceptionString)) {'),)),

    # sidebarAction: parseSidebarActionDetails accepts tabId or windowId, not
    # both, and the setters validate one further key. isOpen deliberately does
    # not use it: "we don't use parseSidebarActionDetails here because we only
    # need windowId for isOpen", so declaring tabId there would invite a call
    # that silently does nothing. setIcon validates nothing at all because it is
    # unimplemented; its dictionary is what WebKit declares for it.
    ('sidebarAction', 'getPanel', 'details'): (
        'browser.SidebarActionDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'void WebExtensionAPISidebarAction::getPanel(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'auto result = parseSidebarActionDetails(details);'),)),
    ('sidebarAction', 'getTitle', 'details'): (
        'browser.SidebarActionDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'void WebExtensionAPISidebarAction::getTitle(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'auto result = parseSidebarActionDetails(details);'),)),
    ('sidebarAction', 'isOpen', 'details'): (
        '{ windowId?: number }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'id maybeWindowId = details[windowIdKey];'),)),
    ('sidebarAction', 'setIcon', 'details'): (
        'browser.SidebarActionSetIconDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'static NSString * const apiName = @"sidebarAction.setIcon()";'),)),
    ('sidebarAction', 'setPanel', 'details'): (
        'browser.SidebarActionSetPanelDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'void WebExtensionAPISidebarAction::setPanel(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'auto panelResult = parseDetailsStringFromKey(details, panelKey);'),)),
    ('sidebarAction', 'setTitle', 'details'): (
        'browser.SidebarActionSetTitleDetails',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'void WebExtensionAPISidebarAction::setTitle(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'auto titleResult = parseDetailsStringFromKey(details, titleKey);'),)),

    # permissions: parseDetailsDictionary validates exactly
    # {permissions?: string[], origins?: string[]}, with no required keys, which
    # is what WebExtensionPermissions declares.
    ('permissions', 'contains', 'permissions'): (
        'browser.Permissions',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'void WebExtensionAPIPermissions::contains(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'if (!parseDetailsDictionary(details, permissions, origins, apiName, outExceptionString))'),)),
    ('permissions', 'remove', 'permissions'): (
        'browser.Permissions',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'void WebExtensionAPIPermissions::remove(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'if (!parseDetailsDictionary(details, permissions, origins, apiName, outExceptionString))'),)),
    ('permissions', 'request', 'permissions'): (
        'browser.Permissions',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'void WebExtensionAPIPermissions::request(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'if (!parseDetailsDictionary(details, permissions, origins, apiName, outExceptionString))'),)),

    # webNavigation: both operations require their identifiers, while the IDL
    # dictionaries declare every member optional, so the declared form permits
    # {} and fails at runtime. processId is dropped because validateDictionary
    # ignores keys it was not given a type for; declaring it invites a no-op.
    ('webNavigation', 'getFrame', 'details'): (
        '{ tabId: number; frameId: number }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWebNavigationCocoa.mm',
             'void WebExtensionAPIWebNavigation::getFrame(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWebNavigationCocoa.mm',
             'if (!validateDictionary(details, @"details", requiredKeys, types, outExceptionString))'),)),
    ('webNavigation', 'getAllFrames', 'details'): (
        '{ tabId: number }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWebNavigationCocoa.mm',
             'void WebExtensionAPIWebNavigation::getAllFrames(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWebNavigationCocoa.mm',
             'if (!validateDictionary(details, @"details", requiredKeys, types, outExceptionString))'),)),

    # sidePanel: setOptions takes the whole dictionary and setPanelBehavior
    # validates exactly {openPanelOnActionClick?: boolean}. The other two read
    # less than WebExtensionSidePanelOptions declares, and they differ from each
    # other: open parses a tab and a window, getOptions parses only a tab and
    # sends std::nullopt for the window, so declaring windowId there would
    # invite a call that does nothing.
    ('sidePanel', 'getOptions', 'options'): (
        '{ tabId?: number }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
             'void WebExtensionAPISidePanel::getOptions(NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
             'auto result = parseTabIdentifier(options);'),)),
    ('sidePanel', 'open', 'options'): (
        '{ tabId?: number; windowId?: number }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
             'void WebExtensionAPISidePanel::open(NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
             'auto tabResult = parseTabIdentifier(options);'),)),
    ('sidePanel', 'setOptions', 'options'): (
        'browser.SidePanelOptions',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
             'void WebExtensionAPISidePanel::setOptions(NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
             'auto tabIdentifierResult = parseTabIdentifier(options);'),)),
    ('sidePanel', 'setPanelBehavior', 'behavior'): (
        'browser.SidePanelBehavior',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
             'void WebExtensionAPISidePanel::setPanelBehavior(NSDictionary *behavior, Ref<WebExtensionCallbackHandler>&& callback, NSString** outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
             'auto result = parseActionClickBehavior(behavior);'),)),

    # offscreen: all three keys are required, while the IDL declares them
    # optional, so createDocument({}) typechecked and failed at runtime.
    ('offscreen', 'createDocument', 'options'): (
        '{ url: string; justification: string; reasons: string[] }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIOffscreenCocoa.mm',
             'void WebExtensionAPIOffscreen::createDocument(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIOffscreenCocoa.mm',
             'if (!validateDictionary(details, @"parameters", requiredKeys, types, outExceptionString))'),)),

    # declarativeNetRequest: both filter keys are optional. tabId alone becomes
    # required, and only for an extension without the feedback permission, which
    # a type cannot express. minTimeStamp is never required.
    ('declarativeNetRequest', 'getMatchedRules', 'filter'): (
        'browser.DNRMatchedRulesFilter',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'void WebExtensionAPIDeclarativeNetRequest::getMatchedRules(NSDictionary *filter, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'if (!validateDictionary(filter, nil, requiredKeys, keyTypes, outExceptionString))'),)),
    # Read from each operation's validateDictionary table. These were widened to
    # Record<string, unknown> because no dictionary name composed, not because
    # the accepted keys were unknown.
    ('declarativeNetRequest', 'updateEnabledRulesets', 'options'): (
        '{ enableRulesetIds?: string[]; disableRulesetIds?: string[] }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'void WebExtensionAPIDeclarativeNetRequest::updateEnabledRulesets(NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'if (!validateDictionary(options, @"options", nil, types, outExceptionString))'),)),
    ('declarativeNetRequest', 'updateDynamicRules', 'options'): (
        '{ addRules?: Record<string, unknown>[]; removeRuleIds?: number[] }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'void WebExtensionAPIDeclarativeNetRequest::updateDynamicRules(NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'if (!validateDictionary(options, @"options", nil, keyTypes, outExceptionString))'),)),
    ('declarativeNetRequest', 'updateSessionRules', 'options'): (
        '{ addRules?: Record<string, unknown>[]; removeRuleIds?: number[] }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'void WebExtensionAPIDeclarativeNetRequest::updateSessionRules(NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'if (!validateDictionary(options, @"options", nil, keyTypes, outExceptionString))'),)),
    # tabUpdate carries its own validateDictionary with both keys required, so
    # they are required whenever tabUpdate is present. The outer table is a
    # separate call and says nothing about them.
    ('declarativeNetRequest', 'setExtensionActionOptions', 'options'): (
        '{ displayActionCountAsBadgeText?: boolean; ' 'tabUpdate?: { tabId: number; increment: number } }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'void WebExtensionAPIDeclarativeNetRequest::setExtensionActionOptions(NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'if (!validateDictionary(options, @"extensionActionOptions", nil, types, outExceptionString))'),)),
    # Found checking the nested-table class for siblings: regex is required, and
    # the parameter had been left as the IDL's any.
    ('declarativeNetRequest', 'isRegexSupported', 'regexOptions'): (
        '{ regex: string; isCaseSensitive?: boolean; requireCapturing?: boolean }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'void WebExtensionAPIDeclarativeNetRequest::isRegexSupported(NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'if (!validateDictionary(options, @"regexOptions", @[ regexKey ], types, outExceptionString))'),)),

    # windows: the four lookups parse a populate flag and a window-type filter.
    # create runs parseWindowUpdateOptions first and then adds its own four, so
    # it accepts everything update does.
    ('windows', 'get', 'properties'): (
        'browser.WindowQueryOptions',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'void WebExtensionAPIWindows::get(WebPageProxyIdentifier webPageProxyIdentifier, double windowID, NSDictionary *info, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'if (!parseWindowGetOptions(info, populate, filter, @"info", outExceptionString))'),)),
    ('windows', 'getAll', 'info'): (
        'browser.WindowQueryOptions',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'void WebExtensionAPIWindows::getAll(NSDictionary *info, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'if (!parseWindowGetOptions(info, populate, filter, @"info", outExceptionString))'),)),
    ('windows', 'getCurrent', 'info'): (
        'browser.WindowQueryOptions',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'void WebExtensionAPIWindows::getCurrent(WebPageProxyIdentifier webPageProxyIdentifier, NSDictionary *info, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'if (!parseWindowGetOptions(info, populate, filter, @"info", outExceptionString))'),)),
    ('windows', 'getLastFocused', 'info'): (
        'browser.WindowQueryOptions',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'void WebExtensionAPIWindows::getLastFocused(NSDictionary *info, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'if (!parseWindowGetOptions(info, populate, filter, @"info", outExceptionString))'),)),
    ('windows', 'update', 'properties'): (
        'browser.WindowUpdateOptions',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'void WebExtensionAPIWindows::update(double windowID, NSDictionary *info, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'if (!parseWindowUpdateOptions(info, parameters, @"properties", outExceptionString))'),)),
    ('windows', 'create', 'info'): (
        'browser.WindowUpdateOptions & { type?: browser.WindowType; ' 'incognito?: boolean; url?: string | string[]; tabId?: number }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'void WebExtensionAPIWindows::createWindow(NSDictionary *data, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'if (!parseWindowCreateOptions(data, parameters, @"info", outExceptionString))'),)),

    # tabs: create chains parseTabUpdateOptions before its own four keys, and
    # connect chains parseSendMessageOptions before adding name, so both are
    # intersections rather than copies. move requires index. The three injection
    # operations share parseScriptOptions and additionally demand file or code.
    ('tabs', 'update', 'properties'): (
        'browser.TabUpdateOptions',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::update(WebPageProxyIdentifier webPageProxyIdentifier, double tabID, NSDictionary *properties, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'if (!parseTabUpdateOptions(properties, parameters, @"properties", outExceptionString))'),)),
    ('tabs', 'create', 'properties'): (
        'browser.TabUpdateOptions & { index?: number; openInReaderMode?: boolean; ' 'title?: string; windowId?: number }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::createTab(WebPageProxyIdentifier webPageProxyIdentifier, NSDictionary *properties, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'if (!parseTabCreateOptions(properties, parameters, @"properties", outExceptionString))'),)),
    ('tabs', 'duplicate', 'properties'): (
        '{ active?: boolean; index?: number }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::duplicate(double tabID, NSDictionary *properties, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'if (properties && !parseTabDuplicateOptions(properties, parameters, @"properties", outExceptionString))'),)),
    ('tabs', 'query', 'info'): (
        'browser.TabQueryOptions',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::query(WebPageProxyIdentifier webPageProxyIdentifier, NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'if (!parseTabQueryOptions(options, parameters, @"info", outExceptionString))'),)),
    ('tabs', 'captureVisibleTab', 'options'): (
        '{ format?: string; quality?: number }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::captureVisibleTab(WebPageProxyIdentifier webPageProxyIdentifier, double windowID, NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'if (!parseCaptureVisibleTabOptions(options, imageFormat, imageQuality, @"options", outExceptionString))'),)),
    ('tabs', 'connect', 'options'): (
        '{ frameId?: number; documentId?: string; name?: string }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'RefPtr<WebExtensionAPIPort> WebExtensionAPITabs::connect(WebFrame& frame, JSContextRef context, double tabID, NSDictionary *options, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'if (!parseConnectOptions(options, name, targetParameters, @"options", outExceptionString))'),)),
    ('tabs', 'move', 'properties'): (
        '{ index: number; windowId?: number }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::move(NSObject *tabIDs, NSDictionary *properties, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'if (!parseTabIdentifiers(tabIDs, identifiers, @"tabIDs", outExceptionString))'),)),
    ('tabs', 'reload', 'properties'): (
        '{ bypassCache?: boolean }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::reload(WebPageProxyIdentifier webPageProxyIdentifier, double tabID, NSDictionary *properties, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'if (properties && !validateDictionary(properties, @"properties", nil, types, outExceptionString))'),)),
    # cookies: every operation runs parseCookieDetails, which accepts
    # {name, storeId, url} and takes its required keys from the caller. get and
    # remove require name and url, set requires url, getAll requires nothing and
    # validates four filter keys of its own.
    ('cookies', 'get', 'details'): (
        '{ name: string; url: string; storeId?: string }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'void WebExtensionAPICookies::get(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'auto parsedDetails = parseCookieDetails(details, @[ @"name", urlKey ], outExceptionString);'),)),
    ('cookies', 'remove', 'details'): (
        '{ name: string; url: string; storeId?: string }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'void WebExtensionAPICookies::remove(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'auto parsedDetails = parseCookieDetails(details, @[ @"name", urlKey ], outExceptionString);'),)),
    ('cookies', 'getAll', 'details'): (
        '{ name?: string; url?: string; storeId?: string; domain?: string; ' 'path?: string; secure?: boolean; session?: boolean }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'void WebExtensionAPICookies::getAll(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'auto parsedDetails = parseCookieDetails(details, nil, outExceptionString);'),)),
    ('cookies', 'set', 'details'): (
        '{ url: string; name?: string; storeId?: string; domain?: string; ' 'path?: string; value?: string; expirationDate?: number; ' 'httpOnly?: boolean; secure?: boolean; ' 'sameSite?: browser.CookieSameSiteStatus }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'void WebExtensionAPICookies::set(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'auto parsedDetails = parseCookieDetails(details, @[ urlKey ], outExceptionString);'),)),

    # scripting: both CSS operations require target, which chains
    # parseTargetInjectionOptions and requires tabId inside it. allFrames and
    # frameIds are mutually exclusive, which a type cannot express.
    ('scripting', 'insertCSS', 'details'): (
        'browser.CSSInjection',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIScriptingCocoa.mm',
             'void WebExtensionAPIScripting::insertCSS(NSDictionary *cssInfo, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),)),
    ('scripting', 'removeCSS', 'details'): (
        'browser.CSSInjection',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIScriptingCocoa.mm',
             'void WebExtensionAPIScripting::removeCSS(NSDictionary *cssInfo, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),)),

    # alarms: when and delayInMinutes are mutually exclusive, and name may not
    # be given here when it is also the first argument. Both are runtime rules.
    ('alarms', 'create', 'info'): (
        '{ name?: string; when?: number; delayInMinutes?: number; ' 'periodInMinutes?: number }',
        (Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPIAlarms.cpp',
             'void WebExtensionAPIAlarms::createAlarm(const String& name, RefPtr<JSON::Value> alarmInfo, Ref<WebExtensionCallbackHandler>&& callback, String& outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPIAlarms.cpp',
             'if (!validateDictionary(alarmInfo, "info"_s, { }, {'),)),

    # menus: create and update share parseCreateAndUpdateProperties. title is
    # required only for create, and only when the item is not a separator, so
    # update requires nothing. iconVariants sits behind
    # ENABLE(WK_WEB_EXTENSIONS_ICON_VARIANTS), which defaults to
    # ENABLE(WK_WEB_EXTENSIONS): it is on wherever the API exists at all, so it
    # is not conditional in any build that has menus.
    ('menus', 'update', 'properties'): (
        'browser.MenuItemUpdateProperties',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIMenusCocoa.mm',
             'void WebExtensionAPIMenus::update(WebPage& page, WebFrame& frame, id identifier, NSDictionary *properties, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIMenusCocoa.mm',
             'if (!validateObject(identifier, @"identifier", [NSOrderedSet orderedSetWithObjects:NSString.class, NSNumber.class, nil], outExceptionString))'),)),

    # The last hand-written rules, now read. tabs takes numbers,
    # bookmarks strings, i18n strings, and menus identifiers are the same
    # string-or-number its create table accepts.
    ('tabs', 'move', 'tabIDs'): (
        'number | number[]',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::move(NSObject *tabIDs, NSDictionary *properties, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'if (!parseTabIdentifiers(tabIDs, identifiers, @"tabIDs", outExceptionString))'),)),
    ('tabs', 'remove', 'tabIDs'): (
        'number | number[]',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::remove(NSObject *tabIDs, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'if (!parseTabIdentifiers(tabIDs, identifiers, @"tabIDs", outExceptionString))'),)),
    ('bookmarks', 'get', 'idOrIdList'): (
        'string | string[]',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'if ([idOrIdList isKindOfClass:[NSString class]]) {'),)),
    ('i18n', 'getMessage', 'substitutions'): (
        'string | string[]',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPILocalizationCocoa.mm',
             'if ([substitutions isKindOfClass:NSString.class])'),)),
    ('menus', 'remove', 'identifier'): (
        'number | string',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIMenusCocoa.mm',
             'void WebExtensionAPIMenus::remove(id identifier, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIMenusCocoa.mm',
             'if (!validateObject(identifier, @"identifier", [NSOrderedSet orderedSetWithObjects:NSString.class, NSNumber.class, nil], outExceptionString))'),)),
    ('menus', 'update', 'identifier'): (
        'number | string',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIMenusCocoa.mm',
             'void WebExtensionAPIMenus::update(WebPage& page, WebFrame& frame, id identifier, NSDictionary *properties, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIMenusCocoa.mm',
             'if (!validateObject(identifier, @"identifier", [NSOrderedSet orderedSetWithObjects:NSString.class, NSNumber.class, nil], outExceptionString))'),)),
    ('scripting', 'registerContentScripts', 'scripts'): (
        'browser.RegisteredContentScript[]',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIScriptingCocoa.mm',
             'if (!parseRegisteredContentScripts(scripts, FirstTimeRegistration::Yes, parameters, outExceptionString))'),)),
    ('scripting', 'updateContentScripts', 'scripts'): (
        'browser.RegisteredContentScript[]',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIScriptingCocoa.mm',
             'if (!parseRegisteredContentScripts(scripts, FirstTimeRegistration::No, parameters, outExceptionString))'),)),

    # Not a MessageSender. Both resolve the argument with
    # WebFrame::contentFrameForWindowOrFrameElement, so it is a window object or
    # a frame element and nothing else.
    ('runtime', 'getFrameId', 'target'): (
        'globalThis.Window | globalThis.HTMLIFrameElement | globalThis.HTMLFrameElement',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'RefPtr frame = WebFrame::contentFrameForWindowOrFrameElement(target.context.JSGlobalContextRef, target.JSValueRef);'),)),
    ('runtime', 'getDocumentId', 'target'): (
        'globalThis.Window | globalThis.HTMLIFrameElement | globalThis.HTMLFrameElement',
        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'RefPtr frame = target ? WebFrame::contentFrameForWindowOrFrameElement(target.context.JSGlobalContextRef, target.JSValueRef) : nullptr;'),)),
}

# How each parameter's type was decided, keyed by (namespace, operation,
# argument). Instrumentation, not logic: generation is a single deterministic
# pass, and generate_dts clears this before it starts.
PARAM_DERIVATIONS = {}

# IDL dictionary members the implementation contradicts. Dictionaries are
# otherwise emitted exactly as WebKit declares them; an entry here replaces one
# member of one dictionary with what the implementation actually reads, and
# cites the line that reads it. Keyed by (dictionary, IDL member name); the
# value is the emitted TypeScript member and its citations. A key that names a
# dictionary or member the IDL does not declare fails the build, so this table
# can correct a member but never invent one.
DICTIONARY_MEMBER_CORRECTIONS = {
    # WebExtensionDNRTabUpdateOptions declares `count`. setExtensionActionOptions
    # validates the nested tabUpdate dictionary against `increment`, required,
    # and reads that key. Safari never looks at `count`.
    ('WebExtensionDNRTabUpdateOptions', 'count'): (
        'increment: number;',
        (Cite(DNR_COCOA,
              'if (!validateDictionary(tabUpdateDictionary, @"tabUpdate", '
              '@[ actionCountTabIDKey, actionCountIncrementKey ], tabUpdateTypes, '
              'outExceptionString))'),
         Cite(API_KEYS, 'static NSString * const actionCountIncrementKey = @"increment";'))),
    ('WebExtensionDNRTabUpdateOptions', 'tabId'): (
        'tabId: number;',
        (Cite(DNR_COCOA,
              'if (!validateDictionary(tabUpdateDictionary, @"tabUpdate", '
              '@[ actionCountTabIDKey, actionCountIncrementKey ], tabUpdateTypes, '
              'outExceptionString))'),)),
}

# Return-side evidence for every operation that hands the callback a payload,
# or returns synchronously. The first citation must occur exactly once in its
# file and identifies the operation; any further one is the line that shows what
# it hands back. Together with CONFIRMED_EMPTY_CALLBACKS this covers every
# operation in every read namespace, which is what READ_NAMESPACES had been
# asserting with nothing behind it.
#
# A namespace may be in READ_NAMESPACES only if every one of its operations is
# in exactly one of these two tables; the build checks that.
RETURN_EVIDENCE = {
    ('action', 'getBadgeBackgroundColor'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::getBadgeBackgroundColor(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'callback->call(fromArray(callback->globalContext(), { 255, 0, 0, 255 }));'),),
    ('action', 'getBadgeText'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::getBadgeText(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'SUPPRESS_UNCOUNTED_ARG callback->call(JSValueMakeString(callback->globalContext(), toJSString(result.value()).get()));'),),
    ('action', 'getPopup'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::getPopup(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'SUPPRESS_UNCOUNTED_ARG callback->call(JSValueMakeString(callback->globalContext(), toJSString(result.value()).get()));'),),
    ('action', 'getTitle'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::getTitle(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, String& outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'SUPPRESS_UNCOUNTED_ARG callback->call(JSValueMakeString(callback->globalContext(), toJSString(result.value()).get()));'),),
    ('action', 'isEnabled'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'void WebExtensionAPIAction::isEnabled(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIActionCocoa.mm',
             'callback->call(JSValueMakeBoolean(callback->globalContext(), result.value()));'),),
    ('alarms', 'clear'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPIAlarms.cpp',
             'void WebExtensionAPIAlarms::clear(const String& name, Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPIAlarms.cpp',
             'callback->call(JSValueMakeBoolean(callback->globalContext(), success));'),),
    ('alarms', 'clearAll'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPIAlarms.cpp',
             'void WebExtensionAPIAlarms::clearAll(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPIAlarms.cpp',
             'callback->call(JSValueMakeBoolean(callback->globalContext(), success));'),),
    ('alarms', 'get'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPIAlarms.cpp',
             'void WebExtensionAPIAlarms::get(const String& name, Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPIAlarms.cpp',
             'callback->call(toWebAPI(callback->globalContext(), alarm, UseNullValue::No));'),),
    ('alarms', 'getAll'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPIAlarms.cpp',
             'void WebExtensionAPIAlarms::getAll(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPIAlarms.cpp',
             'callback->call(toWebAPI(callback->globalContext(), alarms));'),),
    ('bookmarks', 'create'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'void WebExtensionAPIBookmarks::createBookmark(NSDictionary *bookmark, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'callback->call(newNodeDictionary);'),),
    ('bookmarks', 'get'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'void WebExtensionAPIBookmarks::get(NSObject *idOrIdList, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'callback->call(resultArray);'),),
    ('bookmarks', 'getChildren'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'void WebExtensionAPIBookmarks::getChildren(NSString *bookmarkIdentifier, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'callback->call(resultArray);'),),
    ('bookmarks', 'getRecent'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'void WebExtensionAPIBookmarks::getRecent(long long numberOfItems, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'callback->call(resultArray);'),),
    ('bookmarks', 'getSubTree'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'void WebExtensionAPIBookmarks::getSubTree(NSString *bookmarkIdentifier, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'callback->call(@[], nil);'),),
    ('bookmarks', 'getTree'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'void WebExtensionAPIBookmarks::getTree(Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'callback->call(resultArray);'),),
    ('bookmarks', 'move'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'void WebExtensionAPIBookmarks::move(NSString *bookmarkIdentifier, NSDictionary *destination, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'callback->call(movedNodeDictionary);'),),
    ('bookmarks', 'search'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'void WebExtensionAPIBookmarks::search(NSObject *query, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'callback->call(resultArray);'),),
    ('bookmarks', 'update'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'void WebExtensionAPIBookmarks::update(NSString *bookmarkIdentifier, NSDictionary *changes, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIBookmarksCocoa.mm',
             'callback->call(updatedNodeDictionary);'),),
    ('commands', 'getAll'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICommandsCocoa.mm',
             'void WebExtensionAPICommands::getAll(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICommandsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toAPI(commands)));'),),
    ('cookies', 'get'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'void WebExtensionAPICookies::get(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('cookies', 'getAll'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'void WebExtensionAPICookies::getAll(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('cookies', 'getAllCookieStores'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'void WebExtensionAPICookies::getAllCookieStores(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value(), protectedThis->extensionContext().defaultSessionID())));'),),
    ('cookies', 'remove'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'void WebExtensionAPICookies::remove(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('cookies', 'set'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'void WebExtensionAPICookies::set(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('declarativeNetRequest', 'getDynamicRules'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'void WebExtensionAPIDeclarativeNetRequest::getDynamicRules(NSDictionary *filter, Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'callback->call(fromJSON(callback->globalContext(), JSON::Value::parseJSON(result.value())));'),),
    ('declarativeNetRequest', 'getEnabledRulesets'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'void WebExtensionAPIDeclarativeNetRequest::getEnabledRulesets(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'callback->call(fromArray(callback->globalContext(), WTF::move(enabledRulesets)));'),),
    ('declarativeNetRequest', 'getMatchedRules'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'void WebExtensionAPIDeclarativeNetRequest::getMatchedRules(NSDictionary *filter, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('declarativeNetRequest', 'getSessionRules'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'void WebExtensionAPIDeclarativeNetRequest::getSessionRules(NSDictionary *filter, Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'callback->call(fromJSON(callback->globalContext(), JSON::Value::parseJSON(result.value())));'),),
    ('declarativeNetRequest', 'isRegexSupported'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'void WebExtensionAPIDeclarativeNetRequest::isRegexSupported(NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDeclarativeNetRequestCocoa.mm',
             'SUPPRESS_UNCOUNTED_ARG callback->call(fromObject(callback->globalContext(), {'),),
    ('dom', 'openOrClosedShadowRoot'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDOMCocoa.mm',
             'JSValue *WebExtensionAPIDOM::openOrClosedShadowRoot(JSValue *element)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIDOMCocoa.mm',
             'return [element valueForProperty:@"openOrClosedShadowRoot"];'),),
    ('extension', 'isAllowedFileSchemeAccess'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIExtensionCocoa.mm',
             'void WebExtensionAPIExtension::isAllowedFileSchemeAccess(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIExtensionCocoa.mm',
             'callback->call(JSValueMakeBoolean(callback->globalContext(), false));'),),
    ('extension', 'isAllowedIncognitoAccess'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIExtensionCocoa.mm',
             'void WebExtensionAPIExtension::isAllowedIncognitoAccess(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIExtensionCocoa.mm',
             'callback->call(JSValueMakeBoolean(callback->globalContext(), result));'),),
    ('i18n', 'getAcceptLanguages'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPILocalizationCocoa.mm',
             'void WebExtensionAPILocalization::getAcceptLanguages(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPILocalizationCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), acceptLanguages.array));'),),
    ('i18n', 'getMessage'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPILocalizationCocoa.mm',
             'NSString *WebExtensionAPILocalization::getMessage(NSString* messageName, id substitutions)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPILocalizationCocoa.mm',
             'return @"";'),),
    ('i18n', 'getPreferredSystemLanguages'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPILocalizationCocoa.mm',
             'void WebExtensionAPILocalization::getPreferredSystemLanguages(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPILocalizationCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), NSLocale.preferredLanguages));'),),
    ('i18n', 'getSystemUILanguage'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPILocalizationCocoa.mm',
             'void WebExtensionAPILocalization::getSystemUILanguage(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPILocalizationCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), NSLocale._deviceLanguage));'),),
    ('i18n', 'getUILanguage'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPILocalizationCocoa.mm',
             'NSString *WebExtensionAPILocalization::getUILanguage()'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPILocalizationCocoa.mm',
             'return toWebAPI(NSLocale.currentLocale);'),),
    ('offscreen', 'hasDocument'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIOffscreenCocoa.mm',
             'void WebExtensionAPIOffscreen::hasDocument(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIOffscreenCocoa.mm',
             'callback->call(JSValueMakeBoolean(callback->globalContext(), result.value()));'),),
    ('permissions', 'contains'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'void WebExtensionAPIPermissions::contains(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'callback->call(JSValueMakeBoolean(callback->globalContext(), containsPermissions));'),),
    ('permissions', 'getAll'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'void WebExtensionAPIPermissions::getAll(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'callback->call(fromObject(globalContext, { { permissionsKey, Protected(globalContext, permissionsValue) },'),),
    ('permissions', 'remove'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'void WebExtensionAPIPermissions::remove(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'callback->call(JSValueMakeBoolean(callback->globalContext(), success));'),),
    ('permissions', 'request'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'void WebExtensionAPIPermissions::request(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',
             'callback->call(JSValueMakeBoolean(callback->globalContext(), success));'),),
    ('runtime', 'connectNative'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'RefPtr<WebExtensionAPIPort> WebExtensionAPIRuntime::connectNative(WebPageProxyIdentifier webPageProxyIdentifier, JSContextRef context, const String& applicationID)'),),
    ('runtime', 'getBackgroundPage'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'void WebExtensionAPIRuntime::getBackgroundPage(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'callback->call(toWindowObject(callback->globalContext(), *backgroundPage));'),),
    ('runtime', 'getDocumentId'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'String WebExtensionAPIRuntime::getDocumentId(JSValue *target, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'return String();'),),
    ('runtime', 'getFrameId'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'double WebExtensionAPIRuntime::getFrameId(JSValue *target)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'return WebExtensionFrameConstants::None;'),),
    ('runtime', 'getPlatformInfo'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'void WebExtensionAPIRuntime::getPlatformInfo(Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'SUPPRESS_UNCOUNTED_ARG callback->call(fromObject(callback->globalContext(), {'),),
    ('runtime', 'getURL'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'NSURL *WebExtensionAPIRuntime::getURL(const String& resourcePath, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'return URL { extensionContext().baseURL(), resourcePath }.createNSURL().autorelease();'),),
    ('runtime', 'getVersion'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'String WebExtensionAPIRuntime::getVersion()'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'return manifest ? manifest->getString(versionKey) : nullString();'),),
    ('runtime', 'reload'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIRuntimeCocoa.mm',
             'void WebExtensionAPIRuntime::reload()'),),
    ('scripting', 'getRegisteredContentScripts'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIScriptingCocoa.mm',
             'void WebExtensionAPIScripting::getRegisteredContentScripts(NSDictionary *filter, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIScriptingCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('sidePanel', 'getOptions'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
             'void WebExtensionAPISidePanel::getOptions(NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), serializeSidebarParameters(result.value())));'),),
    ('sidePanel', 'getPanelBehavior'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
             'void WebExtensionAPISidePanel::getPanelBehavior(Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidePanelCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), @{'),),
    ('sidebarAction', 'getPanel'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'void WebExtensionAPISidebarAction::getPanel(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), result.value().panelPath));'),),
    ('sidebarAction', 'getTitle'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'void WebExtensionAPISidebarAction::getTitle(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), result.value()));'),),
    ('sidebarAction', 'isOpen'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'void WebExtensionAPISidebarAction::isOpen(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPISidebarActionCocoa.mm',
             'callback->call(JSValueMakeBoolean(callback->globalContext(), result.value()));'),),
    ('tabs', 'captureVisibleTab'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::captureVisibleTab(WebPageProxyIdentifier webPageProxyIdentifier, double windowID, NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'SUPPRESS_UNCOUNTED_ARG callback->call(JSValueMakeString(callback->globalContext(), toJSString(emptyDataURLValue).get()));'),),
    ('tabs', 'connect'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'RefPtr<WebExtensionAPIPort> WebExtensionAPITabs::connect(WebFrame& frame, JSContextRef context, double tabID, NSDictionary *options, NSString **outExceptionString)'),),
    ('tabs', 'create'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::createTab(WebPageProxyIdentifier webPageProxyIdentifier, NSDictionary *properties, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('tabs', 'detectLanguage'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::detectLanguage(WebPageProxyIdentifier webPageProxyIdentifier, double tabID, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'SUPPRESS_UNCOUNTED_ARG callback->call(JSValueMakeString(callback->globalContext(), toJSString(unknownLanguageValue).get()));'),),
    ('tabs', 'duplicate'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::duplicate(double tabID, NSDictionary *properties, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('tabs', 'get'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::get(double tabID, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('tabs', 'getCurrent'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::getCurrent(WebPageProxyIdentifier webPageProxyIdentifier, Ref<WebExtensionCallbackHandler>&& callback)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('tabs', 'getZoom'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::getZoom(WebPageProxyIdentifier webPageProxyIdentifier, double tabID, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'callback->call(JSValueMakeNumber(callback->globalContext(), result.value()));'),),
    ('tabs', 'move'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::move(NSObject *tabIDs, NSDictionary *properties, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(movedTabs[0])));'),),
    ('tabs', 'query'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::query(WebPageProxyIdentifier webPageProxyIdentifier, NSDictionary *options, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('tabs', 'update'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'void WebExtensionAPITabs::update(WebPageProxyIdentifier webPageProxyIdentifier, double tabID, NSDictionary *properties, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('test', 'assertFalse'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPITest.cpp',
             'void WebExtensionAPITest::assertFalse(JSContextRef context, bool actualValue, const String& message, String& outExceptionString)'),),
    ('test', 'assertTrue'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPITest.cpp',
             'void WebExtensionAPITest::assertTrue(JSContextRef context, bool actualValue, const String& message, String& outExceptionString)'),),
    ('test', 'fail'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPITest.cpp',
             'void WebExtensionAPITest::fail(JSContextRef context, const String& message)'),),
    ('test', 'isProcessingUserGesture'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPITest.cpp',
             'bool WebExtensionAPITest::isProcessingUserGesture()'),
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPITest.cpp',
             'return WebCore::UserGestureIndicator::processingUserGesture();'),),
    ('test', 'notifyFail'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPITest.cpp',
             'void WebExtensionAPITest::notifyFail(JSContextRef context, const String& message)'),),
    ('test', 'notifyPass'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPITest.cpp',
             'void WebExtensionAPITest::notifyPass(JSContextRef context, const String& message)'),),
    ('test', 'succeed'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/WebExtensionAPITest.cpp',
             'void WebExtensionAPITest::succeed(JSContextRef context, const String& message)'),),
    ('webNavigation', 'getAllFrames'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWebNavigationCocoa.mm',
             'void WebExtensionAPIWebNavigation::getAllFrames(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWebNavigationCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('webNavigation', 'getFrame'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWebNavigationCocoa.mm',
             'void WebExtensionAPIWebNavigation::getFrame(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWebNavigationCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('windows', 'create'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'void WebExtensionAPIWindows::createWindow(NSDictionary *data, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('windows', 'get'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'void WebExtensionAPIWindows::get(WebPageProxyIdentifier webPageProxyIdentifier, double windowID, NSDictionary *info, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('windows', 'getAll'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'void WebExtensionAPIWindows::getAll(NSDictionary *info, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('windows', 'getCurrent'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'void WebExtensionAPIWindows::getCurrent(WebPageProxyIdentifier webPageProxyIdentifier, NSDictionary *info, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('windows', 'getLastFocused'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'void WebExtensionAPIWindows::getLastFocused(NSDictionary *info, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
    ('windows', 'update'): (
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'void WebExtensionAPIWindows::update(double windowID, NSDictionary *info, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),
        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIWindowsCocoa.mm',
             'callback->call(toJSValueRef(callback->globalContext(), toWebAPI(result.value())));'),),
}

# Which empty-callback entries fired this run, so their citations get checked.
EMPTY_CALLBACK_USED = set()
PARAMETER_TYPES_USED = set()
DICTIONARY_CORRECTIONS_USED = set()


def check_parse_coverage():
    """Fails the build on any IDL line no parse rule accounted for.

    A member the parser does not understand is otherwise dropped in silence, and
    only shows up as a missing declaration nobody is looking for.
    """
    errors = []
    for path, record in sorted(PARSE_COVERAGE.items()):
        for number, line in enumerate(record['lines'], start=1):
            if number in record['consumed']:
                continue
            if any(p.match(line) for p in IGNORABLE_IDL):
                continue
            errors.append(f'{path}:{number}: {line.strip()}')
    if errors:
        raise ReconciliationError(
            'IDL the parser does not account for. Every line must produce a '
            'member or match an ignorable pattern, so upstream syntax changes '
            'fail loudly instead of dropping declarations:\n  '
            + '\n  '.join(errors))
    return sum(len(r['consumed']) for r in PARSE_COVERAGE.values())


def resolve_algorithmic_param_type(ns_name, op_name, arg_name, raw_type, available_dicts):
    """
    Algorithmic parameter type resolver that dynamically matches method parameters
    to WebIDL dictionaries based on naming conventions and WebIDL AST structure.
    """
    read = PARAMETER_TYPES.get((ns_name, op_name, arg_name))
    if read:
        PARAM_DERIVATIONS[(ns_name, op_name, arg_name)] = 'read'
        PARAMETER_TYPES_USED.add((ns_name, op_name, arg_name))
        return read[0]

    # 1. Structural multi-target identifiers
    if arg_name in ('tabIDs', 'idOrIdList'):
        PARAM_DERIVATIONS[(ns_name, op_name, arg_name)] = 'special-case'
        return 'number | number[]' if 'tab' in arg_name.lower() else 'string | string[]'
    if ns_name == 'menus' and arg_name in ('identifier', 'id'):
        PARAM_DERIVATIONS[(ns_name, op_name, arg_name)] = 'special-case'
        return 'number | string'
    if arg_name == 'target' and ns_name == 'runtime':
        PARAM_DERIVATIONS[(ns_name, op_name, arg_name)] = 'special-case'
        return 'browser.MessageSender | globalThis.Window'
    if arg_name == 'substitutions' and ns_name == 'i18n':
        PARAM_DERIVATIONS[(ns_name, op_name, arg_name)] = 'special-case'
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
        PARAM_DERIVATIONS[(ns_name, op_name, arg_name)] = 'special-case'
        return 'browser.RegisteredContentScript[]'

    # The candidate search below only makes sense where the IDL declines to say
    # what the argument is: `any`, or an object. Where the IDL states a type,
    # that IS the derivation and guessing over it is how `enable(double tabId)`
    # shipped as ActionDetails and `notifyFail(DOMString message)` as
    # MessageOptions.
    declared = clean_type(raw_type)
    if declared not in ('unknown', 'Record<string, unknown>'):
        PARAM_DERIVATIONS[(ns_name, op_name, arg_name)] = 'idl-type'
        return declared

    # Check candidates against available dictionaries. The dictionary exists,
    # but nothing establishes that this argument is the one it describes: the
    # match is on spelling. That is the mechanism POSTMORTEM-algorithmic-return-
    # types.md is about, applied to arguments, so every hit is recorded.
    for c in candidates:
        if c in available_dicts or f"WebExtension{c}" in available_dicts:
            PARAM_DERIVATIONS[(ns_name, op_name, arg_name)] = 'candidate-name'
            return f"browser.{c}"

    cleaned = clean_type(raw_type)
    if cleaned == 'unknown' and arg_name in ('details', 'info', 'options', 'properties'):
        PARAM_DERIVATIONS[(ns_name, op_name, arg_name)] = 'widened'
        return 'Record<string, unknown>'
    PARAM_DERIVATIONS[(ns_name, op_name, arg_name)] = 'idl-type'
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
        # register/update/unregister call back empty and are recorded as such;
        # this one hands back toWebAPI of the stored scripts.
        if op_name == 'getRegisteredContentScripts':
            return 'browser.RegisteredContentScript[]'
    if ns_name == 'cookies' and op_name == 'getAllCookieStores':
        return 'browser.CookieStore[]'
    # get, set and remove all resolve Expected<std::optional<
    # WebExtensionCookieParameters>> and hand back toWebAPI of it, so set and
    # remove return the cookie rather than nothing. Note remove yields the
    # whole cookie, not Chrome's url/name/storeId subset.
    if ns_name == 'cookies' and op_name in ('set', 'remove'):
        return 'browser.Cookie | null'
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
    if (ns_name, op_name) in CONFIRMED_EMPTY_CALLBACKS:
        EMPTY_CALLBACK_USED.add((ns_name, op_name))
        return 'void'
    # TabsMove resolves a Vector and unwraps it: one tab moved comes back as
    # the tab, more than one as the array. The generic move rule returns the
    # single form only.
    if ns_name == 'tabs' and op_name == 'move':
        return 'browser.Tab | browser.Tab[]'
    # bookmarks.get takes an id or a list of them and calls back with an array
    # either way. The generic get rule below returns a single entity.
    if ns_name == 'bookmarks' and op_name == 'get':
        return 'browser.BookmarkTreeNode[]'
    # windows.get, getCurrent and update resolve a plain WebExtensionWindowParameters
    # and are covered by the verb rules below. getLastFocused matches no verb rule,
    # so without this it falls through to void and drops a window it does deliver.
    if ns_name == 'windows' and op_name == 'getLastFocused':
        return 'browser.Window'
    if ns_name == 'webNavigation':
        # getFrame resolves an optional, so it can come back empty. getAllFrames
        # maps a Vector and always yields an array.
        if op_name == 'getFrame':
            return 'browser.FrameDetails | null'
        if op_name == 'getAllFrames':
            return 'browser.FrameDetails[]'

    # Booleans. The startswith('is')/startswith('has') gate these used to sit
    # behind decided nothing: every branch is an exact match, so the prefix test
    # only obscured that. Removing it left the output identical.
    if op_name in ('contains', 'request', 'remove') and ns_name == 'permissions':
        return 'boolean'
    if op_name in ('clear', 'clearAll') and ns_name == 'alarms':
        return 'boolean'
    if (ns_name, op_name) in (('extension', 'isAllowedIncognitoAccess'),
                              ('extension', 'isAllowedFileSchemeAccess'),
                              ('offscreen', 'hasDocument'),
                              ('action', 'isEnabled'),
                              ('sidebarAction', 'isOpen')):
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

    # No rule matched. None means unresolved, which is not the same as a rule
    # deciding the callback takes nothing: windows.getLastFocused reached here
    # and shipped as void while WebKit was calling back with a window.
    return None


def resolve_return_type(ns_name, op_name, available_dicts):
    """The callback payload, and whether anything actually decided it.

    Returns (type, derivation). `unresolved` marks an operation that matched no
    rule and is being declared void on no evidence. Those are the ones to read
    the implementation for; see POSTMORTEM-algorithmic-return-types.md.
    """
    resolved = resolve_algorithmic_return_type(ns_name, op_name, available_dicts)
    if resolved is None:
        return 'void', 'unresolved'
    return resolved, 'verb-rule'


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

    for idl_type, (payload, _cites) in EVENT_PAYLOADS.items():
        if idl_type in a_type:
            return [f'export const {a_name}: {payload};'], f'event-payload:{idl_type}'
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
    derivation = 'operation-signature'

    cb_arg = next((a for a in op['args'] if a['callback'] or 'callback' in a['name'].lower()), None)
    non_cb_args = [a for a in op['args'] if a is not cb_arg]

    # True optional leading check: if first argument is optional, allow omitting it
    has_leading_optional = len(non_cb_args) >= 2 and non_cb_args[0]['optional']

    if cb_arg and op_ret == 'void':
        cb_payload_type, how = resolve_return_type(ns_name, op_name, available_dicts)
        if how == 'unresolved':
            derivation = 'operation-signature:unresolved-payload'

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

    if ns_name not in READ_NAMESPACES and derivation == 'operation-signature':
        derivation = 'operation-signature:unread-namespace'
    return lines, derivation


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
        self.absent_interfaces = set()

    def declare(self, iface, kind, name):
        """Registers a parsed member that emission is expected to account for."""
        self.declared.setdefault((iface, name), kind)

    def record_absent_interface(self, iface):
        """A KNOWN_IDL_FILES entry absent at this revision is recorded as
        absent-at-ref and never parsed; the revision does not declare it.
        """
        self.absent_interfaces.add(iface)
        self.record(iface, iface, 'interface', 'absent-at-ref', [])

    def absent_namespaces(self):
        """Root namespaces whose interface is absent at this revision;
        evidence tables keyed by namespace skip them."""
        return {ROOT_NAMESPACES[iface] for iface in self.absent_interfaces
                if iface in ROOT_NAMESPACES}

    def record(self, iface, member, kind, origin, lines, cites=(), declaration=None):
        resolved = []
        for cite in cites:
            if cite is DECLARATION:
                if not declaration:
                    raise CitationError(
                        f'{iface}.{member} cites its own IDL declaration, but the '
                        f'parser recorded no source span for it.'
                    )
                # Quote the whole statement including its terminator, so a
                # declaration that is a prefix of another (onConnect inside
                # onConnectExternal) does not read as ambiguous.
                cite = Cite(declaration['path'], declaration['quote'] + ';')
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

    def unresolved_payloads(self):
        return {f'{ROOT_NAMESPACES.get(m["interface"], m["interface"])}.{m["member"]}'
                for m in self.members
                if m['origin'] == 'operation-signature:unresolved-payload'}

    def unverified_returns(self):
        return {f'{ROOT_NAMESPACES.get(m["interface"], m["interface"])}.{m["member"]}'
                for m in self.members
                if m['origin'] == 'operation-signature:unread-namespace'}

    def candidate_named_parameters(self):
        return {f'{ns}.{op}({arg})'
                for (ns, op, arg), how in PARAM_DERIVATIONS.items()
                if how == 'candidate-name'}

    def check_ratchet(self, baseline_path, actual, subject, fix):
        """Two-sided reconciliation of a shrinking list.

        A name not in the file fails, so the class cannot grow. A name in the
        file that no longer qualifies also fails, so the list cannot drift out
        of date. Names leave by doing the work, never by editing the file.
        """
        recorded = {line.split('#')[0].strip()
                    for line in baseline_path.read_text().splitlines()}
        recorded.discard('')

        errors = []
        for name in sorted(actual - recorded):
            errors.append(f'{name} {subject} and is not in {baseline_path.name}. {fix}')
        for name in sorted(recorded - actual):
            errors.append(
                f'{name} is listed in {baseline_path.name} and no longer '
                f'qualifies. If a reading of the implementation moved it, delete '
                f'the line. If a new rule moved it, that rule is an unchecked '
                f'guess and deleting this line launders it.')
        if errors:
            raise ReconciliationError(
                f'{baseline_path.name} does not match what was generated:\n  '
                + '\n  '.join(errors))
        return len(actual)

    def check_read_namespaces_are_read(self):
        """A namespace counts as read only if every operation carries evidence.

        READ_NAMESPACES had been a set of names meaning "somebody looked". Now
        each name is a claim the build checks: every operation in it must be in
        CONFIRMED_EMPTY_CALLBACKS or RETURN_EVIDENCE, and no operation may be in
        both.
        """
        errors = []
        by_ns = {}
        for m in self.members:
            if m['kind'] == 'operation' and m['origin'].startswith('operation-signature'):
                ns = ROOT_NAMESPACES.get(m['interface'], m['interface'])
                by_ns.setdefault(ns, set()).add(m['member'])
        for ns in sorted(READ_NAMESPACES):
            for op in sorted(by_ns.get(ns, ())):
                in_empty = (ns, op) in CONFIRMED_EMPTY_CALLBACKS
                in_ret = (ns, op) in RETURN_EVIDENCE
                if in_empty and in_ret:
                    errors.append(f'{ns}.{op} is in both CONFIRMED_EMPTY_CALLBACKS '
                                  f'and RETURN_EVIDENCE; it cannot be both.')
                elif not in_empty and not in_ret:
                    errors.append(f'{ns}.{op}: {ns} is in READ_NAMESPACES but this '
                                  f'operation carries no return-side evidence. Cite '
                                  f'its callback->call or its signature, or take '
                                  f'{ns} out of READ_NAMESPACES.')
        # RETURN_EVIDENCE is checked against what the main ref declares, not
        # against what was emitted.
        declared_by_ns = {}
        for (iface, member), kind in self.declared.items():
            if kind == 'operation':
                ns = ROOT_NAMESPACES.get(iface, iface)
                declared_by_ns.setdefault(ns, set()).add(member)
        absent = self.absent_namespaces()
        for (ns, op) in sorted(RETURN_EVIDENCE):
            if ns in absent:
                continue
            if op not in declared_by_ns.get(ns, ()):
                errors.append(f'RETURN_EVIDENCE names {ns}.{op}, which the IDL does '
                              f'not declare as an operation.')
        if errors:
            raise ReconciliationError(
                'READ_NAMESPACES does not match its evidence:\n  ' + '\n  '.join(errors))
        return len(RETURN_EVIDENCE)

    def check_unresolved(self, baseline_path):
        """Two-sided reconciliation of the operations declared void on no evidence.

        The file is a ratchet. A new entry means a guess just entered the output
        and fails the build; a stale entry means one was resolved and the file
        was not updated, which also fails, so the list cannot quietly drift.
        Entries leave it by reading the implementation, never by editing it to
        make this pass.
        """
        actual = self.unresolved_payloads()
        recorded = {line.split('#')[0].strip()
                    for line in baseline_path.read_text().splitlines()}
        recorded.discard('')

        errors = []
        for name in sorted(actual - recorded):
            errors.append(
                f'{name} is declared void because no rule matched it, and it is '
                f'not in {baseline_path.name}. Read the operation in WebKit and '
                f'declare what it calls back with.'
            )
        for name in sorted(recorded - actual):
            errors.append(
                f'{name} is listed in {baseline_path.name} and is no longer '
                f'unresolved. If a reading moved it, delete the line. If a new '
                f'rule moved it, that rule is an unchecked guess and deleting '
                f'this line launders it.'
            )
        if errors:
            raise ReconciliationError(
                'unresolved callback payloads do not match the recorded list:\n  '
                + '\n  '.join(errors)
            )
        return len(actual)

    def check(self):
        errors = []
        absent_namespaces = self.absent_namespaces()

        unused = sorted(set(SIGNATURE_OVERRIDES) - self.used_overrides)
        for iface, member in unused:
            if iface in self.absent_interfaces:
                continue
            errors.append(
                f'SIGNATURE_OVERRIDES[{iface!r}, {member!r}] matched no parsed member. '
                f'WebKit does not declare it at this revision, or the interface is skipped.'
            )

        for key in sorted(set(DICTIONARY_MEMBER_CORRECTIONS) - DICTIONARY_CORRECTIONS_USED):
            errors.append(
                f'DICTIONARY_MEMBER_CORRECTIONS[{key[0]!r}, {key[1]!r}] matched no '
                f'parsed dictionary member. It can correct a member WebKit declares, '
                f'never add one.'
            )

        unused_skips = sorted(set(MEMBER_SKIPS) - self.used_skips)
        for iface, member in unused_skips:
            if iface in self.absent_interfaces:
                continue
            errors.append(
                f'MEMBER_SKIPS[{iface!r}, {member!r}] matched no parsed member. '
                f'The reason it records no longer applies to anything.'
            )

        unused_empty = sorted(set(CONFIRMED_EMPTY_CALLBACKS) - EMPTY_CALLBACK_USED)
        for ns_name, op_name in unused_empty:
            if ns_name in absent_namespaces:
                continue
            errors.append(
                f'CONFIRMED_EMPTY_CALLBACKS[{ns_name!r}, {op_name!r}] matched no '
                f'operation. The operation was removed or renamed and this entry '
                f'no longer describes anything.'
            )

        unused_params = sorted(set(PARAMETER_TYPES) - PARAMETER_TYPES_USED)
        for ns_name, op_name, arg_name in unused_params:
            if ns_name in absent_namespaces:
                continue
            errors.append(
                f'PARAMETER_TYPES[{ns_name!r}, {op_name!r}, {arg_name!r}] matched '
                f'no parameter. The operation was removed or renamed and this '
                f'entry no longer describes anything.'
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


def verify_citations(reconciler, resolver, ship_resolver):
    """Re-resolves every citation against the revision being generated from.

    Covers the recorded members and the empty-callback table, which would
    otherwise be an attestation: an entry saying an operation calls back with
    nothing, backed by nobody having checked. 'mv3-removed' citations quote
    the gate text read at the ship ref (see read_mv3_gates), so those alone
    are re-resolved against ship_resolver instead of the main ref.
    """
    checked = 0
    absent_namespaces = reconciler.absent_namespaces()
    for (ns_name, op_name, arg_name) in sorted(PARAMETER_TYPES_USED):
        _type, cites = PARAMETER_TYPES[(ns_name, op_name, arg_name)]
        for position, cite in enumerate(cites):
            text = resolver.read(cite.path)
            normalized, _ = normalized_with_lines(text)
            hits = normalized.count(norm_ws(cite.quote))
            if hits == 0:
                raise CitationError(
                    f'{ns_name}.{op_name}({arg_name}) cites text no longer in '
                    f'{cite.path} at {resolver.describe()}:\n    {cite.quote}')
            if position == 0 and hits > 1:
                raise CitationError(
                    f'{ns_name}.{op_name}({arg_name}): the identifying citation '
                    f'occurs {hits} times in {cite.path}, so it does not identify '
                    f'this operation:\n    {cite.quote}')
            checked += 1
    for (ns_name, op_name), cites in sorted(RETURN_EVIDENCE.items()):
        if ns_name in absent_namespaces:
            # Nothing was emitted for an absent namespace, so its citations
            # are not resolved at this revision.
            continue
        for position, cite in enumerate(cites):
            text = resolver.read(cite.path)
            normalized, _ = normalized_with_lines(text)
            hits = normalized.count(norm_ws(cite.quote))
            if hits == 0:
                raise CitationError(
                    f'{ns_name}.{op_name} return evidence is no longer in '
                    f'{cite.path} at {resolver.describe()}:\n    {cite.quote}')
            if position == 0 and hits > 1:
                raise CitationError(
                    f'{ns_name}.{op_name}: identifying return citation occurs '
                    f'{hits} times in {cite.path}:\n    {cite.quote}')
            checked += 1
    for (ns_name, op_name) in sorted(EMPTY_CALLBACK_USED):
        cite = CONFIRMED_EMPTY_CALLBACKS[(ns_name, op_name)]
        text = resolver.read(cite.path)
        normalized, line_of = normalized_with_lines(text)
        needle = norm_ws(cite.quote)
        hits = normalized.count(needle)
        if hits == 0:
            raise CitationError(
                f'{ns_name}.{op_name} is recorded as calling back with no '
                f'argument, and the line proving it is no longer in '
                f'{cite.path} at {resolver.describe()}:\n    {cite.quote}')
        if hits > 1:
            raise CitationError(
                f'{ns_name}.{op_name} cites text occurring {hits} times in '
                f'{cite.path}, so it does not identify this operation. Extend '
                f'the quote until it is unique:\n    {cite.quote}')
        checked += 1
    for entry in reconciler.members:
        entry_resolver = ship_resolver if entry['origin'] == 'mv3-removed' else resolver
        for cite in entry['citations']:
            text = entry_resolver.read(cite['path'])
            normalized, line_of = normalized_with_lines(text)
            needle = norm_ws(cite['quote'])
            index = normalized.find(needle)
            if cite.get('absent'):
                if index >= 0:
                    raise CitationError(
                        f"{entry['interface']}.{entry['member']}: the declaration rests "
                        f"on {cite['quote']!r} being absent from {cite['path']}, but it "
                        f"appears there at {entry_resolver.describe()} on line {line_of[index]}."
                    )
            elif index < 0:
                raise CitationError(
                    f"{entry['interface']}.{entry['member']}: cited text is not present "
                    f"in {cite['path']} at {entry_resolver.describe()}:\n    {cite['quote']}"
                )
            elif normalized.count(needle) > 1:
                raise CitationError(
                    f"{entry['interface']}.{entry['member']}: cited text occurs "
                    f"{normalized.count(needle)} times in {cite['path']}, so it does "
                    f"not identify what it cites. Extend the quote until it is "
                    f"unique:\n    {cite['quote']}"
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


def emit_interface_members(out, sub, iface_data, reconciler, spaces, ship_facts):
    """Emits a sub-interface body. Members come from the override table only."""
    for kind, member in interface_members(iface_data):
        if not sub.covers(member['name']):
            continue
        key = (sub.iface, member['name'])
        override = SIGNATURE_OVERRIDES.get(key)
        if override:
            reconciler.used_overrides.add(key)
            if ship_facts.declares_member(sub.iface, kind, member['name']):
                out.extend(indent(override.lines(), spaces))
                reconciler.record(sub.iface, member['name'], kind, 'override',
                                  override.sig, override.cites, member.get('declaration'))
            else:
                reconciler.record(sub.iface, member['name'], kind, 'unshipped', [])
        elif key in MEMBER_SKIPS:
            reconciler.used_skips.add(key)
            reconciler.record(sub.iface, member['name'], kind, 'skipped', [],
                              declaration=member.get('declaration'))


def emit_namespace_members(out, iface_name, iface_data, ns_name, reconciler, available_dicts,
                            mv3_removed, ship_facts):
    """`mv3_removed` is (path, {op_name: verbatim gate text}) for this
    interface's isPropertyAllowed, or None. An operation named there is
    hidden from every MV3 extension and is skipped, citing the gate that
    hides it.

    Emission is gated on ship_facts. An override or MEMBER_SKIPS entry still
    counts as used against the main ref.
    """
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
        if ship_facts.declares_member(iface_name, 'constant', c['name']):
            out.extend(indent(lines, 8))
            reconciler.record(iface_name, c['name'], 'constant', origin, lines, cites,
                              c.get('declaration'))
        else:
            reconciler.record(iface_name, c['name'], 'constant', 'unshipped', [])

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
        elif (iface_name, attr['name']) in ATTRIBUTE_PAYLOADS:
            payload, extra = ATTRIBUTE_PAYLOADS[(iface_name, attr['name'])]
            lines = [f'export const {attr["name"]}: {payload};']
            origin, cites = 'attribute-payload', (DECLARATION,) + extra
        else:
            lines, origin = derive_attribute_lines(ns_name, attr)
            cites = (DECLARATION,)
            if origin.startswith('event-payload:'):
                cites += EVENT_PAYLOADS[origin.split(':', 1)[1]][1]
        if ship_facts.declares_member(iface_name, 'attribute', attr['name']):
            out.extend(indent(lines, 8))
            reconciler.record(iface_name, attr['name'], 'attribute', origin, lines, cites,
                              attr.get('declaration'))
        else:
            reconciler.record(iface_name, attr['name'], 'attribute', 'unshipped', [])

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
        elif mv3_removed and op['name'] in mv3_removed[1]:
            gate_path, gates = mv3_removed
            reconciler.record(iface_name, op['name'], 'operation', 'mv3-removed', [],
                              cites=(Cite(gate_path, gates[op['name']]),),
                              declaration=op.get('declaration'))
            continue
        else:
            lines, origin = derive_operation_lines(ns_name, op, available_dicts)
            cites = (DECLARATION,)
        if ship_facts.declares_member(iface_name, 'operation', op['name']):
            out.extend(indent(lines, 8))
            reconciler.record(iface_name, op['name'], 'operation', origin, lines, cites,
                              op.get('declaration'))
        else:
            reconciler.record(iface_name, op['name'], 'operation', 'unshipped', [])


class ShipFacts:
    """Existence facts read from the WebKit tag of the last shipped Safari.

    Shapes and evidence still come from --ref; this only answers whether a
    name is declared at all. `ifaces` maps an interface name to its parsed
    attribute/operation/constant name sets; `dicts` and `enums` map a
    dictionary or enum name to its parsed member/value name set.
    """

    def __init__(self, ref, sha, version, ifaces, dicts, enums):
        self.ref = ref
        self.sha = sha
        self.version = version
        self.ifaces = ifaces
        self.dicts = dicts
        self.enums = enums

    def declares_interface(self, iface_name):
        return iface_name in self.ifaces

    def declares_member(self, iface_name, kind, member_name):
        members = self.ifaces.get(iface_name)
        return members is not None and member_name in members[kind + 's']

    def declares_dict(self, dict_name):
        return dict_name in self.dicts

    def declares_dict_member(self, dict_name, member_name):
        members = self.dicts.get(dict_name)
        return members is not None and member_name in members

    def declares_enum(self, enum_name):
        return enum_name in self.enums

    def declares_enum_value(self, enum_name, value):
        values = self.enums.get(enum_name)
        return values is not None and value in values


def compute_ship_facts(resolver, ref, sha, version) -> ShipFacts:
    """Parses the ship ref's IDL the same way the main ref is parsed, and
    keeps only the name sets emission needs to answer "does this exist".

    Reuses check_idl_file_list, so an IDL file the ship ref has and
    KNOWN_IDL_FILES does not is fatal the same way it is for the main ref. A
    KNOWN_IDL_FILES entry the ship ref lacks means the whole interface is
    unshipped, not fetched or parsed.
    """
    listed, absent = check_idl_file_list(resolver)
    if absent:
        print(f"Ship interface file list matches {resolver.describe()} ({listed} files); "
              f"{len(absent)} known file(s) unshipped at this revision: "
              f"{', '.join(absent)}.")
    else:
        print(f"Ship interface file list matches {resolver.describe()} ({listed} files).")

    ifaces, dicts, enums = {}, {}, {}
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        fetch_upstream_idls(tmp_path, resolver, absent=absent)
        for p in sorted(tmp_path.glob('*.idl')):
            e, d, i = parse_idl_file(p)
            enums.update(e)
            dicts.update(d)
            ifaces.update(i)

    ship_ifaces = {
        name: {
            'attributes': {a['name'] for a in data['attributes']},
            'operations': {o['name'] for o in data['operations']},
            'constants': {c['name'] for c in data['constants']},
        }
        for name, data in ifaces.items()
    }
    ship_dicts = {name: set(data['members']) for name, data in dicts.items()}
    ship_enums = {name: set(values) for name, values in enums.items()}
    return ShipFacts(ref, sha, version, ship_ifaces, ship_dicts, ship_enums)


def generate_dts(idl_dir: pathlib.Path, reconciler: 'Reconciler', source: str,
                  gate_resolver: 'SourceResolver', ship_facts: 'ShipFacts') -> str:
    PARAM_DERIVATIONS.clear()
    EMPTY_CALLBACK_USED.clear()
    PARAMETER_TYPES_USED.clear()
    DICTIONARY_CORRECTIONS_USED.clear()
    PARSE_COVERAGE.clear()
    all_enums = {}
    all_dicts = {}
    all_ifaces = {}

    # Reads the first candidate path that exists; none existing is fatal.
    # Gates are read at the ship ref.
    def read_mv3_gates(paths):
        errors = []
        for path in paths:
            try:
                text = gate_resolver.read(path)
            except CitationError as e:
                errors.append(str(e))
                continue
            removed = derive_mv3_removed_names(text)
            if 'supportsManifestVersion(3)' in text and not removed:
                raise ReconciliationError(
                    f'{path} still guards on supportsManifestVersion(3) but '
                    f'derive_mv3_removed_names matched nothing in it.')
            return path, removed
        raise CitationError(
            'none of the candidate paths for this gate exist at '
            f'{gate_resolver.describe()}:\n  ' + '\n  '.join(errors))

    mv3_namespace_path, mv3_namespace_removed = read_mv3_gates(NAMESPACE_GATE_PATHS)
    mv3_removed_by_iface = {
        'WebExtensionAPITabs': read_mv3_gates((TABS_COCOA,)),
        'WebExtensionAPIExtension': read_mv3_gates((EXTENSION_COCOA,)),
    }

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
        emitted = []
        for sub in entries:
            if sub.iface not in all_ifaces:
                raise ReconciliationError(
                    f'{sub.iface} is declared as a sub-interface but no parsed IDL '
                    f'file contains it at this revision.'
                )
            # Members are recorded even for an unshipped interface, so every
            # main-ref member has a provenance entry.
            body = []
            emit_interface_members(body, sub, all_ifaces[sub.iface],
                                   reconciler, member_indent, ship_facts)
            if not ship_facts.declares_interface(sub.iface):
                reconciler.record(sub.iface, sub.iface, 'interface', 'unshipped', [])
                continue
            emitted.append(sub)
            lines.append(f'{" " * body_indent}{sub.decl} {{')
            lines.extend(body)
            lines.append(f'{" " * body_indent}}}')
        if group_name:
            lines.append('    }')
        for sub in emitted:
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

    # Enums from WebIDL. Undeclared at the ship ref keeps main's declaration,
    # recorded shape-from-main; declared there loses the values it lacks.
    dropped_enums = []
    for enum_name, values in sorted(all_enums.items()):
        short_name = enum_name[12:] if enum_name.startswith('WebExtension') else enum_name
        if not ship_facts.declares_enum(enum_name):
            reconciler.record(enum_name, enum_name, 'enum', 'shape-from-main', [])
            kept = values
        else:
            kept = [v for v in values if ship_facts.declares_enum_value(enum_name, v)]
            for v in values:
                if v not in kept:
                    reconciler.record(enum_name, v, 'enum-value', 'unshipped', [])
            if not kept:
                dropped_enums.append(short_name)
                reconciler.record(enum_name, enum_name, 'enum', 'unshipped', [])
                continue
        val_str = ' | '.join(f'"{v}"' for v in kept)
        lines.append(f'    export type {short_name} = {val_str};')
    lines.append('')

    # Dictionaries from WebIDL. Undeclared at the ship ref keeps main's
    # declaration, recorded shape-from-main; declared there loses the members
    # it lacks; a dictionary with no shipped member is dropped.
    dropped_dicts = []
    for dict_name, dict_data in sorted(all_dicts.items()):
        short_name = dict_name[12:] if dict_name.startswith('WebExtension') else dict_name
        ship_has_dict = ship_facts.declares_dict(dict_name)
        if not ship_has_dict:
            reconciler.record(dict_name, dict_name, 'dictionary', 'shape-from-main', [])
        elif dict_data['members'] and not any(
                ship_facts.declares_dict_member(dict_name, m) for m in dict_data['members']):
            for m_name in sorted(dict_data['members']):
                reconciler.record(dict_name, m_name, 'dictionary-member', 'unshipped', [])
            dropped_dicts.append(short_name)
            reconciler.record(dict_name, dict_name, 'dictionary', 'unshipped', [])
            continue
        parent = dict_data['parent']
        parent_str = f' extends {clean_type(parent)}' if parent else ''
        lines.append(f'    export interface {short_name}{parent_str} {{')
        for m_name, m_info in sorted(dict_data['members'].items()):
            if ship_has_dict and not ship_facts.declares_dict_member(dict_name, m_name):
                reconciler.record(dict_name, m_name, 'dictionary-member', 'unshipped', [])
                continue
            corrected = DICTIONARY_MEMBER_CORRECTIONS.get((dict_name, m_name))
            if corrected:
                DICTIONARY_CORRECTIONS_USED.add((dict_name, m_name))
                lines.append(f'        {corrected[0]}')
                reconciler.record(short_name, m_name, 'dictionary-member',
                                  'corrected', [corrected[0]], corrected[1])
                continue
            opt = '' if m_info['required'] else '?'
            m_type = clean_type(m_info['type'])
            lines.append(f'        {m_name}{opt}: {m_type};')
        lines.append('    }')
        lines.append('')

    for group in SUB_INTERFACE_GROUPS[1:]:
        emit_group(*group)

    # Root Namespaces
    # Members are recorded even for an unshipped interface, so every main-ref
    # member has a provenance entry.
    emitted_namespaces = set()
    for iface_name, iface_data in sorted(all_ifaces.items()):
        if iface_name not in ROOT_NAMESPACES:
            continue

        ns_name = ROOT_NAMESPACES[iface_name]
        body = []
        emit_namespace_members(body, iface_name, iface_data, ns_name, reconciler,
                               dict_short_names,
                               mv3_removed_by_iface.get(iface_name), ship_facts)
        if not ship_facts.declares_interface(iface_name):
            reconciler.record(iface_name, iface_name, 'interface', 'unshipped', [])
            continue

        emitted_namespaces.add(ns_name)
        lines.append(f'    export namespace {ns_name} {{')
        lines.extend(body)
        lines.append('    }')
        lines.append('')

    lines.append('}')
    lines.append('')

    # Skips a name mv3_namespace_removed hides; see "Manifest V3 gates" above.
    lines.append('declare namespace chrome {')
    for chrome_name, target in CHROME_NAMESPACE_ALIASES:
        if chrome_name in mv3_namespace_removed:
            reconciler.record('WebExtensionAPINamespace', chrome_name, 'attribute',
                              'mv3-removed', [],
                              cites=(Cite(mv3_namespace_path,
                                          mv3_namespace_removed[chrome_name]),))
            continue
        # An alias to a namespace that was not emitted would import nothing.
        if target.split('.', 1)[1] not in emitted_namespaces:
            reconciler.record('WebExtensionAPINamespace', chrome_name, 'attribute',
                              'absent-at-ref', [])
            continue
        lines.append(f'    export import {chrome_name} = {target};')
    lines.append('}')
    lines.append('')

    content = '\n'.join(lines)

    # A dropped enum or dictionary must not be referenced as browser.<Name> by
    # anything emitted. Qualified sub-interface references
    # (browser.runtime.Port) are caught by npm test.
    dangling = [name for name in dropped_enums + dropped_dicts
                if re.search(rf'\bbrowser\.{re.escape(name)}\b', content)]
    if dangling:
        raise ReconciliationError(
            'the ship ref leaves nothing to emit for ' + ', '.join(sorted(dangling)) +
            ', but an emitted declaration still references it as browser.<Name>.')

    return content


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


def check_idl_file_list(resolver: SourceResolver):
    """Reconciles KNOWN_IDL_FILES against what the revision actually holds.

    Everything downstream reconciles the interfaces inside the files we fetch.
    Without this, a new WebExtensionAPIFoo.idl upstream is not a missing
    interface, it is a namespace nothing ever looks for.

    A file the revision has that the list lacks is fatal. A file the list has
    that the revision lacks is returned for the caller to record.
    """
    actual = resolver.list_idl_files()
    known = set(KNOWN_IDL_FILES)

    errors = []
    for name in sorted(actual - known):
        errors.append(f'{name} exists at {resolver.describe()} and is not in '
                      f'KNOWN_IDL_FILES, so nothing reads it.')
    if errors:
        raise ReconciliationError(
            'the interface file list does not match the revision:\n  '
            + '\n  '.join(errors))
    return len(actual), sorted(known - actual)


def fetch_upstream_idls(target_dir: pathlib.Path, resolver: SourceResolver, absent=()):
    """Writes every known IDL file out of the resolver. Fails fast on error.

    `absent` lists files check_idl_file_list found missing; they are not
    fetched.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    idl_files = sorted(set(KNOWN_IDL_FILES) - set(absent))

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


# The WebKit tag of the last shipped Safari. --ref supplies shapes and
# evidence; this supplies existence. A member --ref declares but this tag does
# not is left out of the output.
SHIP_REF = 'WebKit-7624.1.16'
SHIP_VERSION = '26.4'


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
        '--ship-ref',
        default=None,
        help=f'WebKit ref of the last shipped Safari, read for existence only '
             f'(default: {SHIP_REF}). Required together with --ship-version.'
    )
    parser.add_argument(
        '--ship-version',
        default=None,
        help=f'Safari version --ship-ref belongs to, recorded in provenance.json '
             f'(default: {SHIP_VERSION}). Required together with --ship-ref.'
    )
    parser.add_argument(
        '--cache-dir',
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent.parent / '.idls-cache',
        help='Directory to cache fetched WebKit sources in'
    )
    parser.add_argument(
        '--unresolved-payloads',
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent.parent / 'unresolved-payloads.txt',
        help='Ratchet file listing operations declared void with no rule behind it'
    )
    parser.add_argument(
        '--unverified-parameters',
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent.parent / 'unverified-parameters.txt',
        help='Ratchet file listing parameters typed by candidate-name matching'
    )
    parser.add_argument(
        '--unverified-returns',
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent.parent / 'unverified-returns.txt',
        help='Ratchet file listing operations in namespaces whose implementation is unread'
    )
    parser.add_argument(
        '--provenance',
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent.parent / 'provenance.json',
        help='Where to write the record of where every declaration came from'
    )
    parser.add_argument(
        '--output', '-o',
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent.parent / 'index.d.ts',
        help='Output path for emitted .d.ts file (default: index.d.ts)'
    )

    args = parser.parse_args()

    if bool(args.ship_ref) != bool(args.ship_version):
        parser.error('--ship-ref and --ship-version must be given together')
    if args.ship_ref is None:
        args.ship_ref, args.ship_version = SHIP_REF, SHIP_VERSION

    if args.pr:
        args.repo, args.ref = resolve_pr_head(args.pr, args.repo)

    resolver = build_resolver(args)
    resolved = resolver.resolve_ref()
    if resolved and resolved != args.ref:
        print(f"Resolved {args.ref} to {resolved}.")
    if resolved:
        args.ref = resolved
        resolver = build_resolver(args)

    ship_ref = args.ship_ref
    ship_args = argparse.Namespace(**vars(args))
    ship_args.ref = args.ship_ref
    ship_resolver = build_resolver(ship_args)
    ship_resolved = ship_resolver.resolve_ref()
    if ship_resolved and ship_resolved != ship_args.ref:
        print(f"Resolved ship ref {ship_args.ref} to {ship_resolved}.")
    if ship_resolved:
        ship_args.ref = ship_resolved
        ship_resolver = build_resolver(ship_args)
    ship_sha = ship_args.ref

    reconciler = Reconciler()

    listed, absent_idl_files = check_idl_file_list(resolver)
    if absent_idl_files:
        print(f"Interface file list matches {resolver.describe()} ({listed} files); "
              f"{len(absent_idl_files)} known file(s) absent at this revision: "
              f"{', '.join(absent_idl_files)}.")
        for name in absent_idl_files:
            reconciler.record_absent_interface(name[:-len('.idl')])
    else:
        print(f"Interface file list matches {resolver.describe()} ({listed} files).")

    ship_facts = compute_ship_facts(ship_resolver, ship_ref, ship_sha, args.ship_version)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        fetch_upstream_idls(tmp_path, resolver, absent=absent_idl_files)
        dts_content = generate_dts(tmp_path, reconciler, f'{args.repo}@{args.ref}',
                                   ship_resolver, ship_facts)

    reconciler.check()
    evidenced = reconciler.check_read_namespaces_are_read()
    covered = check_parse_coverage()
    unresolved = reconciler.check_unresolved(args.unresolved_payloads)
    parameters = reconciler.check_ratchet(
        args.unverified_parameters, reconciler.candidate_named_parameters(),
        'is typed by matching composed candidate names against the parsed dictionaries',
        'Read the validateDictionary table for that operation in '
        'WebExtensionAPI<Ns>Cocoa.mm and name the dictionary explicitly, or widen '
        'the parameter.')
    unverified = reconciler.check_ratchet(
        args.unverified_returns, reconciler.unverified_returns(),
        'takes its return type from the verb table in a namespace nobody has read',
        'Read WebExtensionAPI<Ns>Cocoa.mm, check every operation against its '
        'callback->call, then add the namespace to READ_NAMESPACES.')
    checked = verify_citations(reconciler, resolver, ship_resolver)
    print(f"Accounted for every line of {len(PARSE_COVERAGE)} IDL file(s) "
          f"({covered} parsed).")
    print(f"Every operation in {len(READ_NAMESPACES)} read namespace(s) carries "
          f"evidence ({evidenced} payloads, {len(CONFIRMED_EMPTY_CALLBACKS)} empty).")
    print(f"Re-resolved {checked} citation(s) against {resolver.describe()}; "
          f"{unresolved} unresolved payload(s), "
          f"{unverified} return(s) from unread namespaces, "
          f"{parameters} parameter(s) typed by name.")

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
            # Not resolver.describe(): that names the local checkout when one is
            # used, so the file differed by machine and the diff gate could
            # never pass in CI. A local checkout at this ref holds the same
            # bytes as the repository, so the repository is the honest source.
            # --idl-dir does not, and says so, which keeps it uncommittable.
            'source': (f'{args.idl_dir} (local files, not reproducible)'
                       if args.idl_dir else f'{args.repo}@{args.ref}'),
            'repository': args.repo,
            'ref': args.ref,
            'ship_ref': ship_ref,
            'ship_sha': ship_sha,
            'ship_version': args.ship_version,
            'members': reconciler.members,
            'interfaceSkips': INTERFACE_SKIPS,
        }, indent=2, sort_keys=True) + '\n')
        print(f"Wrote provenance for {len(reconciler.members)} member(s) -> {args.provenance}")


if __name__ == '__main__':
    main()
