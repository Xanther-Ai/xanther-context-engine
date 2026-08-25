# httpx — XME mode results

**Date:** 2026-08-22 11:08  
**Index time:** 29.8s  
**Nodes:** 2392 | **Edges:** 4213 | **Docs:** 0 | **Embeddings:** 0

---

## Q1: How does a timeout get applied to a request — trace from client.get(timeout=5) to the socket call.

**Facts retrieved:** 15  
**Episodes retrieved:** 15  
**Context length:** 6252 chars

**Context preview:**
```
CODEBASE CONTEXT FOR: How does a timeout get applied to a request — trace from client.get(timeout=5) to the socket call.

CODE SYMBOLS AND FACTS:
  - function.test_timeout_from_nothing: def test_timeout_from_nothing() [2026-08-22T02:33:04.616535+00:00]
  - function.test_timeout_from_none: def test_timeout_from_none() [2026-08-22T02:33:04.616535+00:00]
  - function.test_timeout_from_one_none_value:
```

**Score (0-3):** _[ fill in after testing with model ]_

**Model answer:** _[ fill in ]_

**Notes:** _[ what was correct / wrong / missing ]_

---

## Q2: What runs between client.send() and the actual network I/O?

**Facts retrieved:** 15  
**Episodes retrieved:** 15  
**Context length:** 6029 chars

**Context preview:**
```
CODEBASE CONTEXT FOR: What runs between client.send() and the actual network I/O?

CODE SYMBOLS AND FACTS:
  - module.test_whatwg: module in tests/models/test_whatwg.py [2026-08-22T02:33:04.616535+00:00]
  - function.test_cookie_persistence: def test_cookie_persistence() -> None — Ensure that Client instances persist cookies between requests. [2026-08-22T02:33:04.616535+00:00]
  - class.Client: An
```

**Score (0-3):** _[ fill in after testing with model ]_

**Model answer:** _[ fill in ]_

**Notes:** _[ what was correct / wrong / missing ]_

---

## Q3: How does httpx handle redirects — which class controls the redirect loop?

**Facts retrieved:** 15  
**Episodes retrieved:** 15  
**Context length:** 7314 chars

**Context preview:**
```
CODEBASE CONTEXT FOR: How does httpx handle redirects — which class controls the redirect loop?

CODE SYMBOLS AND FACTS:
  - class.Client: An HTTP client, with connection pooling, HTTP/2, redirects, cookie persistence, etc.

It can be shared between threads.

Usage:

```python
>>> client = httpx.Client()
>>> response = client.get('https: [2026-08-22T02:33:04.616535+00:00]
  - class.AsyncClient: An
```

**Score (0-3):** _[ fill in after testing with model ]_

**Model answer:** _[ fill in ]_

**Notes:** _[ what was correct / wrong / missing ]_

---

## Q4: What is the impact of changing AsyncHTTPTransport._send?

**Facts retrieved:** 4  
**Episodes retrieved:** 11  
**Context length:** 4273 chars

**Context preview:**
```
CODEBASE CONTEXT FOR: What is the impact of changing AsyncHTTPTransport._send?

CODE SYMBOLS AND FACTS:
  - module.test_whatwg: module in tests/models/test_whatwg.py [2026-08-22T02:33:04.616535+00:00]
  - method.port: def port(self) -> int | None — The URL port as an integer.

Note that the URL class performs port normalization as per the WHATWG spec.
Default ports for "http", "https", "ws", "wss"
```

**Score (0-3):** _[ fill in after testing with model ]_

**Model answer:** _[ fill in ]_

**Notes:** _[ what was correct / wrong / missing ]_

---

## Q5: How does connection pooling work — which class manages the pool?

**Facts retrieved:** 15  
**Episodes retrieved:** 15  
**Context length:** 6351 chars

**Context preview:**
```
CODEBASE CONTEXT FOR: How does connection pooling work — which class manages the pool?

CODE SYMBOLS AND FACTS:
  - class.Client: An HTTP client, with connection pooling, HTTP/2, redirects, cookie persistence, etc.

It can be shared between threads.

Usage:

```python
>>> client = httpx.Client()
>>> response = client.get('https: [2026-08-22T02:33:04.616535+00:00]
  - class.AsyncClient: An asynchro
```

**Score (0-3):** _[ fill in after testing with model ]_

**Model answer:** _[ fill in ]_

**Notes:** _[ what was correct / wrong / missing ]_

---
