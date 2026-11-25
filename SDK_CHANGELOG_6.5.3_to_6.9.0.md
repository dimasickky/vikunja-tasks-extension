## 6.9.0 - 2026-11-23

A refusal that only the person can lift says so by structure (slice K2 of the 2026-11-19 marathon audit): the
kernel no longer has to read it out of the error text.

### Added
- `ActionResult.needs_human` - `{"what": str, "kind": "means" | "fact" | "decision"}`, in the dataclass, the
  Pydantic contract (`NeedsHumanModel`, `validate_needs_human`) and `action_result.schema.json`. No `source` key:
  the kernel names the source at its own boundary and passes `what` to the person as a quote.
- Error codes `AUTH_EXPIRED`, `MFA_REQUIRED`, `CONSENT_REQUIRED`, `PAYMENT_REQUIRED`, and
  `HUMAN_ACTION_ERROR_CODES` - the codes only the person can resolve (with `PERMISSION_DENIED`). An error result
  with one of them carries `needs_human` by itself; `ActionResult.error(..., needs_human=...)` sets a more exact one.
- `RefusalEmission.needs_human` for the refusal reasons `no_scope` and `missing_params`.
- `ActionResult.from_dict` keeps `error_code` and `needs_human`, and never raises on what came over the wire: a
  result that crossed the kernel boundary carries `source` and `trusted` beside `what` and `kind`; the reader
  (`parse_needs_human_wire`) takes the two keys of the contract and reads a broken shape as none. The strict
  check stays where a result is made (`ActionResult(...)`, `.error()`, `.to_dict()`).

### Changed
- `ActionResultModel` refuses `status="success"` with an `error_code`.

## 6.8.1 - 2026-11-20

The work that can wait (spec 2026-11-19): what a call does has one source for every reader of a step. Live
2026-11-19 six `web_search` calls were accounted as changes, because no list held the name.

### Added
- The tool contract holds the tools a client answers beyond the file and shell tools: `web_search`, `read_url`,
  `view_image` - each a read.

## 6.8.0 - 2026-11-16

The seven guarantees of the kernel (spec 2026-11-16), G3: no silent cut. Live 2026-11-16 a judge read 600-character
copies ending in a bare "…" and approved a loop; the kernel kept about twenty cutters of its own beside the SDK's.

### Added
- `evidence.cut_text(text, limit, ref="", address="")`: the one place a text is cut -- the head and the tail in whole
  lines, and between them a marker saying how many characters and lines are not shown and where the whole is
  (`address`: the call or the path a reader opens it by). Returns `(shown, Cut | None)`.
- `evidence.cut_marker(...)`: the one wording of that marker, for a reader that holds only parts of a whole it never
  loaded (a window of a log).
- `evidence.Cut`: `kept_lines`, `total_lines`, `address`; `Cut.from_dict` (reads a 6.7 record too).
- `evidence.make_evidence(..., address="")`: the view's marker names how the whole copy is opened.

### Changed
- The marker of a cut view: `… [N of M chars (L of K lines) not shown here; the whole: <where>] …` (was
  `… [N of M chars not shown here; the whole is kept] …`). A view is cut at line breaks.

## 6.7.1 - 2026-11-15

### Fixed
- `secret_mask`: a text holding NUL bytes is masked and kept whole. A mask in the making is marked `\x00<n>\x00`; a NUL
  of the text before digits was read as such a mark and `finish()` looked up a mask never made (IndexError). Live on
  the vault with 6.7.0: every write of a message holding NUL bytes answered 500.

## 6.7.0 - 2026-11-15

The truth architecture (spec 2026-11-14, ICNLI §3.5, §7.2, §7.5, §7.7): the SDK is the one owner of every fact the
kernel, the vault, imperal-mcp and webbee share -- they import it, none keeps its own copy.

### Added
- `code_index.text_lines` / `line_count`: a text's lines as `wc -l` and an editor count them -- one definition for
  outline, read_symbol, read_file, the index's facts and line hashes (field test 2026-11-14 Н3: one line more for
  every file ending with a newline, from `count("\n") + 1` copied into 8+ places). `EXTRACTOR_VERSION` 6.
- `secret_mask`: the one owner of secrets. `mask(text)` gives the masked text and each mask's rule, place and length
  (never the value, nor a hash of it); `scrub_secrets`, `scrub_file_text`, `is_secret_file`, `SECRET_FILES`. The kernel's and
  imperal-mcp's copies had drifted (each lacked rules of the other); this is their union. A URL's scheme now stays
  before the masked credentials (`postgres://[REDACTED]@host`).
- `evidence`: the one record of what an agent saw -- whole and masked, addressed by `whole_ref`, its provenance
  (executed / measured / frame / user / memory / own_write / notification), every cut written on it (`Cut`), one
  `subject` identity -- and the six verdicts, two of them blocking (`BLOCKING`: contradicted, stated_unproven).
- `tool_contract` (+ `schemas/tool_contract.json`): one name, description and parameter set per shell tool for Webbee
  and imperal-mcp; `as_function_schema` (the kernel's LOCAL_TOOL_DEFS shape), `as_mcp_schema`. One name per
  capability: `checkpoint_diff`, `checkpoint_rollback`, `grep_code`; read_file honours a window on any file;
  state_lens' focus filters.

- `secret_mask.secret_file_view` / `scrub_secret_file`: a secret file shown by its form (owner 2026-11-15) -- a
  settings file keeps each key's name and loses every value whatever it looks like (`X=hunter2` too); a line with no
  key and a comment are masked whole; key material (`KEY_MATERIAL`: keys, certificates, keystores, `.ssh/`) keeps
  only its line count. `secret_file_values` + `mask_values`: a command that used a secret file loses exactly that
  file's values (and any random-looking token: a value through base64), the rest of its output stays a fact.

### Changed
- `code_index.SECRET_PATTERNS` is split: `secret_mask.SECRET_FILES` (content is secret) and
  `code_index.SKIP_PATTERNS` (= SECRET_FILES + `.git/`: never indexed). `.git/` is no secret.
- `universal.view.line_count` is `code_index.line_count`; `universal.kinds` never-read names are `SECRET_FILES`.
- `code_links.impact`: a file that imports the symbol without using it is a dependent -- a package's `__init__`
  re-export (`via: "reexport"`) or a plain unused import (`via: "import"`), each with its binding's line (field tests
  2026-11-13 #7, 2026-11-14 П7). The earlier "an import is no user" ruling was never the owner's.
- `code_index.line_hashes` has one hash per line (no trailing blank entry for a final newline).

## 6.6.1 - 2026-11-14

From the imperal-mcp 0.9.15 field test (report 2, 13.11).

### Fixed
- IR: a step field the verb does not take is named with the step's right shape -- `collection`/`table` -> `args.kind`,
  `values`/`fields`/`record` -> `args.data`, `update`/`changes` -> `args.set` -- instead of a bare "unknown field".

## 6.6.0 - 2026-11-13

From the imperal-mcp 0.9.14 field test.

### Added
- `Symbol.doc`: a symbol carries its docstring or the comment above it; Python, TypeScript and JavaScript symbols also
  take scope_facts' definitions (module constants such as `PANEL_ORIGIN`), so the local index and the vault's are one
  extractor's.
- A project's own route decorator that names a URL path (`@door("/v1/x", methods=["GET"])`, `path=`, `method=`) declares
  an endpoint; a decorator that names no path (`@lru_cache(128)`) does not.
- IR runner: `{{args.x}}` names the function's parameters, like `{{event.x}}` (the spec and every agent wrote `args`;
  it resolved to "" and a stored link came back empty).

### Fixed
- A function held by a `const` inside a function (an arrow handler inside a React component) is a definition; search
  never found `completeSignIn`/`handleLogin` although outline saw them. `EXTRACTOR_VERSION` 5: the vault asks every
  older blob again.
- IR: one rule for the checker and the runner. `validate_step` requires a step `id` and names verb fields placed at the
  step root ("must go under 'args'"); `run_steps` validates every step before it runs; `store.create` without
  `args.data` says so instead of `KeyError: 'data'`.

## 6.5.3 - 2026-11-06