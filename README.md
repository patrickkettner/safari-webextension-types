# safari-webextension-types

[![CI](https://github.com/patrickkettner/safari-webextension-types/actions/workflows/ci.yml/badge.svg)](https://github.com/patrickkettner/safari-webextension-types/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-blue.svg)](https://www.typescriptlang.org/)

Authoritative TypeScript declarations for Safari WebExtensions, generated directly from WebKit WebIDL interfaces.

---

## Overview

`safari-webextension-types` provides TypeScript declarations (`.d.ts`) for Safari WebExtensions, generated directly from WebKit's upstream WebIDL interface declarations (`Source/WebKit/WebProcess/Extensions/Interfaces/`).

By parsing the WebIDL `interface`, `dictionary`, and `enum` declarations from WebKit, this package extracts the exact parameter schemas, optionality, and return types validated by WebKit's Cocoa implementation, emitting clean, standard TypeScript types for Safari extension developers and multi-browser toolchains.

---

## Key Characteristics

- **Authoritative Source**: Generated directly from WebKit WebIDL declarations in `Source/WebKit/WebProcess/Extensions/Interfaces/`.
- **Dual API Styles**: Full support for modern `Promise`-based asynchronous APIs and traditional `callback` overloads across all namespaces.
- **Dual Namespaces**: Full support for the standard `browser.*` namespace and Safari's runtime `chrome.*` compatibility namespace.
- **Strict Parameter & Return Dictionaries**: Describes required vs. optional fields based on Cocoa validation tables.
- **Zero Runtime Dependencies**: Pure TypeScript declarations (`index.d.ts`).
- **Reproducible Generator**: Fetches upstream WebIDLs at build time with no local WebKit checkout or compilation environment required.

---

## Installation

```bash
npm install --save-dev safari-webextension-types
```

---

## Usage

### In `tsconfig.json`

Add `safari-webextension-types` to `compilerOptions.types`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "types": ["safari-webextension-types"]
  }
}
```

### Or via Triple-Slash Directive

In any TypeScript file:

```typescript
/// <reference types="safari-webextension-types" />
```

---

## Code Examples

### Tabs API (Promises & Callbacks)

```typescript
// Promise syntax
const tabs = await browser.tabs.query({ active: true, currentWindow: true });
for (const tab of tabs) {
    console.log(`Tab ${tab.id}: ${tab.url} (${tab.title})`);
}

const newTab = await browser.tabs.create({
    url: "https://webkit.org",
    active: true
});

// Callback syntax
browser.tabs.get(newTab.id!, (tab) => {
    console.log("Tab status:", tab.status);
});
```

### Windows & Cookies

```typescript
// Windows
const currentWindow = await browser.windows.getCurrent({ populate: true });
console.log("Window state:", currentWindow.state, "Tabs:", currentWindow.tabs?.length);

// Cookies
const cookie = await browser.cookies.get({
    url: "https://apple.com",
    name: "session_token"
});
```

### Storage & Runtime Events

```typescript
// Storage
await browser.storage.local.set({ theme: "dark", fontSize: 14 });
const settings = await browser.storage.local.get(["theme", "fontSize"]);

// Runtime message listener
browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
    console.log("Received message:", message, "from:", sender);
    sendResponse({ status: "acknowledged" });
    return true; // Keep channel open for async response
});

// Chrome alias namespace
await chrome.storage.local.set({ enabled: true });
```

---

## Architecture

```
+------------------------------------------------------------------------+
|                        WebKit Upstream Source                          |
|        (Source/WebKit/WebProcess/Extensions/Interfaces/*.idl)          |
|                                                                        |
|   WebExtensionAPITabs.idl      WebExtensionAPIWindows.idl      ...     |
|   - dictionary definitions     - enum declarations                     |
|   - interface signatures       - callback attributes                   |
+-----------------------------------┬------------------------------------+
                                    |
                         Fetched via HTTP / API
                                    |
                                    v
+------------------------------------------------------------------------+
|                   safari-webextension-types Generator                  |
|                          (scripts/generate.py)                         |
|                                                                        |
|   1. Parses WebIDL AST (dictionaries, enums, interfaces, overloads)    |
|   2. Maps WebIDL primitives to TypeScript types                        |
|   3. Resolves callback and Promise return signatures algorithmically   |
|   4. Emits browser.* and chrome.* namespaces                           |
|   5. Reconciles: a hand-written signature that matches no parsed       |
|      member, or a parsed member that produced nothing, fails the build |
|   6. Re-resolves every citation against the same WebKit revision       |
+-----------------------------------┬------------------------------------+
                                    |
                                    v
+------------------------------------------------------------------------+
|                               index.d.ts                               |
|              Authoritative Safari WebExtension Declarations            |
+------------------------------------------------------------------------+
```

---

## Building from Source

```bash
# Clone the repository
git clone https://github.com/patrickkettner/safari-webextension-types.git
cd safari-webextension-types

# Install development dependencies
npm install

# Run the generator (fetches upstream WebIDLs)
npm run build

# Run type tests
npm test
```

### Generator CLI Options

```bash
# Default: the pinned WebKit/WebKit commit, recorded in the output header
python3 scripts/generate.py

# Generate from a different revision. Use a commit, not a branch: the
# declarations and the evidence cited for them come from the same revision,
# and a moving ref lets those two drift apart.
python3 scripts/generate.py --repo WebKit/WebKit --ref <sha>

# Resolve a WebKit PR to its head commit and generate from that
python3 scripts/generate.py --pr 71593

# Read sources and citations from a local WebKit checkout instead of github.com
python3 scripts/generate.py --webkit-checkout /path/to/webkit

# Parse interfaces from a directory of .idl files. Citations outside that
# directory still need --webkit-checkout or a reachable revision.
python3 scripts/generate.py --idl-dir /path/to/Extensions/Interfaces/

# Record where every emitted member came from
python3 scripts/generate.py --provenance provenance.json
```

### What the build refuses to do

The generator cannot emit a member WebKit does not declare. Emission iterates
the parsed IDL and looks each member up in a table of hand-written signatures,
so a table entry naming something upstream never had matches nothing and has
nothing to emit. Three checks turn that into a failure rather than a silence:

- a signature entry that matched no parsed member fails the build;
- a parsed member that produced no output and records no reason fails the build;
- every emitted member cites source that is re-read at build time, and a
  citation that no longer resolves fails the build.

A claim that something is absent from WebKit is checked the same way, inverted:
the cited text must still not be there.

---

## Related Projects

- **[W3C WebExtensions Community Group](https://github.com/w3c/webextensions)**: Cross-browser web extension standards
- **[chrome-types](https://github.com/GoogleChrome/chrome-types)**: TypeScript declarations for Chromium extensions
- **[web-ext-types](https://github.com/freaktechnik/web-ext-types)**: TypeScript declarations for Firefox extensions

---

## License

[Apache-2.0](LICENSE) (c) 2026 Patrick Kettner
