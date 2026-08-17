# R1 applied: what the gate found, and what changed

Generator: `/home/pdk/safari-webextension-types/scripts/generate.py`.
All evidence read from WebKit@0136fa2b7cf669ab6bc8e715727e6a78bf5f24ba, the
revision the declarations are now generated from and pinned to.

Nothing is committed.

## The mechanism

Emission iterates the parsed IDL and looks each member up in
`SIGNATURE_OVERRIDES[(interface, member)]`. A table entry for a member WebKit
does not declare matches nothing, so it cannot emit; four conditions abort the
build instead:

| Condition | Verified by |
|---|---|
| override matched no parsed member | re-injected all five shipped fabrications: five errors, no output written |
| parsed member produced no output | deleted the `Port.name` entry: error naming it |
| citation no longer resolves | changed one quoted key constant: error naming the file and the text |
| absence claim falsified | pointed the notifications absence claim at text that is present: error with the line number |

268 members recorded, 330 citations, 42 distinct WebKit files, 74 of the
citations into `.mm`/`.h` implementation rather than IDL. Every emitted member
carries at least one citation and that is itself enforced.

## Found by the reconciliation on its first run

Nine members WebKit declares and the package did not emit. All nine now emit:

`Port.error`, `StorageArea.getKeys`, `setAccessLevel`, `onChanged`,
`QUOTA_BYTES`, and the four sync-only limits.

`isPropertyAllowed` answers false for `QUOTA_BYTES_PER_ITEM`, `MAX_ITEMS`,
`MAX_WRITE_OPERATIONS_PER_HOUR` and `MAX_WRITE_OPERATIONS_PER_MINUTE` on every
area but sync, so they are declared on a `SyncStorageArea` and `storage.sync`
alone has that type.

## Fabricated payloads found while citing the hand-written signatures

| Member | Was | WebKit |
|---|---|---|
| `cookies.onChanged` | `(changeInfo: { cookie; removed; cause })` | `invokeListeners()`, no arguments, under a FIXME saying changeInfo is unimplemented (webkit.org/b/267514) |
| `notifications.onClicked` | `(notificationId: string)` | no dispatch site exists; the whole implementation file is two event accessors |
| `notifications.onButtonClicked` | `(notificationId, buttonIndex)` | same |
| `webNavigation.on*` (5 events) | `WebNavigationGetFrameDetails & { url; timeStamp; transitionType?; transitionQualifiers?; error? }` | `{ url, tabId, frameId, parentFrameId, timeStamp, documentId? }`. `WebNavigationGetFrameDetails` is getFrame's **input** dictionary; the three transition keys do not exist |
| `devtools.inspectedWindow.eval` callback | `(result, exceptionInfo: { isError; code; description; details })` | one argument, the array `[result, errorObject]`, and that object's keys are the literals `"isExceptionKey"` and `"valueKey"` |

The first three now declare `(...args: unknown[]) => void` with `@deprecated`
carrying the reason: an untyped listener still compiles, reading through the
argument needs a guard, and the editor shows the warning. A listener that
annotates its parameter with the old shape stops compiling; the fix is to drop
the annotation.

## Wrong in detail, corrected

| Member | Was | Now |
|---|---|---|
| `runtime.lastError` | `{ message?: string } \| undefined` | `Error \| undefined` |
| `runtime.onInstalled` | `reason: ... \| string`, spurious `id?` | `reason: "install" \| "update" \| "browser_update"`, no `id` |
| `tabs.onActivated` | `{ tabId; windowId }` | `{ previousTabId; tabId; windowId }` |
| `tabs.onUpdated` changeInfo | Chrome's seven keys, incl. `favIconUrl` which no Safari Tab has | `browser.Tab`, since both arguments go through the same `toWebAPI` |
| `menus.onClicked` info | missing `linkText`, `frameId`; `editable` required | both present, `editable` optional, `mediaType` narrowed to the three values |
| `storage.onChanged` | inline `{ oldValue?; newValue? }` | `browser.StorageChange`, the IDL dictionary |
| `InjectionResult.result` | `result?: T` | `result: T \| null`, always set |
| `RegisteredContentScript.world` | `"ISOLATED" \| "MAIN"` | adds the lowercase spellings WebKit actually writes |

Confirmed correct and now citable: `scripting.ExecutionWorld`,
`declarativeNetRequest.getMatchedRules` and `isRegexSupported`, `tabs.onMoved` /
`onDetached` / `onAttached` / `onRemoved`, `commands.onChanged`,
`permissions.onAdded` / `onRemoved`, `runtime.onStartup`, and every key of the
four entity types.

## Removed as dead, proven by regeneration

Three branches of the attribute chain compared against pre-`clean_type` names
(`a_type == 'WebExtensionAPIDevToolsInspectedWindow'` and the two beside it) and
could never fire. Removing them left the output identical.

## Upstream bug candidates this turned up

1. `cookies.onChanged` carries no changeInfo. Already filed as webkit.org/b/267514.
2. `notifications.onClicked` and `onButtonClicked` are declared and never dispatched.
3. `WebExtensionAPIDevToolsInspectedWindowCocoa.mm` builds the eval error object
   with `"isExceptionKey"` and `"valueKey"`, which are the names of the key
   constants rather than their values.

## Fixed after the first pass

`webNavigation.getFrame` / `getAllFrames` were typed
`WebNavigationGetFrameDetails`, which is the dictionary the *details* argument
takes. They now return a cited `FrameDetails`
(`{ errorOccurred, parentFrameId, url, frameId?, documentId? }`), and
`getAllFrames` dropped its `| null`: it maps a `Vector`, so it always yields an
array.

### windows.getLastFocused

Was `Promise<void>`; WebKit resolves `Expected<WebExtensionWindowParameters>`
and calls back with a window. Now `browser.Window`. It had no rule in
`resolve_algorithmic_return_type` and fell through to the default.

### action.getBadgeBackgroundColor is a stub

It sends no message and calls back with the literal `{ 255, 0, 0, 255 }`, so
every extension reading a badge colour on Safari is told opaque red. The
declared `number[]` is correct; the value is not real. Upstream bug candidate.

### sidebarAction.setIcon always rejects

It sends no message and calls `reportError` with "'sidebarAction.setIcon()' is
unimplemented" (webkit.org/b/276833). Already filed upstream. No declaration
changed: `Promise<void>` does not claim a promise resolves.

### tabs.move returns one tab or many

It resolves a `Vector` and unwraps a single-element result, so moving one tab
yields a tab and moving several yields an array. Was declared `browser.Tab`.

### cookies.set and cookies.remove return the cookie

Both were `Promise<void>`. Both resolve
`Expected<std::optional<WebExtensionCookieParameters>>` and call back with
`toWebAPI` of it, the same as `get`. `remove` hands back the whole cookie rather
than Chrome's url/name/storeId subset.

### alarms.create returns nothing

It reaches `callback->call()` with no argument. It was declared
`browser.Alarm` because the generic `create` rule hands over the namespace
primary entity.

### extension.isAllowedFileSchemeAccess is a stub

It sends no message and calls back with a literal `false`, so it always denies.
The declared boolean is correct; the answer is not real. Upstream bug candidate.

### Name matching was overriding declared IDL types

`resolve_algorithmic_param_type` composed candidate dictionary names and took
whichever existed, **before** looking at what the IDL said the argument was. So
`action.enable([Optional] double tabId)` shipped as `browser.ActionDetails` and
`test.notifyFail([Optional] DOMString message)` as `browser.MessageOptions`.
Eight parameters were affected: `action.enable`/`disable`'s `tabId` and six
`message` arguments across `test`.

The candidate search now runs only where the IDL declines to say (`any`, or an
object). Where the IDL states a type, that is the derivation.

### action.openPopup rejected a tabId WebKit accepts

`openPopup` validates its argument through `parseActionDetails` alone, which
accepts `{tabId, windowId}`. The IDL declares
`WebExtensionActionOpenPopupOptions` with only `windowId`, and the generator
matched that name, so `browser.action.openPopup({tabId: 5})` failed to compile
against a call Safari accepts. Now `browser.ActionDetails`.

A parameter that is too narrow rejects valid code, which is the harmful
direction. Upstream bug candidate: the dictionary is missing `tabId`.

### webNavigation.getFrame and getAllFrames permitted a call that fails

Both require their identifiers, while the IDL dictionaries declare every member
optional, so `getFrame({})` typechecked and failed at runtime. `processId` is
declared by the dictionary and never read. Upstream bug candidate on both
counts.

### offscreen.createDocument permitted a call that fails

url, justification and reasons are all required by the implementation and all
optional in `WebExtensionOffscreenCreateParameters`, so `createDocument({})`
typechecked. Upstream bug candidate.

### webRequest details is missing requestBody

`WebExtensionWebRequestDetails` declares 18 members and not `requestBody`, which
the implementation sets whenever a form body is present and the listener asked
for it in extraInfoSpec:

    if (formData && extraInfo.contains(String(requestBodyKey)))
        [details setObject:requestBody forKey:requestBodyKey];

The string `requestBody` does not appear in the IDL at all. `onBeforeRequest`
listeners now receive `WebRequestDetails & { requestBody?: ... }`, intersected
at that one event rather than added to the dictionary; it is the only event
whose dispatch sets the key. Its three keys are read from
`toWebAPI(const WebCore::FormData&)`. Upstream bug candidate stands: the
dictionary should declare it.

Verified at the same time and correct: listeners receive one argument. The tab,
window and resource-load values passed alongside it go to `enumerateListeners`
for filtering and never reach the callback, so the declared arity is right.
Every other key the implementation sets is declared.

The 8 keys always set (frameId, parentFrameId, requestId, timeStamp, url, tabId,
type, method) are declared optional, so listeners must null-check values that
are always present. Under-claim, not a break.

### Review findings, 2026-08-17

An external review of the first 23 commits confirmed the type derivations and
found six defects. Four were mine to fix and are fixed: `sidePanel.getOptions`
declared a `windowId` the function never parses; two error messages instructed
the reader to launder a fresh guess by deleting a ratchet line; two boolean
rules matched on operation name across every namespace; and a comment claimed
both declarativeNetRequest filter keys become required when only `tabId` does.

Two are structural and are NOT fixed. See the worklist.

### action.setBadgeBackgroundColor and runtime.setUninstallURL are stubs

Both call back with no argument because neither does anything. Both carry a
FIXME saying so: rdar://57666368 for the badge colour, rdar://58000001 for the
uninstall URL. Found because a citation extractor walked past the end of each
function looking for an IPC reply that is not there, and attached the next
function's message instead.

Upstream bug candidates, and they pair with the two stubs already recorded:
`getBadgeBackgroundColor` returns a hardcoded red, and
`isAllowedFileSchemeAccess` always answers false.

### Nested key tables were read one level deep

`declarativeNetRequest.setExtensionActionOptions` declared
`tabUpdate?: { tabId?; increment? }`. The outer `validateDictionary` requires
nothing, but `tabUpdate` carries a **second** call requiring both keys
whenever it is present, so `{tabUpdate: {}}` typechecked and threw.

Scanning every `validateDictionary` call site in the API directory for nested
ones found one sibling, in a different shape: `StorageArea.setAccessLevel`
requires `accessLevel` and constrains it to two literals, while
`WebExtensionStorageAccessOptions` declares it optional and untyped.

Uncovered class for the gate list: a parameter's key table may contain another
key table, and nothing forces the reader down.

### Runtime rules the types do not express

Listed here because a TypeScript object type cannot state them, and because a
list in one place beats a sentence in each commit.

Mutual exclusions, each enforced by the implementation:
- `sidebarAction.*` details: `tabId` and `windowId` cannot both be given.
- `tabs.sendMessage`/`connect` options: `frameId` and `documentId` cannot both.
- `alarms.create` info: `when` and `delayInMinutes` cannot both; `name` cannot
  appear when it is also the first argument.
- `scripting` targets: `allFrames` and `frameIds` cannot both.

Conditional requiredness:
- `declarativeNetRequest.getMatchedRules`: `tabId` is required only for an
  extension without the feedback permission.

### DNRTabUpdateOptions declared `count`; Safari reads `increment`

WebKit's own IDL dictionary has the wrong member name: `setExtensionActionOptions`
validates the nested `tabUpdate` against `@[ actionCountTabIDKey,
actionCountIncrementKey ]`, both required, and `actionCountIncrementKey` is
`"increment"`. Our emitted `browser.DNRTabUpdateOptions` copied the IDL and so
had a key Safari never reads. Now corrected and cited. Upstream fix is A5 in
UPSTREAM-DRAFTS.md.

## Still open
- The 130 members emitted by the algorithmic path cite their IDL declaration but
  not the source of their return shape.
- `webRequest` event details are `browser.WebRequestDetails` from the IDL and
  were not checked against the dispatch site.
- R2 (parse-coverage gate, derived file list) and the rest of R3 are untouched.
  The interface list is now reconciled: an interface WebKit adds fails the build
  until it is given a disposition. The *file* list is still hand-maintained.
