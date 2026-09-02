#!/usr/bin/env python3
"""Unit test for derive_mv3_removed_names in scripts/generate.py.

Feeds it synthetic isPropertyAllowed snippets; touches no WebKit checkout or
the network.
"""

import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATE = ROOT / 'scripts' / 'generate.py'

spec = importlib.util.spec_from_file_location('generate', GENERATE)
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)

derive_mv3_removed_names = generate.derive_mv3_removed_names

failures = []


def check(name, actual, expected):
    if actual != expected:
        failures.append(f'{name}: expected {expected!r}, got {actual!r}')


# Shape A: a name gated in its own branch, mixed with distractors.
DIRECT_SHAPE = '''
bool WebExtensionAPINamespace::isPropertyAllowed(const ASCIILiteral& name, WebPage* page)
{
    if (name == "bookmarks"_s)
        return page->corePage()->settings().webExtensionBookmarksEnabled();

    if (name == "declarativeNetRequest"_s)
        return extensionContext->hasPermission(name);

    if (name == "browserAction"_s)
        return !extensionContext->supportsManifestVersion(3) && doesDictionaryExist(extensionContext->manifest(), "browser_action"_s);

    if (name == "pageAction"_s)
        return !extensionContext->supportsManifestVersion(3) && doesDictionaryExist(extensionContext->manifest(), "page_action"_s);

    ASSERT_NOT_REACHED();
    return false;
}
'''

direct_result = derive_mv3_removed_names(DIRECT_SHAPE)
check('direct shape: names found', set(direct_result), {'browserAction', 'pageAction'})
check('direct shape: bookmarks not swept in', 'bookmarks' in direct_result, False)
check('direct shape: declarativeNetRequest not swept in',
      'declarativeNetRequest' in direct_result, False)
for gated_name in ('browserAction', 'pageAction'):
    quote = direct_result[gated_name]
    if f'"{gated_name}"_s' not in quote or 'supportsManifestVersion(3)' not in quote:
        failures.append(f'direct shape: {gated_name} quote does not identify its own gate: {quote!r}')


# Shape B: several names sharing one removedInManifestVersion3 set.
SET_SHAPE = '''
bool WebExtensionAPITabs::isPropertyAllowed(const ASCIILiteral& name, WebPage*)
{
    RefPtr context = extensionContext();
    if (context->isUnsupportedAPI(propertyPath(), name)) [[unlikely]]
        return false;

    static NeverDestroyed<HashSet<AtomString>> removedInManifestVersion3 { HashSet { AtomString("executeScript"_s), AtomString("getSelected"_s), AtomString("insertCSS"_s), AtomString("removeCSS"_s) } };
    if (removedInManifestVersion3.get().contains(name))
        return !context->supportsManifestVersion(3);

    ASSERT_NOT_REACHED();
    return false;
}
'''

set_result = derive_mv3_removed_names(SET_SHAPE)
check('set shape: names found', set(set_result),
      {'executeScript', 'getSelected', 'insertCSS', 'removeCSS'})
shared_quotes = set(set_result.values())
check('set shape: every name cites the same shared gate', len(shared_quotes), 1)


# A file with neither shape derives nothing.
NO_MV3_GATE = '''
bool WebExtensionAPICommands::isPropertyAllowed(const ASCIILiteral& name, WebPage*)
{
    if (name == "onCommand"_s)
        return doesDictionaryExist(extensionContext->manifest(), "commands"_s);
    return false;
}
'''
check('no-gate file: derives nothing', derive_mv3_removed_names(NO_MV3_GATE), {})


# Both shapes together derive the union.
COMBINED = DIRECT_SHAPE + '\n' + SET_SHAPE
combined_result = derive_mv3_removed_names(COMBINED)
check('combined shapes: union of both',
      set(combined_result),
      {'browserAction', 'pageAction', 'executeScript', 'getSelected', 'insertCSS', 'removeCSS'})


if failures:
    print(f'{len(failures)} failure(s):')
    for f in failures:
        print(f'  {f}')
    sys.exit(1)

print('derive_mv3_removed_names: all cases passed.')
