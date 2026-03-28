# Why Open Source

ToolWitness is free, open source, and local-first by design — not as a marketing tactic, but because the problem demands it.

## The trust paradox

ToolWitness exists to answer one question: **is your AI agent telling the truth about what its tools returned?**

If we asked you to send your agent's tool inputs, outputs, and responses to our cloud to verify them, we'd be asking you to trust *us* in order to verify trust in *your agent*. That's a paradox. The verification layer should be the most trustworthy component in the stack — and the most trustworthy thing is code you can read, running on your machine, with no network calls.

## Why a library, not a service

ToolWitness is a Python package you install and embed in your agent code:

```bash
pip install toolwitness
```

One import, one line to wrap your client, and verification happens locally. We chose this approach deliberately:

**You own your data.** Tool inputs, outputs, and verification results never leave your machine. There's no account to create, no API key to manage, no data retention policy to read. Your agent's behavior is your business.

**You can read every line.** The entire verification engine — HMAC receipts, structural matching, schema conformance, chain verification, classification — is in the source code under Apache 2.0. No black boxes, no proprietary scoring algorithms, no "trust us, it works."

**It works where you work.** ToolWitness runs in your CI pipeline, your development environment, your production stack. It doesn't depend on an external service being up, fast, or affordable. If our company disappeared tomorrow, your verification would keep working.

**Adoption matters more than revenue right now.** "Silent failure detection" is a category that barely has a name. The [academic research](https://arxiv.org/abs/2603.10060) is just starting to formalize it. We need developers using ToolWitness, finding edge cases, building adapters, and proving the approach works across real-world agents — not paying us $29/month to try it.

## The research that got us here

ToolWitness was born from a research sprint across 35+ sources (Gartner, Forrester, Stanford HAI, Sequoia, NIST, OWASP) examining where agentic AI tooling has gaps. The finding: existing observability tools (LangSmith, Langfuse, Datadog) trace *that tools ran* but none verify *whether agents told the truth about what came back*.

The closest academic work is [NabaOS](https://arxiv.org/abs/2603.10060) (Basu, March 2026) — a verification framework using HMAC-signed tool execution receipts to detect hallucinated tool results. NabaOS achieves 94.2% detection of fabricated tool references with under 15ms overhead, compared to cryptographic approaches like zkLLM that take 180 seconds per query.

ToolWitness takes the same core insight — lightweight receipts beat heavy cryptography for interactive agents — and packages it as a practical, framework-agnostic tool that developers can install today.

## What open source gives you

| Concern | Our answer |
|---|---|
| "Will this steal my code?" | All code is visible. We see tool I/O only, not your codebase. [Full privacy details →](privacy.md) |
| "What if you shut down?" | The code is Apache 2.0. Fork it, vendor it, maintain it yourself. |
| "Can I trust the classifications?" | Read the classifier. It's 200 lines of Python, not a black box. |
| "What about my proprietary agent?" | Everything runs locally. No data leaves your machine. |
| "Will this break my agent?" | Fail-open design. ToolWitness errors never block your tools. |

## What comes next

The open source library is the foundation. Over time, we plan to build:

- **Community adapters** — support for more frameworks as developers contribute them
- **Improved verification** — semantic matching, NLP claim extraction, deeper chain analysis
- **Enterprise features** — hosted dashboards, team views, historical trending, compliance reporting

The core verification engine will always be free and open source. Enterprise features will be how we sustain the project — not by locking down what developers already have.

## Get involved

- [:fontawesome-brands-github: View the source](https://github.com/vcrosby22/toolwitness)
- [Getting Started →](getting-started.md)
- [Contributing →](contributing.md)
