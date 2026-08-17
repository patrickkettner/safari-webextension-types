#!/usr/bin/env python3
"""Proves each gate can go red.

A gate that has never been seen to fail is theatre until shown otherwise; the
parse-coverage gate here reported success twice while measuring nothing. Each
case below feeds the generator an input that must fail with a named error, and
this script fails if the generator does not.

Every case runs against the pinned revision through the same resolver the real
build uses. `--webkit-checkout` is honoured when given, so this is fast locally
and still works over the network in CI.
"""

import argparse
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


def case(name, must_contain):
    def register(fn):
        CASES.append((name, must_contain, fn))
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


@case('a namespace dropped from READ_NAMESPACES lands in unverified-returns',
      'in a namespace nobody has read and is not in unverified-returns.txt')
def unverified_return_grows(common):
    return run(common, mutate=lambda s: s.replace("    'cookies',\n", '', 1))


@case('a parameter that falls back to a composed name lands in unverified-parameters',
      'is typed by matching composed candidate names')
def unverified_parameter_grows(common):
    return run(common, mutate=lambda s: s.replace(
        "    ('permissions', 'contains', 'permissions'): (", "    ('permissions', 'containsX', 'permissions'): (", 1))


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
    print(f'{len(CASES) - failures} of {len(CASES)} gates proven red.')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
