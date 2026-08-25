# httpx — FULL mode results

**Date:** 2026-08-22 09:28  
**Index time:** 3755.8s  
**Nodes:** 2392 | **Edges:** 4213 | **Docs:** 952 | **Embeddings:** 0

---

## Q1: How does a timeout get applied to a request — trace from client.get(timeout=5) to the socket call.

**Facts retrieved:** 15  
**Episodes retrieved:** 15  
**Context length:** 5750 chars

**Context preview:**
```
CODEBASE CONTEXT FOR: How does a timeout get applied to a request — trace from client.get(timeout=5) to the socket call.

CODE SYMBOLS AND FACTS:
  - function.test_timeout_from_nothing: def test_timeout_from_nothing() [2026-08-22T02:50:38.828816+00:00]
  - function.test_timeout_from_none: def test_timeout_from_none() [2026-08-22T02:50:38.828816+00:00]
  - function.test_timeout_from_one_none_value:
```

**Score (0-3):** _[ fill in after testing with model ]_

**Model answer:** _[ fill in ]_

**Notes:** _[ what was correct / wrong / missing ]_

---

## Q2: What runs between client.send() and the actual network I/O?

**Facts retrieved:** 8  
**Episodes retrieved:** 15  
**Context length:** 4780 chars

**Context preview:**
```
CODEBASE CONTEXT FOR: What runs between client.send() and the actual network I/O?

CODE SYMBOLS AND FACTS:
  - module.test_whatwg: module in tests/models/test_whatwg.py [2026-08-22T02:50:38.828816+00:00]
  - module.test_whatwg: module in tests/models/test_whatwg.py [2026-08-22T03:58:00.548903+00:00]
  - method._transport_for_url: def _transport_for_url(self, url) -> BaseTransport — This method ret
```

**Score (0-3):** _[ fill in after testing with model ]_

**Model answer:** _[ fill in ]_

**Notes:** _[ what was correct / wrong / missing ]_

---

## Q3: How does httpx handle redirects — which class controls the redirect loop?

**Facts retrieved:** 15  
**Episodes retrieved:** 15  
**Context length:** 7264 chars

**Context preview:**
```
CODEBASE CONTEXT FOR: How does httpx handle redirects — which class controls the redirect loop?

CODE SYMBOLS AND FACTS:
  - function.redirects: def redirects(request) -> httpx.Response — The 'redirects' function handles HTTP requests and returns appropriate HTTP responses based on the request URL scheme and path. [2026-08-22T03:58:00.548903+00:00]
  - function.cookie_sessions: def cookie_sessions
```

**Score (0-3):** _[ fill in after testing with model ]_

**Model answer:** _[ fill in ]_

**Notes:** _[ what was correct / wrong / missing ]_

---

## Q4: What is the impact of changing AsyncHTTPTransport._send?

**Facts retrieved:** 2  
**Episodes retrieved:** 11  
**Context length:** 3767 chars

**Context preview:**
```
CODEBASE CONTEXT FOR: What is the impact of changing AsyncHTTPTransport._send?

CODE SYMBOLS AND FACTS:
  - module.test_whatwg: module in tests/models/test_whatwg.py [2026-08-22T02:50:38.828816+00:00]
  - module.test_whatwg: module in tests/models/test_whatwg.py [2026-08-22T03:58:00.548903+00:00]

RELEVANT CODE FILES / PAST ACTIONS:

--- Code file: httpx/_transports/default.py () ---
Assistant: FI
```

**Score (0-3):** _[ fill in after testing with model ]_

**Model answer:** _[ fill in ]_

**Notes:** _[ what was correct / wrong / missing ]_

---

## Q5: How does connection pooling work — which class manages the pool?

**Facts retrieved:** 15  
**Episodes retrieved:** 15  
**Context length:** 6168 chars

**Context preview:**
```
CODEBASE CONTEXT FOR: How does connection pooling work — which class manages the pool?

CODE SYMBOLS AND FACTS:
  - class.Client: Client is an HTTP client that supports connection pooling, HTTP/2, redirects, and cookie persistence, and can be shared across threads. [2026-08-22T03:58:00.548903+00:00]
  - class.AsyncClient: AsyncClient is an asynchronous HTTP client that supports connection pooling,
```

**Score (0-3):** _[ fill in after testing with model ]_

**Model answer:** _[ fill in ]_

**Notes:** _[ what was correct / wrong / missing ]_

---
