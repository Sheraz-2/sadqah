# Local AI (Ollama) for the SadQah assistant

The assistant (chat guide, needs price check, needs-proof check) can run on a local model through [Ollama](https://ollama.com), so
supported text features need no paid cloud request. This is an explicit choice: SadQah never switches engines by itself.

## Choose the engine (`.env`)

| Setting | Default | Meaning |
|---|---|---|
| `ASSISTANT_PROVIDER` | `anthropic` | `anthropic` (original behaviour, needs `ANTHROPIC_API_KEY`), `ollama` (local, text only) or `none` (built-in FAQ only) |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Where the API container reaches Ollama. Only `scheme://host:port`. |
| `OLLAMA_MODEL` | `qwen2.5:1.5b` | The model name exactly as `ollama list` shows it |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | Per request (also bounds each wait on the network). A small model on a CPU can be slow |
| `OLLAMA_NUM_CTX` | `4096` | Context window sent to Ollama. Its own default (2048) is too small for the assistant's instructions and would cut them off |

The setting only affects the assistant. KYC document extraction, face checks, authentication and payments are unchanged.
`ASSISTANT_LLM_MODEL` (a Claude model name) is used only with `anthropic`; with `ollama` the model is `OLLAMA_MODEL`.

## What the local model does and does not do

* **Chat** and **price estimates**: yes. The existing prompts (`GUIDE_SYSTEM`, `PRICE_SYSTEM`) are sent as Ollama's system message;
  prices are requested in JSON mode and then go through the same validation as before (`parse_model_json`, `coerce_estimates`,
  `evaluate_items`, `summarize`). The verdict on a price is plain arithmetic against the model's range. Estimates can be wrong even
  when well formed: they stay labelled as estimates and a SadQah reviewer decides.
* **Proof photos and PDFs**: **no.** `qwen2.5:1.5b` is a text model. With `ollama` the proof is stored and shown to staff as
  "Proof not checked by AI" (`NOT_CHECKED`); nothing about the file is sent to the model, and nothing is silently sent to a paid
  service instead. To have the proof reviewed by AI you must choose `anthropic` explicitly (with its key).
* Generated text never approves KYC, authorises a payout or certifies a proof. A person decides.

## If Ollama is down, slow, or answers badly

Chat falls back to the built-in FAQ (`ai: false`), a price check returns "no estimate" (`ai_available: false`), and a needs
submission still reaches a human reviewer unchecked. Details go to the API log (status code or error class only, never what the
person typed or the model said). There is no fallback to Anthropic.

## Set up on Windows with Docker Desktop

1. Ollama is running and the model is pulled: `ollama list` shows `qwen2.5:1.5b` (`ollama pull qwen2.5:1.5b`).
2. In `.env` add (do not commit it):
   ```
   ASSISTANT_PROVIDER=ollama
   OLLAMA_BASE_URL=http://host.docker.internal:11434
   OLLAMA_MODEL=qwen2.5:1.5b
   ```
3. Recreate the API so it reads them: `docker compose --profile app up -d --force-recreate api`
4. Check the setting reached the container: `docker compose exec api env | findstr /i "ASSISTANT_PROVIDER OLLAMA"`
5. Ask SadQah's own endpoint (not Ollama directly):
   ```
   Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/assistant/chat -ContentType "application/json" -Body '{"messages":[{"role":"user","content":"How do I delete my account?"}],"page":"/settings"}'
   ```
   `ai` should be `True` and the reply should come from the model. While it runs, `ollama ps` lists the loaded model, and the
   Ollama server log shows a `POST /api/chat`. If `ai` is `False`, read `docker compose logs api` for the `ollama ...` line.

Keep Ollama private: leave it on its default local address, do not set `OLLAMA_HOST=0.0.0.0`, and do not publish port 11434.
`docker-compose.yml` publishes only the API on `127.0.0.1:8000`; it also maps `host.docker.internal` for Linux hosts.

## Limits

* Quality: a 1.5B model is small. Expect simpler answers, occasional wrong or off-topic replies, weaker non-English output, and
  price ranges that are sometimes missing or invalid (those items show "no reliable estimate").
* If the Ollama host is unreachable in a way that does not refuse the connection at once (for example a firewall that drops it), a request waits for the timeout before the FAQ answers; lower `OLLAMA_TIMEOUT_SECONDS` if that matters more to you than slow answers.
* No streaming and one model call per request; the first call after Ollama has been idle loads the model and can be slow.
* The automated tests use a fake Ollama server on loopback and the real route handlers; they do not measure the model.

## Speed, load and history (second round)

A 1.5B model on a CPU is slow by nature: expect many seconds per answer and longer on the first one after a restart. The code cannot
change that, but it avoids making it worse:

| Cause of slowness | What SadQah does now | Setting |
|---|---|---|
| Long answers (every extra token is more waiting) | Chat replies are capped; a cut-off reply ends at the last full sentence. Price estimates only ask for room for the items listed. | `OLLAMA_MAX_TOKENS` (400) |
| Model unloaded between questions (a reload takes seconds) | Asks Ollama to keep it loaded for 30 minutes. | `OLLAMA_KEEP_ALIVE` |
| Reading the instructions again on every question | The instructions are always the same first message, so Ollama can reuse what it already processed. History is bounded to the newest 6 messages / 3000 characters. | `ASSISTANT_HISTORY_MESSAGES`, `ASSISTANT_HISTORY_CHARS` |
| Several questions at once fighting for the CPU (this is what slows the whole website) | One model call at a time, two more may wait; beyond that the person gets an honest message at once. | `OLLAMA_MAX_CONCURRENT`, `OLLAMA_MAX_QUEUE` |
| The model using every CPU core | Optional cap on model threads, so the website keeps some cores. | `OLLAMA_NUM_THREAD` (try your core count minus 2) |

The model call runs in a worker thread, so a slow answer does not block the API's event loop; a test checks that other work keeps being
served during a slow generation. That does **not** stop Ollama itself from using the CPU: if the site still feels slow while the model is
working, lower `OLLAMA_NUM_THREAD` and, in Ollama's own environment, set `OLLAMA_NUM_PARALLEL=1`. The API log prints one line per answer
(`ollama answered in 12.3s (prompt tokens ..., reply tokens ..., model load ...)`) so you can see where the time goes: a large "model load"
means the model was reloaded; large "prompt tokens" means a long prompt.

In the browser the widget shows "Thinking…", adds "Still working…" after 12 seconds, and ends with a clear message after 150 seconds
(the frontend proxy is allowed up to 180 seconds in `next.config.mjs`; restart `npm run dev` / rebuild for that to apply).

### Conversation history

The chat history is made valid in one place (`normalize_history`, used by the chat route for every engine): it starts and ends with the
person, strictly alternates, merges consecutive messages of the same role without losing text, drops blank or unsupported-role messages
and trailing assistant messages, and keeps the newest messages within the limits above. The widget leaves out its own error notices.
The earlier error "The conversation must alternate between you and the assistant, starting and ending with you" came from the widget sending
its last 12 messages: after the sixth question that window began with an assistant message, which the route rejected.

### Not inventing features

The assistant's instructions and site guide were checked line by line against the real pages (labels, paths, sort names, settings, the
no-platform-fee statement on the Trust page). Where the app does not offer something (live chat, a phone line,
a contact form) the guide says so, and it names the one real support channel: the Contact us page (`/contact`, linked in the footer) and
its e-mail address `sadqahsupport@gmail.com`. The guide never promises a reply time, never says a message was sent (the visitor presses Send
in their own e-mail app), and never asks anyone to e-mail passwords, one-time codes, payment credentials or identity documents. See
[CONTACT_US.md](CONTACT_US.md). The model is told to answer only from that guide and to say "I am not sure about that" otherwise. A
small model can still ignore instructions, so a few requests for things SadQah does not offer (live chat, phone or WhatsApp, a mobile
app, crypto, bank transfer, Apple/Google Pay) get a fixed, honest answer without calling the model. Tests check the guide against the frontend
source when it is present. They cannot prove what the real model will say: ask it a few things that do not exist and read the answers.
