# REFLECTION.md

## What assumptions did you make?

The biggest assumption was that the portal's `/portal/export` endpoint returns all meters on a single page — I saw 403 records come back for `page=1` and there was no sign of further pages. I built the single-meter detail route around this: fetch the full export, find the requested meter by ID. It feels fragile (what if the dataset grows to 10,000 meters?), but it's the right call for the data size I could observe.

I also assumed the signing secret from `/portal/keys` is session-scoped and stable for the session's lifetime. I cache it on first use and invalidate + retry on a 401. If the key rotated mid-session that would break things, but nothing in the portal's JS suggested it does.

Finally, I assumed "read-only" meant I shouldn't probe mutation endpoints. The portal looks read-only from the UI anyway, but I deliberately didn't try `POST`/`PUT` to any of the `/portal/` paths.

---

## Which part was the most difficult, and how did you get unstuck?

The most difficult part was discovering the signed export endpoint. I knew there was more data than the search endpoint showed (it only returns 6 fields), but I couldn't find a richer route by guessing URL patterns.

The unlock was methodically fetching every JavaScript chunk linked in the page's `Link` preload headers. The `4.2Bgc2kUI.js` chunk (loaded only on the Transformers page, not the Meters page) contained the entire export flow in one readable function: the fetch to `/portal/keys`, the HMAC computation, and the fetch to `/portal/export`. Once I'd read that chunk I had everything I needed.

Lesson: when exploring an unfamiliar SvelteKit app, the per-route JS nodes are the most valuable artefact — not the network tab (which requires a running browser), but the `Link: rel=modulepreload` headers on each SSR response.

---

## If you had another day, what would you improve?

A local index would be the highest-leverage change. Right now every `/v1/meters/{id}` call hits the portal's export endpoint (≈250 KB). With a background task that fetches the export at startup and indexes meters by ID into an in-memory dict, the per-request cost drops to a dict lookup. The index would be refreshed every N minutes (probably 15–30, since meter data doesn't change minute-by-minute).

After that: gateway authentication (API keys), a `Dockerfile`, and proper delta-kWh computation in the consumption endpoint. The consumption endpoint is the one I'd most want a real operator to validate — I'm not 100% sure the register values are cumulative from the meter's epoch vs. some rolling window.

---

## What mistake did you make while solving this?

I initially tried logging in with the field name `username` (since the credential in the brief used the word "Username: operator@urja.local"). The login form's `input` element has `autocomplete="username"` for browser autofill, but the actual field `name` attribute is `email`. This gave me a 403 on the first login attempt and briefly made me think there was CSRF protection I was missing. Reading the HTML more carefully sorted it out in a few minutes, but it was a reminder to look at the raw `name` attribute, not the label or the autocomplete hint.

---

## If you were reviewing your own submission, what would you criticise?

The single-meter detail endpoint making a full 250 KB export request on every call is the obvious weak point. I called it out in the README trade-offs section, but a reviewer would rightly note that it's not production-safe under any real load. The fix (a startup index) is straightforward, I just didn't want to add cache invalidation logic without knowing the portal's actual data-change frequency.

I'd also criticise the lack of a `Dockerfile`. Running `pip install -r requirements.txt && python -m src` is fine for evaluation, but a production submission should containerise. And the test suite could cover more edge cases: what happens when the portal returns malformed JSON? What if the energy endpoint returns an empty list? The happy-path coverage is solid, but resilience testing is thin.
