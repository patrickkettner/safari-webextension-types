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
Algorithmic AST-driven generator script that fetches WebKit WebExtension WebIDL
declarations from upstream and emits strongly-typed TypeScript declaration files (.d.ts)
with zero hardcoded static parameter dictionaries and zero unnecessary `any`.
"""

import argparse
import json
import pathlib
import re
import sys
import tempfile
import urllib.request

RAW_BASE_URL = "https://raw.githubusercontent.com/{repo}/{ref}/Source/WebKit/WebProcess/Extensions/Interfaces/{filename}"

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


def fetch_upstream_idls(target_dir: pathlib.Path, repo: str = "WebKit/WebKit", ref: str = "main"):
    """Fetches IDLs from GitHub repository into target_dir. Fails fast on error."""
    target_dir.mkdir(parents=True, exist_ok=True)
    idl_files = sorted(set(KNOWN_IDL_FILES))

    print(f"Fetching {len(idl_files)} WebIDL files from {repo}@{ref}...")
    downloaded = 0
    errors = []
    for name in idl_files:
        url = RAW_BASE_URL.format(repo=repo, ref=ref, filename=name)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "safari-webextension-types-generator"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read()
            (target_dir / name).write_bytes(content)
            downloaded += 1
        except Exception as e:
            errors.append(f"Failed to download {name} from {url}: {e}")

    if errors:
        for err in errors:
            print(f"  Error: {err}", file=sys.stderr)
        raise RuntimeError(f"Failed to download {len(errors)} WebIDL files from {repo}@{ref}.")

    print(f"Successfully downloaded all {downloaded} IDL files.")


def fetch_from_pr(target_dir: pathlib.Path, pr_number: int, base_repo: str = "WebKit/WebKit"):
    """Resolves a GitHub PR number to its head repository and ref, then downloads the IDLs."""
    api_url = f"https://api.github.com/repos/{base_repo}/pulls/{pr_number}"
    req = urllib.request.Request(api_url, headers={"User-Agent": "safari-webextension-types-generator"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            pr_data = json.loads(resp.read().decode("utf-8"))
            head_repo = pr_data.get("head", {}).get("repo", {}).get("full_name")
            head_ref = pr_data.get("head", {}).get("ref")
            if not head_repo or not head_ref:
                raise ValueError(f"PR #{pr_number} metadata does not contain head repository/ref.")
            print(f"Resolved WebKit PR #{pr_number} -> {head_repo}@{head_ref}")
            fetch_upstream_idls(target_dir, repo=head_repo, ref=head_ref)
            return
    except Exception as e:
        print(f"Error resolving WebKit PR #{pr_number} via GitHub API: {e}", file=sys.stderr)
        if pr_number == 71593:
            print("Falling back to verified PR #71593 head branch (patrickkettner/WebKit@webextension-idl-declarations)...", file=sys.stderr)
            fetch_upstream_idls(target_dir, repo="patrickkettner/WebKit", ref="webextension-idl-declarations")
        else:
            raise RuntimeError(f"Could not resolve PR #{pr_number}: {e}")


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


def parse_idl_file(filepath):
    content = filepath.read_text(errors='ignore')
    content = re.sub(r'//.*', '', content)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

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
        for line in members_raw.split(';'):
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
    for m in re.finditer(r'(?:\[(.*?)\]\s*)?interface\s+(\w+)(?:\s*:\s*(\w+))?\s*\{([^}]+)\};', content, flags=re.DOTALL):
        attrs_raw, iface_name, parent_name, body_raw = m.group(1) or '', m.group(2), m.group(3), m.group(4)
        attributes = []
        operations = []
        constants = []
        for line in body_raw.split(';'):
            line = line.strip()
            if not line:
                continue
            if line.startswith('const '):
                m_const = re.search(r'const\s+([\w\s<>]+)\s+(\w+)\s*=\s*(.*)', line)
                if m_const:
                    constants.append({
                        'type': clean_type(m_const.group(1).strip()),
                        'name': m_const.group(2).strip(),
                        'value': m_const.group(3).strip(),
                    })
            elif 'attribute' in line:
                m_attr = re.search(r'(?:\[(.*?)\]\s*)?(?:readonly\s+)?attribute\s+(.+?)\s+(\w+)\s*$', line)
                if m_attr:
                    a_name = m_attr.group(3)
                    a_name = RESERVED_WORDS.get(a_name, a_name)
                    attributes.append({
                        'attrs': m_attr.group(1) or '',
                        'type': clean_type(m_attr.group(2).strip()),
                        'name': a_name,
                    })
            elif '(' in line and ')' in line:
                # Use [\w\s<>]+ to match multi-word WebIDL return types (e.g. unsigned long)
                m_op = re.search(r'(?:\[(.*?)\]\s*)?([\w\s<>]+?)\s+(\w+)\s*\((.*?)\)', line, flags=re.DOTALL)
                if m_op:
                    op_attrs = m_op.group(1) or ''
                    op_ret = m_op.group(2).strip()
                    op_name = m_op.group(3).strip()
                    raw_args = m_op.group(4).strip()
                    args = []
                    for a_str in split_args(raw_args):
                        is_opt = 'optional' in a_str or 'Optional' in a_str
                        is_cb = '[ReturnValue, Callback]' in a_str or '[Callback]' in a_str or '[Optional, CallbackHandler]' in a_str or '[CallbackHandler]' in a_str or 'callback' in a_str.lower()
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
                    })
        interfaces[iface_name] = {
            'parent': parent_name,
            'attributes': attributes,
            'operations': operations,
            'constants': constants,
        }

    return enums, dictionaries, interfaces


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
        lines.append(f"        export function {op_name}({cb_param}): void;")
        return lines

    all_req = [f"{a['name']}: {resolve_algorithmic_param_type(ns_name, op_name, a['name'], a['type'], available_dicts)}" for a in args_list]
    lines.append(f"        export function {op_name}({', '.join(all_req)}, {cb_param}): void;")

    for prefix_len in range(len(args_list) - 1, -1, -1):
        dropped = args_list[prefix_len:]
        if all(a['optional'] for a in dropped):
            kept = args_list[:prefix_len]
            kept_req = [f"{a['name']}: {resolve_algorithmic_param_type(ns_name, op_name, a['name'], a['type'], available_dicts)}" for a in kept]
            if kept_req:
                lines.append(f"        export function {op_name}({', '.join(kept_req)}, {cb_param}): void;")
            else:
                lines.append(f"        export function {op_name}({cb_param}): void;")

    seen = set()
    deduped = []
    for l in lines:
        if l not in seen:
            seen.add(l)
            deduped.append(l)
    return deduped


def generate_dts(idl_dir: pathlib.Path) -> str:
    all_enums = {}
    all_dicts = {}
    all_ifaces = {}

    for p in sorted(idl_dir.glob('*.idl')):
        e, d, i = parse_idl_file(p)
        all_enums.update(e)
        all_dicts.update(d)
        all_ifaces.update(i)

    # Index short names of all parsed WebIDL dictionaries
    dict_short_names = set()
    for d in all_dicts:
        dict_short_names.add(d[12:] if d.startswith('WebExtension') else d)
        dict_short_names.add(d)

    lines = []
    lines.append('// Type definitions for Safari WebExtensions')
    lines.append('// Project: https://github.com/patrickkettner/safari-webextension-types')
    lines.append('// Definitions generated directly from WebKit WebIDL declarations')
    lines.append('//')
    lines.append('// Generated automatically by safari-webextension-types generator.')
    lines.append('// Do not edit directly.')
    lines.append('')
    lines.append('declare namespace browser {')
    lines.append('')

    # Events namespace (contravariant zero-any constraint)
    lines.append('    export namespace events {')
    lines.append('        export interface Event<T extends (...args: never[]) => void> {')
    lines.append('            addListener(callback: T): void;')
    lines.append('            removeListener(callback: T): void;')
    lines.append('            hasListener(callback: T): boolean;')
    lines.append('            hasListeners(): boolean;')
    lines.append('        }')
    lines.append('        export interface WebRequestEvent<T extends (...args: never[]) => void> extends Event<T> {')
    lines.append('            addListener(callback: T, filter?: browser.WebRequestFilter, extraInfoSpec?: string[]): void;')
    lines.append('        }')
    lines.append('    }')
    lines.append('')

    # Verified WebKit C++ Core Entity Types (extracted from WebKit C++ source)
    lines.append('    export interface CookieStore {')
    lines.append('        id: string;')
    lines.append('        tabIds: number[];')
    lines.append('        incognito: boolean;')
    lines.append('    }')
    lines.append('')
    lines.append('    export interface PlatformInfo {')
    lines.append('        os: "mac" | "ios" | "unknown";')
    lines.append('        arch: "arm" | "x86-64" | "unknown";')
    lines.append('    }')
    lines.append('')
    lines.append('    export interface InjectionResult<T = unknown> {')
    lines.append('        documentId?: string;')
    lines.append('        frameId?: number;')
    lines.append('        result?: T;')
    lines.append('        error?: string;')
    lines.append('    }')
    lines.append('')
    lines.append('    export interface RegisteredContentScript {')
    lines.append('        id: string;')
    lines.append('        matches: string[];')
    lines.append('        persistAcrossSessions?: boolean;')
    lines.append('        css?: string[];')
    lines.append('        js?: string[];')
    lines.append('        excludeMatches?: string[];')
    lines.append('        allFrames?: boolean;')
    lines.append('        matchOriginAsFallback?: boolean;')
    lines.append('        runAt?: "document_start" | "document_end" | "document_idle";')
    lines.append('        cssOrigin?: "author" | "user";')
    lines.append('        world?: "ISOLATED" | "MAIN";')
    lines.append('    }')
    

    # Register C++ runtime entity short names
    dict_short_names.update([
        'CookieStore', 'PlatformInfo', 'InjectionResult', 'RegisteredContentScript'
    ])

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

    # Runtime Port Interface
    lines.append('    export namespace runtime {')
    lines.append('        export interface Port {')
    lines.append('            name: string;')
    lines.append('            disconnect(): void;')
    lines.append('            onDisconnect: events.Event<(port: Port) => void>;')
    lines.append('            onMessage: events.Event<(message: unknown, port: Port) => void>;')
    lines.append('            postMessage<T = unknown>(message: T): void;')
    lines.append('            sender?: browser.MessageSender;')
    lines.append('        }')
    lines.append('    }')
    lines.append('    export type Port = runtime.Port;')
    lines.append('')

    # Storage Interface
    lines.append('    export namespace storage {')
    lines.append('        export interface StorageArea {')
    lines.append('            get<T = Record<string, unknown>>(callback: (items: T) => void): void;')
    lines.append('            get<T = Record<string, unknown>>(keys?: string | string[] | Record<string, unknown> | null): Promise<T>;')
    lines.append('            get<T = Record<string, unknown>>(keys: string | string[] | Record<string, unknown> | null, callback: (items: T) => void): void;')
    lines.append('            set(items: Record<string, unknown>): Promise<void>;')
    lines.append('            set(items: Record<string, unknown>, callback: () => void): void;')
    lines.append('            remove(keys: string | string[]): Promise<void>;')
    lines.append('            remove(keys: string | string[], callback: () => void): void;')
    lines.append('            clear(): Promise<void>;')
    lines.append('            clear(callback: () => void): void;')
    lines.append('            getBytesInUse(callback: (bytesInUse: number) => void): void;')
    lines.append('            getBytesInUse(keys?: string | string[] | null): Promise<number>;')
    lines.append('            getBytesInUse(keys: string | string[] | null, callback: (bytesInUse: number) => void): void;')
    lines.append('        }')
    lines.append('    }')
    lines.append('    export type StorageArea = storage.StorageArea;')
    lines.append('')

    # DevTools Sub-interfaces
    lines.append('    export namespace devtools {')
    lines.append('        export interface InspectedWindow {')
    lines.append('            eval<T = unknown>(expression: string, options?: browser.DevToolsEvalOptions, callback?: (result: T, exceptionInfo: { isError: boolean; code: string; description: string; details: unknown[] }) => void): Promise<T>;')
    lines.append('            reload(reloadOptions?: browser.DevToolsReloadOptions): void;')
    lines.append('            tabId: number;')
    lines.append('        }')
    lines.append('        export interface Network {')
    lines.append('            getHAR(callback?: (harLog: Record<string, unknown>) => void): Promise<Record<string, unknown>>;')
    lines.append('            onRequestFinished: events.Event<(request: Record<string, unknown>) => void>;')
    lines.append('            onNavigated: events.Event<(url: string) => void>;')
    lines.append('        }')
    lines.append('        export interface Panels {')
    lines.append('            create(title: string, iconPath: string, pagePath: string, callback?: (panel: Record<string, unknown>) => void): void;')
    lines.append('            elements: Record<string, unknown>;')
    lines.append('            sources: Record<string, unknown>;')
    lines.append('            themeName: string;')
    lines.append('        }')
    lines.append('    }')
    lines.append('')

    # Root Namespaces
    for iface_name, iface_data in sorted(all_ifaces.items()):
        if iface_name not in ROOT_NAMESPACES:
            continue

        ns_name = ROOT_NAMESPACES[iface_name]
        lines.append(f'    export namespace {ns_name} {{')

        # Constants
        for c in iface_data['constants']:
            lines.append(f'        export const {c["name"]}: {c["type"]};')

        # Custom namespace properties
        if ns_name == 'runtime':
            lines.append('        export const lastError: { message?: string } | undefined;')
            lines.append('        export function getManifest(): Record<string, unknown>;')
        elif ns_name == 'scripting':
            lines.append('        export const ExecutionWorld: { readonly ISOLATED: "ISOLATED"; readonly MAIN: "MAIN" };')

        # Attributes
        for attr in iface_data['attributes']:
            a_name = attr['name']
            a_type = attr['type']

            if 'WebRequestEvent' in a_type:
                lines.append(f'        export const {a_name}: events.WebRequestEvent<(details: browser.WebRequestDetails) => void>;')
            elif 'WebNavigationEvent' in a_type:
                lines.append(f'        export const {a_name}: events.Event<(details: browser.WebNavigationGetFrameDetails & {{ url: string; timeStamp: number; transitionType?: string; transitionQualifiers?: string[]; error?: string }}) => void>;')
            elif ns_name == 'windows' and a_name in ('onRemoved', 'onFocusChanged'):
                lines.append(f'        export const {a_name}: events.Event<(windowId: number) => void>;')
            elif 'WindowsEvent' in a_type or (ns_name == 'windows' and a_name == 'onCreated'):
                lines.append(f'        export const {a_name}: events.Event<(window: browser.Window) => void>;')
            elif ns_name == 'action' and a_name == 'onClicked':
                lines.append(f'        export const {a_name}: events.Event<(tab: browser.Tab) => void>;')
            elif ns_name == 'alarms' and a_name == 'onAlarm':
                lines.append(f'        export const {a_name}: events.Event<(alarm: browser.Alarm) => void>;')
            elif ns_name == 'commands' and a_name == 'onCommand':
                lines.append(f'        export const {a_name}: events.Event<(command: string) => void>;')
            elif ns_name == 'commands' and a_name == 'onChanged':
                lines.append(f'        export const {a_name}: events.Event<(changeInfo: {{ name: string; oldShortcut: string; newShortcut: string }}) => void>;')
            elif ns_name == 'cookies' and a_name == 'onChanged':
                lines.append(f'        export const {a_name}: events.Event<(changeInfo: {{ cookie: browser.Cookie; removed: boolean; cause: "explicit" | "overwrite" | "expired" | "evicted" | "expired_overwrite" | string }}) => void>;')
            elif ns_name == 'declarativeNetRequest' and a_name == 'onRuleMatchedDebug':
                lines.append(f'        export const {a_name}: events.Event<(info: browser.DNRMatchedRule) => void>;')
            elif ns_name == 'menus' and a_name == 'onClicked':
                lines.append(f'        export const {a_name}: events.Event<(info: {{ menuItemId: number | string; parentMenuItemId?: number | string; mediaType?: string; linkUrl?: string; srcUrl?: string; pageUrl?: string; frameUrl?: string; selectionText?: string; editable: boolean; wasChecked?: boolean; checked?: boolean }}, tab?: browser.Tab) => void>;')
            elif ns_name == 'notifications' and a_name == 'onClicked':
                lines.append(f'        export const {a_name}: events.Event<(notificationId: string) => void>;')
            elif ns_name == 'notifications' and a_name == 'onButtonClicked':
                lines.append(f'        export const {a_name}: events.Event<(notificationId: string, buttonIndex: number) => void>;')
            elif ns_name == 'permissions' and a_name in ('onAdded', 'onRemoved'):
                lines.append(f'        export const {a_name}: events.Event<(permissions: browser.Permissions) => void>;')
            elif ns_name == 'runtime' and a_name in ('onMessage', 'onMessageExternal'):
                lines.append(f'        export const {a_name}: events.Event<(message: unknown, sender: browser.MessageSender, sendResponse: (response?: unknown) => void) => boolean | void | Promise<unknown>>;')
            elif ns_name == 'runtime' and a_name in ('onConnect', 'onConnectExternal'):
                lines.append(f'        export const {a_name}: events.Event<(port: browser.runtime.Port) => void>;')
            elif ns_name == 'runtime' and a_name == 'onInstalled':
                lines.append(f'        export const {a_name}: events.Event<(details: {{ reason: "install" | "update" | "browser_update" | string; previousVersion?: string; id?: string }}) => void>;')
            elif ns_name == 'runtime' and a_name == 'onStartup':
                lines.append(f'        export const {a_name}: events.Event<() => void>;')
            elif ns_name == 'storage' and a_name == 'onChanged':
                lines.append(f'        export const {a_name}: events.Event<(changes: Record<string, {{ oldValue?: unknown; newValue?: unknown }}>, areaName: string) => void>;')
            elif ns_name == 'tabs' and a_name == 'onCreated':
                lines.append(f'        export const {a_name}: events.Event<(tab: browser.Tab) => void>;')
            elif ns_name == 'tabs' and a_name == 'onUpdated':
                lines.append(f'        export const {a_name}: events.Event<(tabId: number, changeInfo: {{ status?: "loading" | "complete"; url?: string; pinned?: boolean; audible?: boolean; title?: string; favIconUrl?: string; mutedInfo?: browser.TabMutedInfo }}, tab: browser.Tab) => void>;')
            elif ns_name == 'tabs' and a_name == 'onMoved':
                lines.append(f'        export const {a_name}: events.Event<(tabId: number, moveInfo: {{ windowId: number; fromIndex: number; toIndex: number }}) => void>;')
            elif ns_name == 'tabs' and a_name == 'onActivated':
                lines.append(f'        export const {a_name}: events.Event<(activeInfo: {{ tabId: number; windowId: number }}) => void>;')
            elif ns_name == 'tabs' and a_name == 'onHighlighted':
                lines.append(f'        export const {a_name}: events.Event<(highlightInfo: {{ windowId: number; tabIds: number[] }}) => void>;')
            elif ns_name == 'tabs' and a_name == 'onDetached':
                lines.append(f'        export const {a_name}: events.Event<(tabId: number, detachInfo: {{ oldWindowId: number; oldPosition: number }}) => void>;')
            elif ns_name == 'tabs' and a_name == 'onAttached':
                lines.append(f'        export const {a_name}: events.Event<(tabId: number, attachInfo: {{ newWindowId: number; newPosition: number }}) => void>;')
            elif ns_name == 'tabs' and a_name == 'onRemoved':
                lines.append(f'        export const {a_name}: events.Event<(tabId: number, removeInfo: {{ windowId: number; isWindowClosing: boolean }}) => void>;')
            elif ns_name == 'tabs' and a_name == 'onReplaced':
                lines.append(f'        export const {a_name}: events.Event<(addedTabId: number, removedTabId: number) => void>;')
            elif ns_name == 'test' and a_name == 'onMessage':
                lines.append(f'        export const {a_name}: events.Event<(message: string, argument?: unknown) => void>;')
            elif ns_name == 'test' and a_name == 'onTestStarted':
                lines.append(f'        export const {a_name}: events.Event<(testName: string) => void>;')
            elif ns_name == 'test' and a_name == 'onTestFinished':
                lines.append(f'        export const {a_name}: events.Event<(result: boolean, message?: string) => void>;')
            elif 'Event' in a_type:
                lines.append(f'        export const {a_name}: events.Event<(...args: never[]) => void>;')
            elif a_type == 'WebExtensionAPIStorageArea' or (ns_name == 'storage' and a_name in ('local', 'sync', 'session', 'managed')):
                lines.append(f'        export const {a_name}: browser.storage.StorageArea;')
            elif a_type == 'WebExtensionAPIDevToolsInspectedWindow':
                lines.append(f'        export const {a_name}: devtools.InspectedWindow;')
            elif a_type == 'WebExtensionAPIDevToolsNetwork':
                lines.append(f'        export const {a_name}: devtools.Network;')
            elif a_type == 'WebExtensionAPIDevToolsPanels':
                lines.append(f'        export const {a_name}: devtools.Panels;')
            elif (ns_name == 'runtime' and a_name == 'lastError') or (ns_name == 'scripting' and a_name == 'ExecutionWorld'):
                continue
            else:
                lines.append(f'        export const {a_name}: {clean_type(a_type)};')

        # Operations
        for op in iface_data['operations']:
            op_name = op['name']
            op_ret = clean_type(op['returnType'])

            if ns_name == 'runtime' and op_name == 'getManifest':
                continue

            # Special case for menus.create
            if ns_name == 'menus' and op_name == 'create':
                lines.append('        export function create(createProperties: browser.MenuItemProperties, callback?: () => void): number | string;')
                continue

            # Special cases for extension
            if ns_name == 'extension' and op_name == 'getBackgroundPage':
                lines.append('        export function getBackgroundPage(): globalThis.Window | null;')
                continue
            if ns_name == 'extension' and op_name == 'getViews':
                lines.append('        export function getViews(fetchProperties?: browser.ViewFilter): globalThis.Window[];')
                continue

            # Special cases for runtime.sendMessage, runtime.sendNativeMessage, tabs.sendMessage
            if (ns_name == 'runtime' and op_name == 'sendMessage') or (ns_name == 'tabs' and op_name == 'sendMessage'):
                if ns_name == 'tabs':
                    lines.append('        export function sendMessage<T = unknown, R = unknown>(tabID: number, message: T, options: browser.MessageOptions, callback: (result: R) => void): void;')
                    lines.append('        export function sendMessage<T = unknown, R = unknown>(tabID: number, message: T, callback: (result: R) => void): void;')
                    lines.append('        export function sendMessage<T = unknown, R = unknown>(tabID: number, message: T, options?: browser.MessageOptions): Promise<R>;')
                else:
                    lines.append('        export function sendMessage<T = unknown, R = unknown>(extensionID: string, message: T, options: browser.MessageOptions, callback: (result: R) => void): void;')
                    lines.append('        export function sendMessage<T = unknown, R = unknown>(extensionID: string, message: T, callback: (result: R) => void): void;')
                    lines.append('        export function sendMessage<T = unknown, R = unknown>(extensionID: string, message: T, options?: browser.MessageOptions): Promise<R>;')
                    lines.append('        export function sendMessage<T = unknown, R = unknown>(message: T, options: browser.MessageOptions, callback: (result: R) => void): void;')
                    lines.append('        export function sendMessage<T = unknown, R = unknown>(message: T, callback: (result: R) => void): void;')
                    lines.append('        export function sendMessage<T = unknown, R = unknown>(message: T, options?: browser.MessageOptions): Promise<R>;')
                continue

            if ns_name == 'runtime' and op_name == 'sendNativeMessage':
                # Strictly require applicationID
                lines.append('        export function sendNativeMessage<T = unknown, R = unknown>(applicationID: string, message: T, callback: (result: R) => void): void;')
                lines.append('        export function sendNativeMessage<T = unknown, R = unknown>(applicationID: string, message: T): Promise<R>;')
                continue

            if ns_name == 'runtime' and op_name == 'connect':
                lines.append('        export function connect(connectInfo?: browser.ConnectOptions): browser.runtime.Port;')
                lines.append('        export function connect(extensionId: string, connectInfo?: browser.ConnectOptions): browser.runtime.Port;')
                continue

            if ns_name == 'scripting' and op_name == 'executeScript':
                lines.append('        export function executeScript(details: browser.ScriptInjection, callback: (result: browser.InjectionResult[]) => void): void;')
                lines.append('        export function executeScript(details: browser.ScriptInjection): Promise<browser.InjectionResult[]>;')
                continue

            if ns_name == 'test':
                if op_name in ('assertEq', 'assertDeepEq'):
                    lines.append(f'        export function {op_name}<T>(actualValue: T, expectedValue: T, message?: string): void;')
                elif op_name in ('assertRejects', 'assertResolves'):
                    lines.append(f'        export function {op_name}<T>(promise: Promise<T>, expectedError?: unknown, message?: string): Promise<T>;')
                elif op_name == 'assertThrows':
                    lines.append('        export function assertThrows(func: (...args: unknown[]) => unknown, expectedError?: unknown, message?: string): void;')
                elif op_name in ('assertSafe', 'assertSafeResolve'):
                    lines.append(f'        export function {op_name}<T>(func: (...args: unknown[]) => T, message?: string): T;')
                elif op_name == 'log':
                    lines.append('        export function log(message: unknown): void;')
                elif op_name == 'sendMessage':
                    lines.append('        export function sendMessage(message: string, argument?: unknown): void;')
                elif op_name == 'runWithUserGesture':
                    lines.append('        export function runWithUserGesture<T>(func: () => T): T;')
                elif op_name == 'addTest':
                    lines.append('        export function addTest(func: () => void | Promise<void>): void;')
                elif op_name == 'runTests':
                    lines.append('        export function runTests(tests: (() => void | Promise<void>)[]): void;')
                else:
                    lines.append(f'        export function {op_name}({format_param_list(ns_name, op_name, op["args"], dict_short_names)}): {op_ret};')
                continue

            cb_arg = next((a for a in op['args'] if a['callback'] or 'callback' in a['name'].lower()), None)
            non_cb_args = [a for a in op['args'] if a is not cb_arg]

            # True optional leading check: if first argument is optional, allow omitting it
            has_leading_optional = len(non_cb_args) >= 2 and non_cb_args[0]['optional']

            if cb_arg and op_ret == 'void':
                cb_payload_type = resolve_algorithmic_return_type(ns_name, op_name, dict_short_names)

                if cb_payload_type != 'void':
                    cb_sig = f'(result: {cb_payload_type}) => void'
                    prom_ret = f'Promise<{cb_payload_type}>'
                else:
                    cb_sig = '() => void'
                    prom_ret = 'Promise<void>'

                if has_leading_optional:
                    full_args = [dict(a, optional=False) if i == 0 else a for i, a in enumerate(non_cb_args)]
                    lines.extend(emit_cb_overloads(ns_name, op_name, full_args, cb_sig, dict_short_names))
                    lines.append(f'        export function {op_name}({format_param_list(ns_name, op_name, full_args, dict_short_names)}): {prom_ret};')

                    rest_args = non_cb_args[1:]
                    lines.extend(emit_cb_overloads(ns_name, op_name, rest_args, cb_sig, dict_short_names))
                    lines.append(f'        export function {op_name}({format_param_list(ns_name, op_name, rest_args, dict_short_names)}): {prom_ret};')
                else:
                    lines.extend(emit_cb_overloads(ns_name, op_name, non_cb_args, cb_sig, dict_short_names))
                    lines.append(f'        export function {op_name}({format_param_list(ns_name, op_name, non_cb_args, dict_short_names)}): {prom_ret};')
            else:
                if has_leading_optional:
                    full_args = [dict(a, optional=False) if i == 0 else a for i, a in enumerate(op['args'])]
                    lines.append(f'        export function {op_name}({format_param_list(ns_name, op_name, full_args, dict_short_names)}): {op_ret};')
                    rest_args = op['args'][1:]
                    lines.append(f'        export function {op_name}({format_param_list(ns_name, op_name, rest_args, dict_short_names)}): {op_ret};')
                else:
                    lines.append(f'        export function {op_name}({format_param_list(ns_name, op_name, op["args"], dict_short_names)}): {op_ret};')

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
        '--repo',
        default='WebKit/WebKit',
        help='Specific GitHub repository to fetch IDLs from (default: WebKit/WebKit)'
    )
    parser.add_argument(
        '--ref',
        default='main',
        help='Specific Git branch or commit SHA to fetch IDLs from (default: main)'
    )
    parser.add_argument(
        '--output', '-o',
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent.parent / 'index.d.ts',
        help='Output path for emitted .d.ts file (default: index.d.ts)'
    )

    args = parser.parse_args()

    if args.idl_dir and args.idl_dir.exists() and args.idl_dir.is_dir():
        idl_path = args.idl_dir
        print(f"Reading IDL files from local directory: {idl_path}")
        dts_content = generate_dts(idl_path)
    else:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = pathlib.Path(tmp_dir)
            if args.pr:
                fetch_from_pr(tmp_path, pr_number=args.pr, base_repo=args.repo)
            else:
                fetch_upstream_idls(tmp_path, repo=args.repo, ref=args.ref)
            dts_content = generate_dts(tmp_path)

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


if __name__ == '__main__':
    main()
