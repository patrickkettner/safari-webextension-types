#!/usr/bin/env python3
"""Proves each gate can go red, and that a two-sided gate does not go red on
its non-error side.

A gate that has never been seen to fail is theatre until shown otherwise; the
parse-coverage gate here reported success twice while measuring nothing. Each
CASES entry feeds the generator an input that must fail with a named error,
and this script fails if the generator does not. A GREEN_CASES entry must not
fail; it is checked against what generation recorded instead of against an
error string.

Every case runs against the pinned revision through the same resolver the real
build uses. `--webkit-checkout` is honoured when given, so this is fast locally
and still works over the network in CI.
"""

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
GENERATE = ROOT / 'scripts' / 'generate.py'


def run(extra_args, mutate=None):
    """Runs the generator, optionally on a mutated copy, and returns its output."""
    with tempfile.TemporaryDirectory() as tmp:
        script = GENERATE
        if mutate:
            script = pathlib.Path(tmp) / 'generate.py'
            script.write_text(mutate(GENERATE.read_text()))
        # A mutated copy lives outside the repository, so every path the
        # generator derives from its own location must be given explicitly or
        # the case fails for the wrong reason.
        result = subprocess.run(
            [sys.executable, str(script),
             '--output', str(pathlib.Path(tmp) / 'out.d.ts'),
             '--provenance', str(pathlib.Path(tmp) / 'p.json'),
             *(() if '--unresolved-payloads' in extra_args
               else ('--unresolved-payloads', str(ROOT / 'unresolved-payloads.txt'))),
             '--unverified-returns', str(ROOT / 'unverified-returns.txt'),
             '--unverified-parameters', str(ROOT / 'unverified-parameters.txt'),
             '--cache-dir', str(ROOT / '.idls-cache'),
             *extra_args],
            capture_output=True, text=True, cwd=str(ROOT))
    return result.returncode, result.stdout + result.stderr


CASES = []
GREEN_CASES = []


def case(name, must_contain):
    def register(fn):
        CASES.append((name, must_contain, fn))
        return fn
    return register


def green_case(name):
    """Registers an input that must not fail the build, checked against what
    generation recorded."""
    def register(fn):
        GREEN_CASES.append((name, fn))
        return fn
    return register


@case('parse coverage rejects IDL syntax no rule handles',
      'IDL the parser does not account for')
def parse_coverage(common):
    return run(['--idl-dir', str(HERE / 'idls-with-maplike'), *common])


@case('a citation that stops resolving fails the build',
      'is recorded as calling back with no argument, and the line proving it')
def stale_citation(common):
    return run(common, mutate=lambda s: s.replace(
        'BookmarksRemoveTree(bookmarkIdentifier)', 'BookmarksRemoveNothing(bookmarkIdentifier)', 1))


@case('a citation occurring more than once in its file fails the build',
      'does not identify what it cites')
def ambiguous_citation(common):
    return run(common, mutate=lambda s: s.replace(
        "EntityMember('url?: string;', (Cite(TABS_COCOA, 'urlKey: NSString.class,'),)),",
        "EntityMember('url?: string;', (Cite(TABS_COCOA, 'pinnedKey: @YES.class,'),)),", 1))


@case('an override naming a member WebKit does not declare fails the build',
      'matched no parsed member')
def fabricated_member(common):
    return run(common, mutate=lambda s: s.replace(
        "    ('WebExtensionAPIDevToolsNetwork', 'onNavigated'): Override(",
        "    ('WebExtensionAPIDevToolsNetwork', 'getHAR'): Override('getHAR(): void;'),\n"
        "    ('WebExtensionAPIDevToolsNetwork', 'onNavigated'): Override(", 1))


@case('an operation falling through the return resolver unlisted fails the build',
      'is declared void because no rule matched it')
def unresolved_payload(common):
    return run(common, mutate=lambda s: s.replace(
        "    if ns_name == 'windows' and op_name == 'getLastFocused':\n        return 'browser.Window'\n", '', 1))


@case('an MV3 gate the parser no longer recognises fails the build',
      'derive_mv3_removed_names matched nothing in it')
def mv3_gate_unrecognised(common):
    return run(common, mutate=lambda s: s.replace(
        r'\{ HashSet \{ (?P<names>', r'\{ HashSetX \{ (?P<names>', 1))


@case('a namespace dropped from READ_NAMESPACES lands in unverified-returns',
      'in a namespace nobody has read and is not in unverified-returns.txt')
def unverified_return_grows(common):
    return run(common, mutate=lambda s: s.replace("    'cookies',\n", '', 1))


@case('a parameter that falls back to a composed name lands in unverified-parameters',
      'is typed by matching composed candidate names')
def unverified_parameter_grows(common):
    return run(common, mutate=lambda s: s.replace(
        "    ('permissions', 'contains', 'permissions'): (\n"
        "        'browser.Permissions',\n"
        "        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',\n"
        "             'void WebExtensionAPIPermissions::contains(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),\n"
        "        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPIPermissionsCocoa.mm',\n"
        "             'if (!parseDetailsDictionary(details, permissions, origins, apiName, outExceptionString))'),)),\n",
        "", 1))


@case('a ratchet entry that no longer qualifies fails the build',
      'no longer unresolved')
def stale_ratchet_entry(common):
    with tempfile.TemporaryDirectory() as tmp:
        stale = pathlib.Path(tmp) / 'unresolved-payloads.txt'
        stale.write_text((ROOT / 'unresolved-payloads.txt').read_text() + 'tabs.query\n')
        return run(['--unresolved-payloads', str(stale), *common])


@case('a parameter reading whose evidence line is gone fails the build',
      'cites text no longer in')
def stale_parameter_citation(common):
    return run(common, mutate=lambda s: s.replace(
        "parseCookieDetails(details, @[ urlKey ], outExceptionString)",
        "parseCookieDetails(details, @[ nameKey ], outExceptionString)", 1))


@case('a read namespace with an operation carrying no return evidence fails the build',
      'carries no return-side evidence')
def read_namespace_without_evidence(common):
    return run(common, mutate=lambda s: s.replace(
        "    ('commands', 'getAll'): (", "    ('commands', 'getAllX'): (", 1))


@case('a dictionary correction naming a member WebKit does not declare fails the build',
      'matched no parsed dictionary member')
def invented_dictionary_member(common):
    return run(common, mutate=lambda s: s.replace(
        "    ('WebExtensionDNRTabUpdateOptions', 'tabId'): (",
        "    ('WebExtensionDNRTabUpdateOptions', 'tabIdX'): (", 1))


@case('an interface file the revision has and the list does not fails the build',
      'is not in KNOWN_IDL_FILES')
def missing_idl_file(common):
    return run(common, mutate=lambda s: s.replace("    'WebExtensionAPIAlarms.idl',\n", '', 1))


@case('an interface file the ship ref has and the list does not fails the build',
      'is not in KNOWN_IDL_FILES')
def missing_ship_idl_file(common):
    # Proves the ship-side check_idl_file_list call is fatal on its own.
    return run(common, mutate=lambda s: s.replace(
        "    listed, absent = check_idl_file_list(resolver)",
        "    KNOWN_IDL_FILES.remove(sorted(KNOWN_IDL_FILES)[0])\n"
        "    listed, absent = check_idl_file_list(resolver)", 1))


@case('--ship-ref without --ship-version fails the build',
      '--ship-ref and --ship-version must be given together')
def ship_ref_without_version(common):
    return run(['--ship-ref', 'WebKit-7624.1.16', *common])


@green_case('a KNOWN_IDL_FILES entry the revision does not have builds clean '
            'and lands in provenance as absent-at-ref')
def absent_known_idl_file(common):
    with tempfile.TemporaryDirectory() as tmp:
        script = pathlib.Path(tmp) / 'generate.py'
        script.write_text(GENERATE.read_text().replace(
            "    'WebExtensionAPIWindows.idl',\n",
            "    'WebExtensionAPIWindows.idl',\n"
            "    'WebExtensionAPINotThere.idl',\n", 1))
        provenance = pathlib.Path(tmp) / 'p.json'
        result = subprocess.run(
            [sys.executable, str(script),
             '--output', str(pathlib.Path(tmp) / 'out.d.ts'),
             '--provenance', str(provenance),
             '--unresolved-payloads', str(ROOT / 'unresolved-payloads.txt'),
             '--unverified-returns', str(ROOT / 'unverified-returns.txt'),
             '--unverified-parameters', str(ROOT / 'unverified-parameters.txt'),
             '--cache-dir', str(ROOT / '.idls-cache'),
             *common],
            capture_output=True, text=True, cwd=str(ROOT))
        if result.returncode != 0:
            return False, f'exited {result.returncode}:\n{result.stdout}{result.stderr}'
        members = json.loads(provenance.read_text())['members']
        hit = next((m for m in members
                    if m['interface'] == 'WebExtensionAPINotThere'
                    and m['origin'] == 'absent-at-ref'), None)
        if hit is None:
            return False, 'no absent-at-ref provenance entry for WebExtensionAPINotThere'
        return True, 'ok'


@green_case('a member the main ref declares and the ship ref does not is left '
            'out of index.d.ts and lands in provenance as unshipped')
def unshipped_member(common):
    with tempfile.TemporaryDirectory() as tmp:
        script = pathlib.Path(tmp) / 'generate.py'
        script.write_text(GENERATE.read_text().replace(
            "    ship_dicts = {name: set(data['members']) for name, data in dicts.items()}",
            "    ship_ifaces['WebExtensionAPITabs']['operations'].discard('query')\n"
            "    ship_dicts = {name: set(data['members']) for name, data in dicts.items()}",
            1))
        out = pathlib.Path(tmp) / 'out.d.ts'
        provenance = pathlib.Path(tmp) / 'p.json'
        result = subprocess.run(
            [sys.executable, str(script),
             '--output', str(out),
             '--provenance', str(provenance),
             '--unresolved-payloads', str(ROOT / 'unresolved-payloads.txt'),
             '--unverified-returns', str(ROOT / 'unverified-returns.txt'),
             '--unverified-parameters', str(ROOT / 'unverified-parameters.txt'),
             '--cache-dir', str(ROOT / '.idls-cache'),
             *common],
            capture_output=True, text=True, cwd=str(ROOT))
        if result.returncode != 0:
            return False, f'exited {result.returncode}:\n{result.stdout}{result.stderr}'
        members = json.loads(provenance.read_text())['members']
        hit = next((m for m in members
                    if m['interface'] == 'WebExtensionAPITabs'
                    and m['member'] == 'query'
                    and m['origin'] == 'unshipped'), None)
        if hit is None:
            return False, 'no unshipped provenance entry for WebExtensionAPITabs.query'
        if 'export function query(info: browser.TabQueryOptions' in out.read_text():
            return False, 'tabs.query is still emitted in index.d.ts'
        return True, 'ok'


@case('an empty-callback entry naming an operation nothing reads fails the build',
      'matched no operation')
def unused_empty_callback(common):
    return run(common, mutate=lambda s: s.replace(
        "    ('tabs', 'goBack'): Cite(",
        "    ('tabs', 'goBackNoSuchOperation'): Cite(\n"
        "        'Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPITabsCocoa.mm',\n"
        "        'WebProcess::singleton().sendWithAsyncReply(Messages::WebExtensionContext::TabsGoBack(webPageProxyIdentifier, tabIdentifer), [protectedThis = Ref { *this }, callback = WTF::move(callback)](Expected<void, WebExtensionError>&& result) {'),\n"
        "    ('tabs', 'goBack'): Cite(", 1))


@case('a parameter-type entry naming a parameter nothing reads fails the build',
      'matched no parameter')
def unused_parameter_type(common):
    return run(common, mutate=lambda s: s.replace(
        "    ('cookies', 'get', 'details'): (",
        "    ('cookies', 'get', 'detailsNoSuchParameter'): (\n"
        "        '{ name: string; url: string; storeId?: string }',\n"
        "        (Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',\n"
        "             'void WebExtensionAPICookies::get(NSDictionary *details, Ref<WebExtensionCallbackHandler>&& callback, NSString **outExceptionString)'),\n"
        "        Cite('Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPICookiesCocoa.mm',\n"
        "             'auto parsedDetails = parseCookieDetails(details, @[ @\"name\", urlKey ], outExceptionString);'),)),\n"
        "    ('cookies', 'get', 'details'): (", 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--webkit-checkout', type=pathlib.Path)
    args = parser.parse_args()
    common = ['--webkit-checkout', str(args.webkit_checkout)] if args.webkit_checkout else []

    failures = 0
    for name, must_contain, fn in CASES:
        code, output = fn(common)
        if code == 0:
            print(f'NOT RED  {name}: generator exited 0')
            failures += 1
        elif must_contain not in output:
            print(f'WRONG RED  {name}: failed, but not with the expected error')
            print('  ' + output.strip().splitlines()[-1][:160])
            failures += 1
        else:
            print(f'red      {name}')
    for name, fn in GREEN_CASES:
        ok, detail = fn(common)
        if ok:
            print(f'green    {name}')
        else:
            print(f'NOT GREEN  {name}: {detail}')
            failures += 1
    total = len(CASES) + len(GREEN_CASES)
    print(f'{total - failures} of {total} gates verified.')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
