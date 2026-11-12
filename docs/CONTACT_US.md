# Contact Us

SadQah support is reached by **e-mail only**: `sadqahsupport@gmail.com`. There is no phone line, live chat or contact form, and no reply
time is promised. The page does not send anything itself.

## What was added

| Piece | File |
|---|---|
| Support address, subject and `mailto:` link (single source of truth) | `frontend/src/lib/contact.ts` |
| Page at `/contact` (server component, has `metadata`) | `frontend/src/app/contact/page.tsx` |
| "Copy email address" button with a polite live region (`role="status"`) | `frontend/src/components/contact/CopyEmail.tsx` |
| "Contact us" link in the footer (shown to signed-in and signed-out visitors, on every page) | `frontend/src/components/layout/Footer.tsx` |
| "contact support" text now links to `/contact` | `settings`, `trust`, `forgot-password`, `recipient/profile` pages |
| `/contact` is linkified when the assistant mentions it | `frontend/src/components/assistant/AssistantWidget.tsx` |
| Assistant knowledge: `SITE_GUIDE`, `GUIDE_SYSTEM`, `UNSUPPORTED_ANSWER`, built-in FAQ and fallbacks | `backend/app/services/assistant.py` |

The header (with its menus) was not changed, so nothing is duplicated and the responsive menus are untouched.

## Changing the address

Edit `SUPPORT_EMAIL` in `frontend/src/lib/contact.ts` **and** the address in `backend/app/services/assistant.py`
(`SITE_GUIDE`, `CONTACT_ANSWER`, `GUIDE_SYSTEM`, `UNSUPPORTED_ANSWER`, the fallbacks). `tests/test_contact_feature.py` fails if the two disagree.

## Rules the page and the assistant follow

* Never e-mail passwords, one-time codes, card / PayPal / bank login details, or identity documents. Verification documents are uploaded
  only inside the Verification page.
* No invented hours, phone numbers, addresses, response times or other channels.
* The assistant says "open the Contact page / e-mail this address". It never claims a message was sent, and it still says "I am not sure
  about that" when the site facts do not answer a question.

## Verification status (what was actually run)

Run in the build sandbox: backend unit tests (`tests/test_contact_feature.py` and the earlier assistant tests), `ruff`, a TypeScript
check against shims, and a headless-Chromium run of the page rendered with the real Tailwind CSS (mailto href and subject, clipboard write
and failure message, live-region text, keyboard order and focus outlines, footer link, widths of 320, 375 and 768 px, text contrast).

**Not run here:** `npm run build` / `next dev` (no `node_modules`), the real Next.js router (direct load and refresh of `/contact` rely on
it being a plain server page), a real e-mail client opening from the `mailto:` link, and a real Ollama model answering contact questions.
Please check these on your machine: `docker compose` or `npm run dev`, open `http://localhost:3000/contact`, refresh it, click
"Write an email" and "Copy email address", and ask the assistant "How do I contact you?".
