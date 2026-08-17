# Worklist: citing the algorithmic return shapes

Untracked working file. Safe to abandon at any line; the status column is the
only state that matters.

## The problem

`resolve_algorithmic_return_type` in `scripts/generate.py` maps an operation to
a return type. Those mappings are Chrome-documentation knowledge written as
code. 130 emitted operations cite the IDL line that declares them and nothing
for the shape they resolve to, so an operation can claim a payload WebKit never
sends, or claim `void` where WebKit sends something.

## Method, one namespace per chunk

1. Read `Source/WebKit/WebProcess/Extensions/API/Cocoa/WebExtensionAPI<Ns>Cocoa.mm`
   at the pinned revision:
   `cd /home/pdk/webkit && git show 0136fa2b7cf669ab6bc8e715727e6a78bf5f24ba:<path>`
2. For each operation, find its `callback->call(...)`. That argument is the
   payload. No `callback->call` with a value means the callback takes nothing,
   so `Promise<void>` is correct.
3. Fix what disagrees:
   - payload is a dictionary with literal keys -> add a cited `ENTITY_TYPES`
     entry and point the resolver at it. `FrameDetails` is the worked example.
   - payload is a scalar or an existing IDL dictionary -> point the resolver at
     that, no new type.
   - source does not say -> widen to `unknown` and record it here. A widened
     type is the absence of a claim, which is honest. A guessed shape is not.
4. `python3 scripts/generate.py --webkit-checkout /home/pdk/webkit`
   then `npm run typecheck && npm test`.
5. Update the row below, and add anything found to `R1-FINDINGS.md`.

Tests written from the emitted output pass vacuously when every member of a
type is optional. Assert members individually.

## The 43

`--provenance` now tags every operation that reached the resolver's fall-through
and was declared `void` with no rule behind it. `windows.getLastFocused` was one
of these and was wrong. Count them with:

    python3 scripts/generate.py --webkit-checkout /home/pdk/webkit --provenance /tmp/p.json
    python3 -c "import json;d=json.load(open('/tmp/p.json'));print(sum(1 for m in d['members'] if m['origin'].endswith('unresolved-payload')))"

0 today, down from 43. The file is now only its header. Five of them (`bookmarks.remove`/`removeTree`, `menus.remove`/
`removeAll`, `windows.remove`) have since been read and are genuinely void, so
the honest number of unverified ones is 38. This count must only ever go down.

When a chunk confirms an operation really does call back with nothing, give it
an explicit rule returning `'void'` rather than leaving it on the fall-through.
That is what moves the number.

Read `POSTMORTEM-algorithmic-return-types.md` before starting: it explains why
these are wrong more often than they look.

## Chunks

| # | Namespace | Ops | Status |
|---|---|---|---|
| 1 | windows | 7 | DONE, see below |
| 2 | tabs | 21 | DONE |
| 3 | action | 13 | DONE |
| 4 | bookmarks | 11 | DONE |
| 5 | runtime | 10 | DONE |
| 6 | declarativeNetRequest | 9 | DONE |
| 7 | sidebarAction | 9 | DONE |
| 8 | test | 7 | DONE |
| 9 | scripting | 6 | DONE |
| 10 | alarms | 5 | DONE |
| 11 | cookies | 5 | DONE |
| 12 | i18n | 5 | DONE |
| 13 | sidePanel | 5 | DONE |
| 14 | permissions | 4 | DONE |
| 15 | extension | 3 | DONE |
| 16 | menus | 3 | DONE |
| 17 | offscreen | 3 | DONE |
| 18 | commands | 1 | DONE |
| 19 | dom | 1 | DONE |
| - | webNavigation | 2 | DONE, shipped as `FrameDetails` |

## Suspicions noted while taking the inventory, not yet checked


## Chunk log

### 1. windows

Read `WebExtensionAPIWindowsCocoa.mm`, checked all 7 against their
`callback->call`. One defect, now fixed:

- `getLastFocused` was `Promise<void>`. It matches no verb rule in
  `resolve_algorithmic_return_type`, so it fell through to the `void` default,
  while WebKit resolves `Expected<WebExtensionWindowParameters>` and calls back
  with a window. Now `browser.Window`.

Confirmed correct, no change: `get`, `getCurrent`, `update` (plain
`WebExtensionWindowParameters`), `getAll` (a `Vector`), `remove`
(`callback->call()` with no argument), and `create`, whose `| undefined` is real
because it alone resolves a `std::optional`.

Lesson for the remaining chunks: the failure mode here was an operation falling
through to the default rather than a wrong rule. Check the `void` ones as
carefully as the rest.

### 2. menus

All four operations resolve `Expected<void>` and reach `callback->call()` with
no argument. One defect, now fixed:

- `update` was `Promise<browser.MenuItemProperties>`. The generic update/move
  verb rule hands an operation its namespace's primary entity, and menus' is
  `MenuItemProperties`. Now `void`.

`remove` and `removeAll` were already `void`. `create` carries an override, so
the `menus.create` branch of the resolver is unreachable and was left alone.

Take the small namespaces first, not the table order. Two chunks have each
found exactly one defect and cost little.

### 3. bookmarks

Checked all 11 against their `callback->call`. One defect, now fixed:

- `get` was a single `BookmarkTreeNode`. It takes an id or a list of them and
  calls back with `resultArray` either way. Now `BookmarkTreeNode[]`.

Correct already: `create`, `move` and `update` call back with one node
dictionary; `getChildren`, `getRecent`, `getSubTree`, `getTree` and `search`
call back with an array; `remove` and `removeTree` reach `callback->call({ })`
with no argument.

Three chunks, three defects, all of them a generic verb rule firing on an
operation it did not fit. That is the pattern to expect.

### 4. action

All 13 read. No wrong types: `getTitle`, `getBadgeText` and `getPopup` call back
with a string, `isEnabled` with a boolean, `getBadgeBackgroundColor` with a
four-element array. The other 8 reach `callback->call()` with no argument and
moved from the ratchet into `CONFIRMED_EMPTY_CALLBACKS`, which is where a void
goes once it has been read.

That table is also where `menus.update` and the other already-confirmed voids
now live, so the ad-hoc branch for it is gone. 43 unresolved became 30, with the
output byte-identical: this chunk changed no type, it changed what is known
about them.

Worth knowing: `getBadgeBackgroundColor` sends no IPC at all. It calls back with
a literal `{ 255, 0, 0, 255 }`. The type is right and the value is a stub.

### 5. sidebarAction

`isOpen` returns a boolean, `getPanel` a `panelPath` string, `getTitle` a
string. `open`, `close`, `toggle`, `setPanel` and `setTitle` call back empty and
moved into `CONFIRMED_EMPTY_CALLBACKS`. 30 unresolved became 24.

`setIcon` sends nothing and calls `reportError` with
"'sidebarAction.setIcon()' is unimplemented", so its promise always rejects. It
briefly got a `@deprecated` doc comment for that. **Reverted**: no type was
wrong. `Promise<void>` never claimed it resolves and TypeScript has no rejection
type. The behaviour is recorded in `R1-FINDINGS.md`, which is where a browser
bug that breaks no declaration belongs. See CLAUDE.md rule 6.

Do not annotate an unimplemented operation unless its type is also wrong.

### 6. tabs

All 21 read. One defect:

- `move` was `browser.Tab`. It resolves a `Vector` and unwraps it: one tab moved
  comes back as the tab, more than one as the array. Now
  `browser.Tab | browser.Tab[]`.

Eight voids confirmed (`goBack`, `goForward`, `insertCSS`, `reload`, `remove`,
`removeCSS`, `setZoom`, `toggleReaderMode`), taking the ratchet from 24 to 16.

Two nullables checked and kept: `getCurrent` and `duplicate` both resolve
`Expected<std::optional<...>>`. `getSelected` earns its `| undefined` the other
way, by reaching a bare `callback->call()` when no tab is selected.

The `tabs.executeScript` suspicion was wrong. It passes
`returnExecutionResultOnly = true`, which returns the bare values rather than
injection results, so `unknown[]` is right.

### 7. declarativeNetRequest

No defects. `getEnabledRulesets` returns a string array, `getMatchedRules` the
`rulesMatchedInfo` wrapper, `isRegexSupported` the `isSupported`/`reason` pair.
The four unresolved operations all call back empty; 16 became 12.

The suspicion about `getDynamicRules` and `getSessionRules` was unfounded. Both
hand back `fromJSON(parseJSON(...))` of whatever was stored, so
`Record<string, unknown>[]` is an honest widening rather than a guess.
Tightening it to `DNRRule[]` would need the write-path validation read first,
and is not worth doing on the strength of the name.

First chunk to find nothing wrong. That is a result too: the ratchet moved
because four operations became readings.

### 8. scripting

No wrong types. `executeScript` and `getRegisteredContentScripts` both hand back
`toWebAPI` of what they resolved, matching what was declared. The other five
call back empty and are now recorded, taking the ratchet from 12 to 9.

The cleanup here matters more than the count. `registerContentScripts` and
`updateContentScripts` were being declared void by a `'get' in op_name`
substring test, which is rule 2's antipattern in miniature: an operation named
`getSomethingRegistered` would have picked up the array type from spelling
alone. That branch is gone, and the two voids are readings instead.

Look for the same shape elsewhere in the resolver. A test on part of a name is
never evidence.

### 9. sidePanel, and the last name test

No wrong types. `getPanelBehavior` hands back a dictionary keyed by
`actionClickBehaviorKey`, which is `@"openPanelOnActionClick"`, matching the IDL
dictionary already declared. `getOptions` serialises the sidebar parameters.
`open`, `setOptions` and `setPanelBehavior` call back empty; 9 became 6.

The sweep the last chunk asked for found one remaining name test, and it turned
out to decide nothing:

    if op_name.startswith('is') or op_name.startswith('has') or op_name in (...)

Every branch inside it was an exact `ns_name`/`op_name` match, so the prefix
test only hid that. Flattened, and the output is identical. That is the whole
standard of proof for a claim like this.

The resolver now has no test on part of a name anywhere.

### 10. cookies, offscreen, runtime. Ratchet cleared.

Two defects, both in cookies:

- `set` and `remove` were `Promise<void>`. Both resolve
  `Expected<std::optional<WebExtensionCookieParameters>>` and hand back
  `toWebAPI` of it, exactly as `get` does. Now `browser.Cookie | null`.
  Worth knowing: `remove` yields the whole cookie, not Chrome's
  url/name/storeId subset.

offscreen and runtime were sound. `hasDocument` returns a boolean,
`getPlatformInfo` the platform object, `getBackgroundPage` a window or null.
Four empty callbacks confirmed.

**Unresolved payloads: 0.** Every operation that was being declared void on no
evidence has now been read.

## What zero does not mean

The ratchet only ever tracked operations that matched *no* rule. An operation
whose verb rule happens to fire is not in it, and was never in it. Ten
namespaces have still not been read at all: alarms, commands, dom, extension,
i18n, notifications, permissions, storage, test, webRequest. Their types come
from the same verb table that was wrong six times.

`unverified-returns.txt` now applies the same pressure to exactly this gap. It
lists every operation taking its type from the verb table in a namespace nobody
has read: **13 operations across alarms (5), commands (1), dom (1), extension (3), i18n (5), permissions (4), test (7)**. A namespace leaves by being read and
added to `READ_NAMESPACES`; the build fails on a new entry and on a stale one.

The remaining namespaces with nothing in that file (dom, notifications, storage)
declare no algorithmic operations at all, so there is nothing there to verify.

### 11. alarms, commands, permissions, extension

One defect:

- `alarms.create` was `browser.Alarm`. It reaches `callback->call()` with no
  argument; the generic `create` rule had handed it the namespace primary. Now
  void. Note alarms lives in `WebExtensionAPIAlarms.cpp`, not a Cocoa file, so
  the usual path did not find it.

Everything else checked out. `alarms.get` earns its `| undefined` through
`UseNullValue::No`, `clear`/`clearAll` return booleans, `commands.getAll`
returns the command array, `permissions.getAll` builds exactly the
permissions/origins pair already declared, and the two `extension` access
checks return booleans.

Unverified returns 26 to 13. Only i18n, test and webRequest left.

Worth knowing: `extension.isAllowedFileSchemeAccess` sends no IPC and calls back
with a literal `false`, so it always denies. Same class as
`action.getBadgeBackgroundColor`. The declared boolean is right; the answer is
not real.

### 12. dom, i18n, test. Both ratchets cleared.

No defects. `i18n`'s five all hand back exactly what they say: the accept
languages array, `NSLocale.preferredLanguages`, `NSLocale._deviceLanguage`, and
two synchronous strings. `test`'s seven are synchronous voids plus
`isProcessingUserGesture`, which returns a bool. `dom.openOrClosedShadowRoot`
returns `[element valueForProperty:...]`, so `unknown` is right.

A correction to the previous entry: the last three namespaces were dom, i18n and
test. An earlier summary said webRequest, which was wrong.

**Both ratchets are empty.** Every operation's return type has been read from
the implementation at the pinned revision.

## What is still unread

20 of 24 namespaces are in `READ_NAMESPACES`. The four outside it (devtools,
notifications, storage, webRequest) declare no operations at all, only
attributes, so there is nothing for either ratchet to hold. If any of them ever
gains an operation it lands in `unverified-returns.txt` on the next build and
fails it, which is the property we wanted.

## The next surface, and it is the same bug

`resolve_algorithmic_param_type` decides **parameter** types the way the return
resolver decided return types: by composing candidate dictionary names out of
the namespace, operation and argument spelling, then taking whichever one
happens to exist.

    candidates = [f"{ns_cap}{op_cap}{arg_cap}", f"{ns_cap}{op_cap}Details", ...]

That is the mechanism this whole document exists because of, applied to the
other half of every signature, and nothing checks it. Two ratchets now cover
return types and none covers arguments.

`unverified-parameters.txt` now holds that surface: **0 parameters** across
action (13), declarativeNetRequest (1), offscreen (1), permissions (3), sidePanel (4), sidebarAction (6), test (6), webNavigation (2). Same two-sided ratchet, proven both ways.

Method: the `.mm` validates incoming dictionaries with
`validateDictionary(dict, name, requiredKeys, keyTypes, ...)` against static
literal tables listing the accepted keys and their classes. Read that, then
either name the dictionary explicitly or widen the parameter. Note the reverse
risk here: unlike a return type, a parameter that is too narrow rejects valid
code, and one that is too wide only fails to catch a mistake. Widen when
unsure.

Measured alongside it, for scale: 47 parameters take their type straight from
the IDL, 29 are already widened to `Record<string, unknown>`, and 10 are
hand-written special cases.

### 13. Parameters: the candidate search was outranking the IDL

The first read of `unverified-parameters.txt` found the worst defect of the
session before any `.mm` was opened. `action.enable(tabId)` was typed
`browser.ActionDetails`, and the IDL says `[Optional] double tabId`.

The candidate loop ran before anything consulted the declared type, so any
argument whose name composed into an existing dictionary name took that
dictionary regardless of what the IDL stated. Eight parameters were wrong:
`action.enable`/`disable` and six `message` arguments in `test` that became
`browser.MessageOptions`.

The search now runs only where the IDL declines to say: `any`, or an object.
Where the IDL states a type, that is the derivation. 36 candidate-name
parameters became 28, and the eight that left are fixes rather than readings.

Two lessons for the rest of this list. Look at the emitted signature before
opening the implementation, because a guess that contradicts the IDL is visible
without leaving the repository. And prefer a structural fix over draining
entries one by one: this took one guard and corrected eight declarations.

### 14. action parameters

Every `action` operation taking `details` routes it through
`parseActionDetails`, which accepts `{tabId, windowId}`; setters validate one
further key on top. The IDL dictionaries already carry all three, so ten of the
eleven guesses were right, and are now recorded as readings in
`PARAMETER_TYPES` rather than left to the name match.

One was wrong. `openPopup` validates through `parseActionDetails` alone, so it
accepts `tabId`, but `WebExtensionActionOpenPopupOptions` declares only
`windowId`. Calling `openPopup({tabId: 5})` failed to compile against a call
Safari accepts. Now `browser.ActionDetails`.

`PARAMETER_TYPES` is the drain for this ratchet: an entry leaves by being read
from the operation's own validation, whether the reading confirms the guess or
replaces it. 28 became 17.

Note the asymmetry that made this one matter. A return type that is too wide
merely under-informs. A parameter that is too narrow rejects correct code, so
the guesses to distrust most are the specific-looking ones.

### 15. sidebarAction parameters

Five guesses held. `parseSidebarActionDetails` accepts `tabId` or `windowId`,
never both, and the setters validate one further key, which is what the IDL
dictionaries already say.

`isOpen` was the exception, and the implementation says so in a comment: "we
don't use parseSidebarActionDetails here because we only need windowId for
isOpen". It was declared `SidebarActionDetails`, which offers a `tabId` the
operation never reads. Now `{ windowId?: number }`.

That narrows a parameter, against the general advice to widen. The advice is
for uncertainty, and there is none here: the source states the intent. The
trade is that `isOpen({tabId: 1})` stops compiling, which converts a call that
silently returned a window-level answer into a compile error.

`setIcon` validates nothing at all, being unimplemented, so its dictionary is
simply what WebKit declares for it. 17 became 11.

### 16. permissions and webNavigation parameters, and how validateDictionary behaves

`permissions` held: `parseDetailsDictionary` validates exactly
`{permissions?: string[], origins?: string[]}` with no required keys, which is
what the IDL declares.

`webNavigation` did not. Both operations require their identifiers, while the
IDL dictionaries declare every member optional, so the declared form permitted
`{}` and failed at runtime. Now `{ tabId: number; frameId: number }` and
`{ tabId: number }`.

**Read `validateDictionary` before reasoning about extra keys.** I assumed it
rejected keys it was not given a type for, which would have made
`WebNavigationGetFrameDetails.processId` a call that fails. It does not:

    if (!requiredKeysSet.contains(key) && !optionalKeysSet.contains(key))
        continue;

Unknown keys are ignored. So a too-wide parameter type never breaks a call, it
only hides a typo or a no-op, and the defect worth hunting is requiredness
rather than extra members. `processId` is dropped from the emitted type because
declaring it invites a silent no-op, not because it would be rejected.

11 became 6. Left: sidePanel (4), offscreen (1), declarativeNetRequest (1).

### 17. sidePanel, offscreen, declarativeNetRequest. All three ratchets cleared.

- `offscreen.createDocument` requires url, justification and reasons, while the
  IDL declares all three optional, so `createDocument({})` typechecked and
  failed at runtime. Now required.
- `sidePanel.getOptions` and `open` parse only tabId and windowId, so the
  `enabled` and `path` members they were declared with would have been ignored.
- `sidePanel.setOptions`, `setPanelBehavior` and
  `declarativeNetRequest.getMatchedRules` held. The last one is optional for a
  good reason: its keys become required only for an extension without the
  feedback permission, which a type cannot express.

**All three ratchets are empty.** Every operation's return type and every
parameter type in the package has been read from the implementation at the
pinned revision, or is a widening that claims nothing.

## What the three files guard now

Nothing is left to drain, so from here they are pure regression gates. Each
fails the build in both directions:

| File | Catches |
|---|---|
| `unresolved-payloads.txt` | an operation newly declared void because no rule matched |
| `unverified-returns.txt` | an operation in a namespace nobody has read |
| `unverified-parameters.txt` | a parameter newly typed by composing a dictionary name |

A new upstream operation lands in one of them on the next build. That is the
point: the generator can no longer quietly guess, in either half of a signature.

## The fourth surface: event payloads have no gate

Operations are fully covered. Event attributes are not, and nothing measures
them.

`derive_attribute_lines` picks an event payload from the attribute's IDL type:
a `WebRequestEvent` becomes `events.WebRequestEvent<(details:
browser.WebRequestDetails) => void>`, and anything else Event-typed falls back
to an open argument list. The first is a name match of exactly the kind the
three ratchets exist to catch, and it is not recorded anywhere.

Reading webRequest found the association is right and the dictionary is
incomplete: `requestBody` is set by the implementation and absent from the IDL,
so a listener cannot read it. Fixing that needs a way to override a member of an
IDL-derived dictionary, which does not exist yet. Every other event payload is
either a cited `SIGNATURE_OVERRIDES` entry or the open fallback.

A fourth ratchet turned out to be the wrong shape for this. An event type the
generator does not recognise falls into the open-argument-list branch, which
claims nothing, so a new upstream event cannot produce a guess the way a new
operation could. Only one mapping was ever an assertion, and a ratchet holding
one entry is worse than making that entry explicit.

So `EVENT_PAYLOADS` holds the type-keyed payload, and `ATTRIBUTE_PAYLOADS`
holds one attribute's exception to it. `requestBody` is intersected into
`onBeforeRequest` alone: `requestBodyKey` is set at exactly one dispatch in the
implementation, inside that event's `enumerateListeners`, and the other eight
never see it. The first version intersected it into all nine, which declared an
optional key that never appears on eight of them. Benign direction, but a
reads-versus-declares miss all the same, and the reviewer caught it.

Measure the surface before building the gate. The three ratchets were worth it
because operations fail *open* into a confident guess; attributes fail *closed*
into a widening.

## Parse coverage: the input side

Every non-blank line of every fetched IDL must now either produce a member or
match an explicit ignorable pattern (declaration headers, extended-attribute
blocks, closing braces). Anything else fails the build with the file, line and
text. Previously the parser dropped syntax it did not understand in silence,
and a dropped member with no override entry was invisible.

Two false passes on the way, both worth knowing about because both looked like
success:

1. Consumption was recorded when a source span was *created*, which happens
   before any rule matches, so every statement counted as parsed. The gate
   reported "all lines accounted for" and would have caught nothing. It now
   marks a line only where a rule produced a member.
2. A statement begins immediately after the previous statement's semicolon, so
   its raw offset lands on the previous line and marked that line parsed. The
   span now skips leading whitespace.

Both were found by feeding the generator an IDL containing `readonly
maplike<...>`, which no rule handles. Neither would have been found by reading
the gate, and after the first fix the count still moved by exactly one line,
which is what gave the second away. Test a gate by breaking the thing it
watches, and check the number, not just the exit status.

## The interface file list

`KNOWN_IDL_FILES` is now reconciled against a listing of the revision, from
`git ls-tree` on a checkout and the GitHub contents API remotely. A file
upstream that is not in the list fails the build, and so does a listed file the
revision does not have. Both proven by breaking them, and the remote path was
exercised too, not just the fast local one.

This closes the last place a whole namespace could go missing without anything
noticing. Everything else reconciles what is inside the files we fetch, so a new
`WebExtensionAPIFoo.idl` was not a missing interface, it was a namespace nothing
ever looked for.

## Provenance, shipped

Two changes make the package re-verifiable by someone who trusts neither this
repository nor its author.

`--ref` is resolved to a sha once, up front, and the resolver is rebuilt on it.
A branch name is still accepted and is recorded as the commit it pointed at, so
the listing, the fetch and the citation checks cannot straddle three revisions
of a moving branch. The resolved sha is what appears in the output header.

`provenance.json` is written on every build and is now a published file. It
carries all 273 members with the revision, and 271 of them with citations that
the build re-resolved: the two without are the recorded skips, which declare
nothing. A reader can take any member, follow it to a file and quoted line at a
named commit, and check it without running anything here.

CI diffs it alongside `index.d.ts`, so it cannot drift from the declarations it
describes.

## Widened parameters: declarativeNetRequest

29 parameters are `Record<string, unknown>`, which is honest but says nothing.
They were widened because no dictionary name composed, not because the accepted
keys are unknown: each operation validates a literal table.

The four in declarativeNetRequest now carry those keys, read from their
`validateDictionary` calls. `addRules` stays `Record<string, unknown>[]` because
the table only says `@[ NSDictionary.class ]`, an array of unspecified objects.

Two mistakes here worth carrying forward. `browser.DNRRule` was reached for
because `NAMESPACE_PRIMARY_ENTITIES` names it, and no such type is emitted:
check that a type exists before referring to it. And the failure surfaced only
because tsc printed it, not because the check failed, which is CLAUDE.md rule
10.

### windows

All six read. The four lookups take a populate flag and a window-type filter,
now `WindowQueryOptions`. `update` takes state, focused and a geometry
rectangle, now `WindowUpdateOptions`. `create` runs `parseWindowUpdateOptions`
before adding its own four keys, so it is declared as an intersection rather
than a copy: the relationship is in the source, and duplicating the six members
would let the two drift.

Both new types are cited member by member, so they are readings in the same
sense as `CookieStore` and `FrameDetails`.

### tabs

All eleven read. Three new cited types: `TabUpdateOptions`, `TabQueryOptions`
(fifteen keys) and `TabScriptInjection`, shared by executeScript, insertCSS and
removeCSS.

Two chains are declared as intersections rather than copies, because the source
chains them: `create` runs `parseTabUpdateOptions` before its own four keys, and
`connect` runs `parseSendMessageOptions` before adding `name`. `move` requires
`index`, which is the only required key in the namespace.

`connect` was the one place I nearly guessed. The grep showed a table holding
only `name`, and reading the function showed it delegating first, so the
declared type would have been missing `frameId` and `documentId`. A grep hit is
not the function.

### cookies

All four share `parseCookieDetails`, which accepts `{name, storeId, url}` and
takes its **required keys from the caller**, so the four differ only in what
they demand: `get` and `remove` require name and url, `set` requires url,
`getAll` requires nothing and validates four filter keys of its own.

That is invisible from the validation table alone. The table is one shared
function; the requiredness lives at each call site, and reading only the table
would have declared four identical types where the real ones differ.

### scripting and alarms

`insertCSS` and `removeCSS` share `CSSInjection`, whose `target` is required and
chains `parseTargetInjectionOptions`, itself requiring `tabId`. Both are cited
types now. `alarms.create` takes the four keys its JSON validation lists.

Neither type can express what the source also enforces: `allFrames` and
`frameIds` are mutually exclusive, as are `when` and `delayInMinutes`, and
`name` may not appear in the info object when it is also the first argument.
Those stay runtime errors, and the comments say so rather than pretending the
type covers them.

### menus, and the last widening

`update` shares `parseCreateAndUpdateProperties` with `create`; `title` is
required only for create, and only when the item is not a separator, so update
requires nothing. Fourteen keys, every string copied out of the keys header
rather than inferred: `documentUrlPatterns` and `targetUrlPatterns` are spelled
differently from their constants, and `icon_variants` is snake case.

The `#if ENABLE(WK_WEB_EXTENSIONS_ICON_VARIANTS)` guard looked like a decision
about claiming build-dependent availability. It is not: the flag defaults to
`ENABLE_WK_WEB_EXTENSIONS`, so it is on wherever the API exists at all. Reading
the definition turned a judgement call back into a fact, which is worth trying
before asking.

## Every parameter, accounted for

    read          57   from the operation's own validation
    idl-type      55   the IDL states the type
    special-case  10   hand-written rules
    widened        0
    candidate-name 0

### The last ten

All read. Nine held: `tabs` validates numbers or an array of them, `bookmarks`
strings or an array of them, `i18n` a string or an array, menus identifiers are
the same string-or-number its create table accepts, and scripting parses an
array of registered scripts.

One did not. `runtime.getFrameId` and `getDocumentId` were declared
`browser.MessageSender | globalThis.Window`. Both resolve their argument with
`WebFrame::contentFrameForWindowOrFrameElement`, so it is a window object or a
frame element. A `MessageSender` was never accepted there.

    read      67
    idl-type  55

Every parameter is now either read from the implementation or stated by the
IDL. Nothing is guessed, widened, or matched on a name.

## Outstanding from the 2026-08-17 review

Two structural findings, neither fixed. Both are the same gap, and the
postmortem already named it as step 5: cite the right-hand side.

### The three ratchets stopped constraining anything

They drove the existing debt to zero and then went quiet. Two holes, both
confirmed:

- A **new** wrong rule in a namespace already in `READ_NAMESPACES` lands in no
  list. A rule matched, so it is not an unresolved payload; the namespace is
  read, so it is not an unverified return. Nothing fires.
- Every exit mechanism is an uncited Python line. One entry in
  `READ_NAMESPACES` blesses a whole namespace; one tuple in
  `CONFIRMED_EMPTY_CALLBACKS` or `PARAMETER_TYPES` clears an entry while
  carrying no evidence. Unlike `Cite`, nothing forces anyone to have looked.

Fix: require a `Cite` on every entry in those three tables, resolved by the
existing mechanism.

**Done for `CONFIRMED_EMPTY_CALLBACKS`.** All 45 entries carry a line proving
the callback takes no argument, and the build rejects a quote that stops
resolving **or that occurs more than once in its file**. Uniqueness is an
invariant the resolver enforces, not something checked once and written down.
Both paths proven by breaking them.

Two lessons paid for here. The extractor keys on the IPC reply resolving
`Expected<void>`, and two operations have no IPC at all because they are
unimplemented stubs: `action.setBadgeBackgroundColor` and
`runtime.setUninstallURL`. It walked past the end of each function and attached
**the next function's message**, which resolved fine and identified the wrong
code. Widening the search window turned a silent miss into a silent wrong
answer, which is worse. Both now cite their own FIXME and call.

The correspondence check that found it is worth keeping by hand until it is a
gate: for every entry, the `Messages::WebExtensionContext::<Name>` in the quote
should relate to the operation. Seven looked odd, five were legitimate aliases
(`disable` sends `ActionSetEnabled`), two were the defect.

**Done for `PARAMETER_TYPES` (68) and `READ_NAMESPACES` (20).** Parameters
pair a unique signature with the shared validation line. `READ_NAMESPACES`
turned out to be standing in for 85 payload-bearing operations with no
return-side citation; those are `RETURN_EVIDENCE` now, 75 extracted and 10
read by hand, and the build fails if any operation in a read namespace is in
neither table or in both. 780 citations. No evidence-free table remains. For parameters the
citation is the operation's `requiredKeys` array and `keyTypes` table, which are
often shared between operations, so uniqueness will need the enclosing function
signature spliced in. Note the reviewer's caution: whitespace-collapsed matching
lets a quote span unrelated lines, so extend quotes deliberately and check the
occurrence count every time.

### 17 of 385 citations do not identify what they cite

Measured, not suspected:

    python3 - <<'EOF'
    # counts occurrences of each quote in its file, whitespace-collapsed
    EOF

`mutedKey: @YES.class,` appears in both `parseTabUpdateOptions` and
`parseTabQueryOptions`, and `TabUpdateOptions` cites it. The citation proves the
key is validated somewhere in the file, not that this operation validates it.
Same for `allFramesKey`, `filesKey`, `targetKey`, `documentIdKey`, `frameIdKey`,
`pinnedKey`, `selectedKey`, `highlightedKey`, and the two `runtime` event
attributes whose IDL lines are identical.

Fix: require a quote to occur exactly once in its file, and extend the 17 to
include a distinguishing neighbour. Note the related weakness the reviewer
identified: whitespace-collapsed matching lets a quote span structurally
unrelated lines, and this repository has written such quotes on purpose. A
uniqueness rule does not solve that; nothing cheap does.

### Also outstanding

Commits 24 to 37 were not reviewed. That includes `check_parse_coverage`, the
citation resolver and the six key-set commits, which is the majority of the risk
surface by the reviewer's own ranking. Treat the first 23 as cleared and the
rest as unexamined.

## The reviewer's remaining items, unstarted

Ordered as given, by leverage.

2. **Complement invariant.** Replace debt-set membership with
   *debt-listed union evidence-bearing = all operations*, reconciled both ways.
   Absence from a debt list currently implies nothing, which is why a fresh rule
   in a read namespace lands nowhere. Under the invariant, "delete the line"
   becomes safe advice because deletion without evidence fails the other side,
   so the error message gets fixed by making it true rather than by rewording it,
   which is all this session did.

3. **Extract, then debt what resists.** `requiredKeys`, `keyTypes` and
   empty-versus-payload `callback->call` are mechanically recoverable for the
   straightforward cases; the empty-callback work above is proof, at 42 of 45
   automatic. Demote the hand tables to a diff against extraction. Chained
   parsers (cookies' per-call-site required keys, `tabs.connect` delegating
   first) will resist, and that is the design: unextractable degrades to
   *listed*, never to *silent*. Do not force those.

4. **Ratchet the resolver out of existence.** Count the branches in
   `resolve_algorithmic_return_type` and drive the count down; assert every
   remaining branch is namespace-qualified. That second check would have caught
   the false claim in commit 13 as a build failure rather than leaving it for a
   reviewer.

5. **Every gate ships a committed red fixture.** Done: `test/red/run.py`,
   six cases, in CI as `npm run test:red`, verified over the network from a
   clean clone. Add a case whenever a gate is added.

6. **Ban load-bearing facts from prose.** Now CLAUDE.md rule 12. Two false
   claims about WebKit shipped in comments because nothing checks prose.

## Uncovered classes, collected

The review asks for defect-to-gate mapping. These have no gate and no rule:

1. **Nested key tables.** A parameter's `validateDictionary` may contain
   another. Found two, one per shape: a nested required pair, and a required key
   the IDL declares optional. Scan with a grep for every `validateDictionary`
   call site whose first argument is not the parameter.
2. **IDL dictionary members are never checked against the implementation.**
   `WebRequestDetails` is missing `requestBody`.
3. **Conditional availability.** `Conditional=`, `[Dynamic]`, `[Platform]`.
   Note the coupling the reviewer found: the parse-coverage pattern
   `^\s*\w+(=[\w&|\s]+)?,?\s*$` exists to eat `Conditional=…` continuation
   lines, so the gate's definition of accounted-for **includes discarding
   availability semantics**. When conditionals get modelled, that pattern must
   narrow in the same commit or the model will silently miss what WebKit adds.
4. **Event filter arguments.** `WebExtensionAPIWebNavigationEvent` and
   `WindowsEvent` take an `addListener` filter that is not represented. Recorded
   in `INTERFACE_SKIPS`.
5. **Mutual exclusions are not expressible in types.** `parseSendMessageOptions`
   rejects `frameId` with `documentId`; `parseSidebarActionDetails` rejects
   `tabId` with `windowId`; scripting rejects `allFrames` with `frameIds`;
   `alarms.create` rejects `when` with `delayInMinutes`, and `name` in the info
   object when it is also the first argument. Flat optional types admit all of
   them. Policy belongs in CLAUDE.md rule 8, and the list belongs here.
6. **Parse coverage is line-granular.** A new extended attribute inside an
   already-matching statement consumes its lines and is invisible; enum bodies
   are bulk-consumed, so an unparseable value line counts as accounted for.
   Item 5's fixtures need an intra-statement case, not just the maplike one.

## Provenance of f1f0e77, and what it says about this session

The reviewer flagged that a commit had been attributed to them on the strength
of its content matching what they would have done. They have no write access
here, so that was plausibility used as proof of authorship: the fabrication move
aimed at a new target.

The reflog settles it without asking anyone:

    f1f0e77 HEAD@{00:45:20}: commit: Require the keys a nested table requires
    554fc56 HEAD@{00:25:55}: checkout: moving from e19bf00 to local-dev

Committed from this working tree, between two of this session's own commits,
with the operator's git identity like every other commit here. It was made by
this session, during the turn that received the D7 report, and then not
remembered as such. There is no third writer.

That is worse than a third writer would have been. The session fixed D7,
committed it, and twenty minutes later "discovered" the fix, could not place it,
and invented an author. Every step of the investigation was sound; the premise
that the commit was foreign was not questioned because it felt foreign.

Standing rules, both mechanical:

- **`git log --format='%h %cd %s'` and `git reflog` before attributing any
  commit.** Content matching an actor is not evidence of the actor.
- **Re-read a file from disk immediately before writing it, always.** In-memory
  copies expire on every tool call, and the two stale-state incidents in this
  session (the extractor miss log, the near-revert of f1f0e77) were both this.

## Uncovered classes, and where each stands

The defect-to-gate mapping the brief asked for. A class is covered when a build
fails on a new instance, not when a rule describes it.

| Class | Example | Status |
|---|---|---|
| Fabricated member name | five DevTools members | covered: keyed emission |
| Return type by name | six defects | covered: every operation in a read namespace must be in `RETURN_EVIDENCE` or `CONFIRMED_EMPTY_CALLBACKS`, so a new rule with no evidence fails the build |
| Parameter type by name | `enable(tabId: ActionDetails)` | covered: `PARAMETER_TYPES` cites, and a fallback to the composed name lands in `unverified-parameters.txt` |
| Nested key table | `setExtensionActionOptions.tabUpdate` | rule 8 only; no gate recurses into sub-dictionaries |
| Dictionary member drift | `WebRequestDetails.requestBody`, `DNRTabUpdateOptions.count` | partly covered: `DICTIONARY_MEMBER_CORRECTIONS` can replace a declared member with a cited reading and cannot invent one; nothing yet *finds* the next drift |
| Conditional availability | `Conditional=`, `[Dynamic]`, `[Platform]` | uncovered; and the parse-coverage pattern `^\s*\w+(=[\w&|\s]+)?,?\s*$` **discards it by design**, so that pattern must narrow in the same commit that models it |
| Event filter arguments | webNavigation/windows `addListener` filter | uncovered, recorded in `INTERFACE_SKIPS` |
| Ambiguous citation | 15 key-table quotes | covered: `verify_citations` rejects count > 1 |
| Prefix-shadowed citation | `onConnect` inside `onConnectExternal` | covered: DECLARATION quotes carry the terminator |
| Attestation table | `getOptions` windowId | covered: all three tables cite, `READ_NAMESPACES` is checked against `RETURN_EVIDENCE` and the empty table |
| Gate with no committed red fixture | parse coverage, vacuous twice | covered: `test/red/run.py`, nine cases in CI, both ratchet directions |

## The file-list gate under --idl-dir, answered

Asked three times, so answered from the code. There is no separate cache mode:
`--cache-dir` only backs `RemoteResolver`'s file reads. `--idl-dir` is the mode
in question, and `IdlDirResolver.list_idl_files` globbed the directory the
caller supplied. Not tool-populated, so not a tautology, but weak: it reconciled
`KNOWN_IDL_FILES` against whatever files happened to be present rather than
against the revision.

Now it defers to the delegate resolver, which lists the revision, and refuses
outright when there is no delegate: `--idl-dir` alone cannot claim the file list
is complete, and says so instead of passing. Proven by removing a file from a
local IDL directory.
