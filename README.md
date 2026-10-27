# Wiki Recall

A Hermes plugin. Before each model turn it searches the open LLM Wiki project with the user's
message and, when a page scores high enough, adds one short note listing up to three page titles
and paths. When no page scores that high, it lists up to two closest pages marked as low
confidence. The assistant then decides whether to read a page with the LLM Wiki tools.

## Why
Relying on a wiki skill alone, the assistant sometimes skipped the wiki for questions about
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
- Low-confidence rule: when no page reaches 0.8, the best pages with vector score >= 0.65 are
  listed, at most 2, under a note saying no page matched closely.
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

Low-confidence pointers: on 36 hand-picked messages from the same user (26 with an answer page in
the wiki, 10 without), the 0.8 rule alone named the answer page for 13 of the 26; adding the
low-confidence rule raised that to 19, and it added low-confidence pointers to 3 of the 10
messages with no answer page. On the 88 real messages that got no pointer in the 142-message
set, the best score was 0.7-0.8 for 19 and 0.6-0.7 for 33, so roughly 19-52 of them now get a
low-confidence note; these were not labelled.

Only the latest message is searched. A note is stored with the message it was added to and is
sent again on later turns of the same session, so a short follow-up can still use an earlier
note. A follow-up with no earlier note relies on the skill.

Local query rewriting was tried and not adopted. On 135 further real messages from the same user
(three fresh sets of 45, hand-labelled against the full page list), small local models on the GPU
(Gemma 3 and 4, Qwen3 1.7B to 8B, TranslateGemma, a query-expansion model) wrote an English
search query that was searched alongside the Turkish message; some runs added a GPU reranker
(Qwen3-Reranker-0.6B, score >= 0.1) to choose the pointers. Each candidate was fixed before its
test set was labelled. None beat the current rule: the best query writer named the answer page
for one more message (13 vs 12 of 25); the reranker stopped pointers on messages with no answer
page (11 to 1 of 14) but named the answer page for one or two fewer messages (13 and 12 vs 14 of
31) and kept 3 to 7 GB of GPU memory in use. The plugin therefore searches the message as written.

## Enable / disable
Enable `wiki-recall` from Hermes' plugin settings (or `hermes plugins enable wiki-recall`);
disable the same way. Takes effect in new sessions.

## Tests
From this folder: `PYTHONUTF8=1 python -m unittest discover -s tests`
