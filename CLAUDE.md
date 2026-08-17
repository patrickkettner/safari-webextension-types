# Working rules for safari-webextension-types

Read this before changing anything. Both failures this repository has had came
from the same move: something plausible was written, plausibility was the only
thing checking it, and it shipped.

Background: `POSTMORTEM-algorithmic-return-types.md`, and the DevTools
fabrication that `SIGNATURE_OVERRIDES` was built to prevent.

## 1. Nothing enters the output that WebKit did not put there

Every part of a declaration is a claim about a shipping browser. Both halves
count:

- **The left of the colon**, the name. Enforced. Emission iterates the parsed
  IDL and looks each member up in `SIGNATURE_OVERRIDES`, so a table entry for a
  member WebKit does not declare matches nothing and cannot emit. An entry that
  matches nothing fails the build; so does a parsed member that emits nothing.
- **The right of the colon**, the type. Partly enforced, and this is where the
  live risk is. See rule 3.

## 2. Never choose a type by the spelling of a name

`resolve_algorithmic_return_type` maps verbs (`get`, `update`, `getAll`) onto
`NAMESPACE_PRIMARY_ENTITIES`. That is Chrome naming convention written as code,
and it has been wrong four times: `menus.update`, `bookmarks.get`,
`windows.getLastFocused`, `webNavigation.getFrame`.

**Do not add a rule to that function.** It is a legacy surface being drained,
not a place to extend. To declare what an operation returns, read
`WebExtensionAPI<Ns>Cocoa.mm` at the pinned revision, find its
`callback->call(...)`, and declare that. `RETURN-SHAPES-WORKLIST.md` has the
method and the remaining namespaces.

If a rule genuinely is the right answer for one operation, it goes in as a
narrow `ns_name == ... and op_name == ...` branch with a comment naming the
implementation you read.

## 3. `unresolved-payloads.txt` only shrinks

It lists every operation declared `void` because no rule matched, which is a
guess rather than a reading. The build reconciles it in both directions: a new
entry fails, and a stale entry fails. Verified by breaking it both ways.

A name leaves the list by reading the implementation. **Deleting a line to make
the build pass inverts the point of the file**, and is the same mistake as
driving a red gate to zero by writing overrides.

## 4. A claim beyond the IDL carries a citation

`Cite(path, quote)` is re-resolved at build time against the same revision the
declarations are generated from, with whitespace collapsed. A quote that no
longer appears fails the build.

`Cite(path, quote, absent=True)` inverts it, for a claim that WebKit does *not*
do something. It is only honest when the path is narrow enough that the quote
would have to be there if the behaviour existed. Name the reason in a comment.

Never write a quote from memory. Copy it out of the file you are citing.

## 5. Widening is honest; a confident wrong type is not

When the implementation does not settle a shape, emit `unknown` and record it.
A widened type states less. It does not state something false.

`void` is not a widening. It asserts the callback receives nothing, which is a
positive claim and was false for `windows.getLastFocused`.

The zero-any gate rewards confidence, so treat it with suspicion: it is happy
with a wrong type and unhappy with an honest `any`. `unknown` satisfies both.

## 6. A browser bug is a finding. Only a wrong type is a type change.

Before changing a declaration, say which type was wrong. If the answer is "none,
but the API misbehaves", it belongs in `R1-FINDINGS.md` and nowhere else.

`sidebarAction.setIcon` is unimplemented upstream and its promise always
rejects. That got a doc comment for one commit before the question was asked:
`Promise<void>` never claimed it resolves, TypeScript has no rejection type, and
every promise can reject. Nothing was wrong, so nothing should have changed.

A doc comment is warranted when it explains a type that *had* to change.
`cookies.onChanged` and the two `notifications` events widened to an open
argument list because their payloads were fabricated; the comment says why the
type is now vague. That is different from annotating behaviour a correct type
already covers.

Otherwise the package acquires an unbounded list of hand-curated notes about
browser bugs, with no gate deciding what belongs, which is how the other
repository reached 200 unverifiable entries.

## 7. Never repurpose a marker for its side effect

Four declarations shipped with `@deprecated` on them. None was deprecated. Two
`notifications` events and `cookies.onChanged` are not implemented **yet**, and
`devtools.inspectedWindow.eval` works, just not with the shape Chrome uses.

`@deprecated` was chosen because it is the only JSDoc tag an editor renders as a
warning. That is picking a marker for its side effect and accepting that it
asserts something false: "this was supported, stop using it" is close to the
opposite of "this is not finished".

There is no `@unimplemented` that tsserver surfaces, so the honest option is a
plain doc comment, which shows on hover with no strikethrough. Say the true
thing quietly rather than a false thing loudly.

The general form: if a marker is being chosen for what it triggers rather than
what it means, it is the wrong marker. Applies to exit codes, log levels, HTTP
statuses and commit trailers just as much as to JSDoc.

## 8. A parameter type states what WebKit reads, not what it accepts

`validateDictionary` silently ignores keys it was given no type for, so Safari
accepts more than any of these types allow. The types name the keys the
operation actually reads.

That is a deliberate trade and it costs something: `getFrame({tabId, frameId,
processId})` runs fine in Safari and no longer compiles, because processId is
in WebKit's own dictionary and nothing reads it. The alternative is declaring
keys that do nothing, which turns a typo into a silent no-op.

Apply it consistently. `sidePanel.getOptions` was declared with a `windowId`
the function never parses, in the same commit that dropped `processId` for that
exact reason, and only a reviewer caught it. If a key is declared, name the
line that reads it.

Two things a key set cannot say, both recorded in `R1-FINDINGS.md` under
"Runtime rules the types do not express" rather than in per-commit prose:
mutual exclusions (`{tabId, windowId}` in sidebarAction, `{frameId,
documentId}` in `parseSendMessageOptions`, `{when, delayInMinutes}` in alarms,
`{allFrames, frameIds}` in scripting), and requiredness that depends on state
(`getMatchedRules` requires `tabId` only without the feedback permission).

And one thing a key set must say: **a nested dictionary validates itself.**
`setExtensionActionOptions` has an all-optional outer table and a `tabUpdate`
inner table with both keys required. Reading one `validateDictionary` per
parameter misses the second. Look for `validateDictionary` calls on a
sub-dictionary every time.

## 9. Prove by regeneration and removal, never by reading

The generator is deterministic and runs in seconds against a local checkout, so
any claim of the form "this code is dead" or "this change is cosmetic" is
directly testable. Three branches of the attribute chain looked live and could
never fire; deleting them left the output identical. That is the standard of
proof.

    python3 scripts/generate.py --webkit-checkout /home/pdk/webkit

## 10. Tests over generated output prove nothing about correctness

`test/test.ts` asserts whatever the generator emitted. It kept passing while
`webNavigation.getFrame` returned the wrong type, because `assertType<T>(v: T)`
only checks assignability and every member of the wrong type was optional.

Assert members individually, never a whole type against a whole type. And do not
mistake a green suite for evidence: it shows the artifact did not change.

## 11. A piped check reports the pipe's exit status, not the check's

`npm run typecheck 2>&1 | tail -2 && echo GREEN` prints GREEN whether or not
tsc passed, because the exit status belongs to `tail`. That was the verification
used for most of a session, so "green" meant "the command ran".

Run checks without a pipe, or `set -o pipefail` first. Read the output as well
as the status: a gate whose number does not move is not passing, it is not
measuring. Three gates in this repository looked green while measuring nothing
before being caught.

## 12. Every gate ships a committed proof that it can go red

`test/red/run.py` feeds the generator an input each gate must reject and fails
if it does not, or if it fails for a different reason. Six cases, run in CI.
Presume a gate without one is theatre: parse coverage reported success twice
while measuring nothing, and three of this repository's red proofs existed only
as commit-message prose until they were written down here.

The harness found its own first bug the same way: a mutated copy of the
generator ran from `/tmp`, could not find the ratchet files, and three cases
went "red" for the wrong reason. Distinguish *red* from *wrong red*, always.

## 13. A table of "I read it" is an attestation, not a gate

The name-side invariant works because the parsed IDL is the only thing that can
put a name in the output. The type side was built out of the material that
invariant exists to remove: `READ_NAMESPACES`, `CONFIRMED_EMPTY_CALLBACKS` and
`PARAMETER_TYPES` were sets of bare Python lines meaning "somebody looked".

The first fabrication-shaped error landed on that surface immediately.
`sidePanel.getOptions` was given a `windowId` the function never parses, in the
same commit that dropped `processId` for that exact reason, and only an external
reviewer caught it. That is the predicted failure of an evidence-free table, not
bad luck.

All three tables now carry evidence the build re-resolves.
`CONFIRMED_EMPTY_CALLBACKS` cites the IPC reply resolving `Expected<void>`.
`PARAMETER_TYPES` pairs the operation signature with the validation line it
reaches. `RETURN_EVIDENCE` cites the `callback->call(...)` or synchronous
signature for every payload-bearing operation, and `READ_NAMESPACES` is now a
checked claim: a namespace may appear there only if every one of its operations
is in exactly one of the two tables. Identifying quotes must occur once in
their file. `DICTIONARY_MEMBER_CORRECTIONS` replaces one IDL dictionary member with what
the implementation reads, cited, and fails the build on a key naming a member
the IDL does not declare. It exists because `WebExtensionDNRTabUpdateOptions`
declares `count` and Safari reads `increment`. There is no evidence-free table
left in the generator.

Claims about WebKit behaviour belong in a `Cite` or in extractor output.
A comment is where a decision goes, never a fact: two false claims about the
source shipped in comments this session because nothing checks prose.

## 14. When a defence works, enumerate what it does not cover

Ask it as a required part of every postmortem. R1 said in principle that types,
parameters, key sets and the tables themselves were exposed. Each was learned
instead by shipping one failure per surface, and the series that drained three
of them added a fourth.

## 15. Never satisfy a gate by editing the thing it measures

Applies to `unresolved-payloads.txt`, to the citation quotes, and to the tests.
A red gate is a question about the generator or about WebKit. Answer it there.

## Publishing

Not published to npm. `private: true` says so and `prepublishOnly` enforces it:
`npm publish` fails on the script. The private flag alone was not enough to
verify, because `npm publish --dry-run` does not exercise it and reports
success. Consumers pin a commit tarball, which is what
the downstream package already does.

The reason is that a declaration here is only true of a particular WebKit
revision, and a bare semver hides the thing that decides whether it is correct.
`provenance.json` and the output header both carry the sha. Revisit when there
is a reason to, and keep the `files` list current in the meantime so flipping it
is a one-line change.

## Key commands

```bash
python3 scripts/generate.py --webkit-checkout /home/pdk/webkit   # offline
python3 scripts/generate.py                                      # over the network
npm run typecheck && npm test
python3 scripts/generate.py --provenance /tmp/p.json             # every member's origin
```

`--ref` is pinned to a commit on purpose. Citations are re-resolved at that
revision, and a moving ref lets a declaration and its evidence drift apart.
