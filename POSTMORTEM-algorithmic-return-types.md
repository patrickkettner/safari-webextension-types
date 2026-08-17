# Postmortem: the return-type resolver guesses, and the guesses shipped

Four wrong return types were found and corrected in three sittings, by reading
the implementation for one namespace at a time. They are not four mistakes.
They are one mechanism failing four times, and the count is not four because
sixteen namespaces have not been read yet.

## What was wrong

| Operation | Declared | WebKit |
|---|---|---|
| `webNavigation.getFrame` / `getAllFrames` | `WebNavigationGetFrameDetails`, the dictionary the *details argument* takes | `{errorOccurred, parentFrameId, url, frameId?, documentId?}` |
| `windows.getLastFocused` | `Promise<void>` | resolves a window and calls back with it |
| `menus.update` | `Promise<MenuItemProperties>` | resolves `Expected<void>`, calls back with nothing |
| `bookmarks.get` | one `BookmarkTreeNode` | calls back with `resultArray` |

## The mechanism

`resolve_algorithmic_return_type` decides what an operation returns from the
**spelling of its name**. A verb table maps `get`, `getAll`, `create`, `update`,
`move`, `search` and friends onto an entry from `NAMESPACE_PRIMARY_ENTITIES`, a
hand-written guess at each namespace's central type. Nothing in the path reads
WebKit.

That produces three distinct failure modes, and this session found all three:

- **A rule fires on an operation it does not fit.** `menus.update` is an
  `update`, so it got the namespace primary, `MenuItemProperties`. `bookmarks.get`
  is a `get`, so it got one node rather than the array its id-list argument
  implies. The rule is not wrong in general; it is wrong here, and the code has
  no way to know the difference.
- **No rule fires, and the default is a claim.** `windows.getLastFocused` matches
  nothing, so it fell to the final `return 'void'`. `void` is not "unknown". It
  is a positive assertion that the callback receives nothing, and it was false.
- **A name collides with an unrelated type.** `webNavigation` has an IDL
  dictionary whose name contains `GetFrameDetails`, so the resolver reached for
  it. It describes the argument going the other way.

The docstring calls this "algorithmic ... based on operation semantics". The
algorithm is English naming convention as practised by Chrome's documentation.
Computing an answer is not deriving one.

## Why the R1 gate did not catch any of it

R1 made it impossible to emit a member the IDL does not declare, and every
emitted member now carries a citation. All four operations above passed it
cleanly, because R1 constrains **existence** and says nothing about **shape**.
`getLastFocused` exists, is cited to its IDL line, and returned the wrong thing.

The citation requirement stops one line short. A member's name is cited to
source; the type on the right of the colon is not.

## Why nothing else caught it either

- **`tsc` cannot.** Every one of these is a well-formed type.
- **The test suite cannot, and demonstrably did not.** `test.ts` asserted
  `getFrame`'s old return type and kept passing after the type changed, because
  `assertType<T>(value: T)` only checks assignability and every member of the
  old type was optional. Tests written from generated output assert whatever the
  output happened to say.
- **The zero-any gate cannot.** A confident wrong type contains no `any`. The
  gate rewards confidence, which is the wrong direction: `unknown` would have
  been honest and `void` was not.
- **Reading it cannot.** All four look right. `update` returning the updated
  thing, `get` returning the thing, `getFrame` returning frame details: each is
  what a reviewer expects to see. The failure is invisible to review by
  construction, which is the same property the five fabricated DevTools members
  had.

## The shape of the bug

The generator has no way to say "I do not know". Every operation gets a
confident type, from a rule or from the `void` default, and both look identical
in the output and in the provenance. The one honest answer available in
TypeScript, `unknown`, is never produced by this path.

That is the asymmetry to fix. Widening a type states less; it does not state
something false. Defaulting to `void` states something false whenever the
operation does return a payload, and states it silently.

## What to change

1. **Derive the payload, do not infer it.** Every namespace's `.mm` reaches
   `callback->call(...)`; the argument is the payload. That is mechanical, it is
   at the same revision everything else is cited to, and it is what the three
   completed chunks did by hand. `RETURN-SHAPES-WORKLIST.md` carries the method
   and the remaining sixteen namespaces.
2. **Make the fall-through visible.** Tag the operations that reached the final
   `return 'void'` separately from the ones a rule chose deliberately, and
   record the tag in the provenance. Today they are indistinguishable.
3. **Default to `unknown`, not `void`.** An unresolved payload should widen, and
   the widening should be recorded rather than silent. `void` should be emitted
   only where the implementation was read and calls back with nothing.
4. **Ratchet the unresolved count.** Once tagged, the number of operations
   without a derived return shape must never increase. That is the same shape as
   the existing reconciliation errors, applied to types instead of names.
5. **Cite the right-hand side.** The end state is that a return type carries a
   citation exactly as a member's existence does, and the build fails when it
   stops resolving. Steps 2 to 4 are what make that reachable incrementally
   instead of as one large rewrite.

## The generalisation

Both failures this repository has now had are the same one. A model produced
something plausible, plausibility was the only thing checking it, and it
shipped. Fabricated member names and inferred return types differ in which half
of the declaration they corrupt, not in kind.

The defence that worked for names was to make the parsed source the only thing
that can put a name in the output. The same defence has not yet been applied to
types.
