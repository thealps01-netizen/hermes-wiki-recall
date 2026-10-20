# Wiki Recall

A Hermes plugin. Before each model turn it searches the open LLM Wiki project with the user's
message and, when a page scores high enough, adds one short note listing up to three page titles
and paths. The assistant then decides whether to read a page with the LLM Wiki tools.

## Why
Relying on the `llm-wiki` skill alone, the assistant sometimes skipped the wiki for questions about
past decisions (it searched chat history instead). This hook makes the lookup automatic.

## Requirements
- The LLM Wiki desktop app running with its API server enabled (default `http://127.0.0.1:19828`;
  override with `LLM_WIKI_API_BASE_URL`).
- If the app requires a token: set the plugin's **API token** setting (Desktop Settings → Plugins →
  Wiki Recall). Hermes stores it as `LLM_WIKI_API_TOKEN` in its `.env`; a `LLM_WIKI_API_TOKEN`
  already in the process environment also works. The token is only sent in the `Authorization`
  header.
- Python standard library only.

## Behaviour
- Pointer rule: vector score >= 0.8, at most 3 pointers, titles and paths only.
- Skip pattern (optional, empty by default): a case-insensitive regular expression; messages that
  match are not searched. Set it in the plugin's settings form, or in `config.yaml`:

  ```yaml
  plugins:
    entries:
      wiki-recall:
        settings:
          skip_pattern: "<regex>"
  ```
- App closed, error or no reply within 2 seconds: nothing is added; the turn continues normally.
  Each such failure writes one `wiki-recall: <reason> (<exception class>)` WARNING line, with no
  message text or token. Find it with `hermes logs errors` (or `hermes logs --level WARNING`).
- Settings take effect in new sessions.
- Embedding runs in the wiki app's configured local model, so a search uses no cloud quota as long
  as the app's embedding endpoint is local.

## What it sends
On every turn, the latest user message (up to 1000 characters) is sent as a POST to
`<LLM_WIKI_API_BASE_URL>/api/v1/projects/current/search` (default `http://127.0.0.1:19828`, a
local address). The plugin makes no other network calls and reads no files.

## Compatibility
Tested with Hermes Agent 0.22.2 and the LLM Wiki desktop app's local search API (fields used:
`results[].path`, `title`, `vectorScore`). There is no CI version matrix, so other versions are
untested. A missing app means no pointers plus the log line above.

## Known limit
The app caps page scores at 1.0 (best chunk + 30% of other chunks), so long pages can pass the
threshold on weak matches. On one user's 142 real messages (Turkish messages, English wiki,
hand-labelled), 54 messages got pointers: 32 pointers were relevant, 33 unrelated and 12 unclear;
20% of messages got at least one unrelated pointer. Also requiring the app's fused keyword+vector
score cut unrelated pointers by about two thirds but dropped 9 of the 32 relevant ones, because
keyword matching fails across languages, so the rule stays vector-only.

Only the latest message is searched. A note is stored with the message it was added to and is
sent again on later turns of the same session, so a short follow-up can still use an earlier
note. A follow-up with no earlier note relies on the skill.

## Enable / disable
Enable `wiki-recall` from Hermes' plugin settings (or `hermes plugins enable wiki-recall`);
disable the same way. Takes effect in new sessions.

## Tests
From this folder: `PYTHONUTF8=1 python -m unittest discover -s tests`
