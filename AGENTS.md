# AGENTS.md — wiki-recall

Native Hermes plugin (hook only, no UI). `__init__.py` registers one `pre_llm_call` hook; `recall.py`
searches the open LLM Wiki project through the desktop app's local HTTP API and returns up to three
page titles and paths as turn context. `README.md` explains behaviour and limits.

## Setup (fresh checkout)
- Python 3.11+, standard library only. No `pip install`.
- Live checks need the LLM Wiki desktop app running with its API server on (default
  `http://127.0.0.1:19828`, override `LLM_WIKI_API_BASE_URL`); unit tests do not.

## Validation (run all after any change; each must pass)
```bash
PYTHONUTF8=1 python -m unittest discover -s tests
hermes plugins validate "$(cygpath -m "$PWD")"
hermes plugins doctor "$(cygpath -m "$PWD")"
```
`hermes plugins validate` must end with `Validation passed.` and show no new warning.

## Rules
- A chat turn must never fail or wait because of this plugin: every network call has a timeout
  (2 s), and every failure returns no context.
- A swallowed failure leaves exactly one `logger.warning` line (`logging.getLogger(__name__)`, so it
  reaches `hermes logs errors`) starting with `wiki-recall: `, naming the reason and the exception
  class only; never the message text, the token, `str(exc)` or the response body.
- The token comes only through Hermes: the `api_token` secret in `config_schema`, read with
  `agent.secret_scope.get_secret("LLM_WIKI_API_TOKEN")` imported inside the hook (catalog rule 11);
  never from a file. It is only ever sent in the `Authorization` header; never logged, printed or
  written.
- Nothing from the author's own setup is a default: no personal project or app names, languages or
  paths in code, manifest, docs or tests. Personal behaviour is a `config_schema` setting
  (e.g. `skip_pattern`, empty by default).
- Request bodies are UTF-8 (`ensure_ascii=False` + `.encode("utf-8")`); Turkish text must survive.
- Context lists titles and paths only, never page content.
- A new rule gets a unit test that fails on the old behaviour first.
- Develop only in this checkout. Never edit the installed copy under `<hermes home>/plugins/`.
- Agent-read text (code, comments, docs) is English.

## Ship
Push `main` to `github.com/thealps01-netizen/hermes-wiki-recall`, then install pinned:
`hermes plugins install thealps01-netizen/hermes-wiki-recall --force --ref <40-char commit> --enable`.
Bump `version` in `plugin.yaml` for every release. Native hooks load per process: new code runs in
sessions started after the install; `--enable` reloads the running gateway.
