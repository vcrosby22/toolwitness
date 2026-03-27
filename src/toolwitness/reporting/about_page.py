"""About page — self-contained marketing and demo page for ToolWitness.

Serves as the pitch deck inside the product: what it is, why it exists,
how it works, privacy guarantees, install instructions, and differentiators.
"""

from __future__ import annotations


def generate_about_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>About ToolWitness</title>
{_css()}
</head><body>

<nav>
    <a href="/" class="nav-brand">ToolWitness</a>
    <div class="nav-links">
        <a href="/">Dashboard</a>
        <a href="/report">Report</a>
        <a href="/about" class="active">About</a>
    </div>
</nav>

{_section_hero()}
{_section_problem()}
{_section_how_it_works()}
{_section_privacy()}
{_section_install()}
{_section_unique()}

<footer>
    <p>Apache 2.0 &mdash; Open source, free forever for individual use.</p>
    <p style="margin-top:0.5rem">
        <a href="https://github.com/vcrosby22/toolwitness">GitHub</a>
    </p>
</footer>

</body></html>"""


def _section_hero() -> str:
    return """
<section class="hero">
    <h1>Stop trusting your agent &mdash; get a witness.</h1>
    <p class="hero-sub">
        ToolWitness detects when AI agents <strong>skip tool calls</strong>
        or <strong>fabricate outputs</strong>. Existing observability tools
        trace that tools ran &mdash; ToolWitness verifies that agents
        <em>told the truth about what came back</em>.
    </p>
    <div class="hero-cta">
        <a href="/" class="btn btn-primary">See the Dashboard</a>
        <a href="#install" class="btn btn-secondary">Install</a>
    </div>
</section>"""


def _section_problem() -> str:
    return """
<section id="problem">
    <h2>The Problem</h2>
    <p class="section-intro">
        AI agents can fail silently in two ways that no existing tool catches:
    </p>

    <div class="two-col">
        <div class="problem-card">
            <div class="problem-icon">&#8856;</div>
            <h3>Tool Skip</h3>
            <p>The agent says it called a tool but <strong>never did</strong>.
            It answered from training data instead. No error, no log,
            no way to tell &mdash; until now.</p>
        </div>
        <div class="problem-card">
            <div class="problem-icon">&#10007;</div>
            <h3>Result Fabrication</h3>
            <p>The agent called the tool, got data back, then
            <strong>misrepresented what it returned</strong>. The trace
            looks clean. The answer is wrong.</p>
        </div>
    </div>

    <div class="comparison">
        <h3>What existing tools miss</h3>
        <table>
            <thead><tr>
                <th>Tool</th>
                <th>Sees tool calls</th>
                <th>Sees latency/tokens</th>
                <th>Verifies truthfulness</th>
            </tr></thead>
            <tbody>
                <tr>
                    <td>LangSmith / Langfuse</td>
                    <td class="yes">Yes</td>
                    <td class="yes">Yes</td>
                    <td class="no">No</td>
                </tr>
                <tr>
                    <td>Datadog / New Relic</td>
                    <td class="yes">Yes</td>
                    <td class="yes">Yes</td>
                    <td class="no">No</td>
                </tr>
                <tr>
                    <td>Provider dashboards</td>
                    <td class="partial">Partial</td>
                    <td class="yes">Yes</td>
                    <td class="no">No</td>
                </tr>
                <tr class="highlight-row">
                    <td><strong>ToolWitness</strong></td>
                    <td class="yes">Yes</td>
                    <td class="yes">Yes</td>
                    <td class="yes"><strong>Yes</strong></td>
                </tr>
            </tbody>
        </table>
    </div>

    <div class="classification-table">
        <h3>Five classifications, one confidence score</h3>
        <table>
            <thead><tr>
                <th>Classification</th><th>What happened</th><th>Example</th>
            </tr></thead>
            <tbody>
                <tr>
                    <td><span class="badge-v">VERIFIED</span></td>
                    <td>Agent accurately reported tool output</td>
                    <td>Tool returned 72&deg;F, agent said &ldquo;72 degrees&rdquo;</td>
                </tr>
                <tr>
                    <td><span class="badge-e">EMBELLISHED</span></td>
                    <td>Agent added claims beyond tool output</td>
                    <td>Tool returned temp only, agent added humidity</td>
                </tr>
                <tr>
                    <td><span class="badge-f">FABRICATED</span></td>
                    <td>Agent&rsquo;s response contradicts tool output</td>
                    <td>Tool returned 72&deg;F, agent said 85&deg;F</td>
                </tr>
                <tr>
                    <td><span class="badge-s">SKIPPED</span></td>
                    <td>Agent claimed a tool ran but it never did</td>
                    <td>No execution receipt exists</td>
                </tr>
                <tr>
                    <td><span class="badge-u">UNMONITORED</span></td>
                    <td>Tool not wrapped by ToolWitness</td>
                    <td>Outside monitoring scope</td>
                </tr>
            </tbody>
        </table>
    </div>
</section>"""


def _section_how_it_works() -> str:
    return """
<section id="how">
    <h2>How It Works</h2>

    <div class="steps">
        <div class="step">
            <div class="step-num">1</div>
            <h3>Wrap</h3>
            <p>Add ToolWitness to your agent with one line of code.
            Works with OpenAI, Anthropic, LangChain, MCP, and CrewAI.</p>
        </div>
        <div class="step-arrow">&rarr;</div>
        <div class="step">
            <div class="step-num">2</div>
            <h3>Execute</h3>
            <p>When a tool runs, ToolWitness generates an
            <strong>HMAC-signed receipt</strong>.
            The model never sees the signing key &mdash; it cannot
            forge a receipt.</p>
        </div>
        <div class="step-arrow">&rarr;</div>
        <div class="step">
            <div class="step-num">3</div>
            <h3>Verify</h3>
            <p>After the agent responds, ToolWitness compares claims
            against actual tool outputs using structural matching,
            schema conformance, and chain verification.</p>
        </div>
        <div class="step-arrow">&rarr;</div>
        <div class="step">
            <div class="step-num">4</div>
            <h3>Classify</h3>
            <p>Each tool interaction gets a classification
            (VERIFIED &rarr; SKIPPED) with a confidence score.
            Failures trigger alerts, show in the dashboard, and
            include fix suggestions.</p>
        </div>
    </div>

    <div class="adapters">
        <h3>Framework adapters</h3>
        <div class="adapter-list">
            <span class="adapter-badge">OpenAI</span>
            <span class="adapter-badge">Anthropic</span>
            <span class="adapter-badge">LangChain</span>
            <span class="adapter-badge">MCP</span>
            <span class="adapter-badge">CrewAI</span>
        </div>
        <p class="adapter-note">Each adapter is one line to add.
        ToolWitness intercepts tool calls transparently &mdash;
        your agent code doesn&rsquo;t change.</p>
    </div>
</section>"""


def _section_privacy() -> str:
    return """
<section id="privacy">
    <h2>Privacy &amp; Security</h2>
    <p class="section-intro">
        &ldquo;Will this steal my code?&rdquo; &mdash; No. Here&rsquo;s
        exactly what ToolWitness sees and doesn&rsquo;t see:
    </p>

    <div class="trust-box">
        <table class="trust-table">
            <thead><tr>
                <th>ToolWitness sees</th>
                <th>ToolWitness does NOT see</th>
            </tr></thead>
            <tbody>
                <tr>
                    <td>Tool function name + arguments</td>
                    <td>Your source code</td>
                </tr>
                <tr>
                    <td>Tool return value</td>
                    <td>Other files in your project</td>
                </tr>
                <tr>
                    <td>Agent&rsquo;s text response</td>
                    <td>Environment variables or secrets</td>
                </tr>
                <tr>
                    <td>Timing of tool calls</td>
                    <td>Network traffic outside tool calls</td>
                </tr>
                <tr>
                    <td>Nothing else</td>
                    <td>Your prompts, system messages, or history</td>
                </tr>
            </tbody>
        </table>
    </div>

    <div class="trust-grid">
        <div class="trust-card">
            <h4>Local-first</h4>
            <p>All data stored in local SQLite
            (<code>~/.toolwitness/</code>). File permissions set to
            <code>0600</code> on Unix. No cloud, no accounts.</p>
        </div>
        <div class="trust-card">
            <h4>No telemetry</h4>
            <p>Telemetry is <strong>off by default</strong>. ToolWitness
            does not phone home, ping any server, or transmit any data
            unless you explicitly enable cloud features.</p>
        </div>
        <div class="trust-card">
            <h4>No training</h4>
            <p>Your data is <strong>never used to train models</strong>.
            ToolWitness is a local tool, not a data collection service.</p>
        </div>
        <div class="trust-card">
            <h4>Fail-open</h4>
            <p>If ToolWitness itself has a bug, <strong>your tools still
            work</strong>. Internal errors are logged and the result is
            classified as UNMONITORED. We never block your agent.</p>
        </div>
        <div class="trust-card">
            <h4>Alert privacy</h4>
            <p>Webhook and Slack alerts support <strong>summary</strong>
            (classification + tool name only) or <strong>full</strong>
            (includes data). Sensitive environments use summary-only.</p>
        </div>
        <div class="trust-card">
            <h4>Open source</h4>
            <p>Apache 2.0 license. Every line of code is inspectable.
            No hidden data collection, no obfuscated binaries.</p>
        </div>
    </div>
</section>"""


def _section_install() -> str:
    return """
<section id="install">
    <h2>Install &amp; Quick Start</h2>

    <div class="install-block">
        <h3>Install</h3>
        <pre><code>pip install toolwitness</code></pre>
        <p>With framework adapters:</p>
        <pre><code>pip install toolwitness[openai]      # OpenAI
pip install toolwitness[anthropic]   # Anthropic
pip install toolwitness[langchain]   # LangChain
pip install toolwitness[mcp]         # MCP
pip install toolwitness[crewai]      # CrewAI</code></pre>
    </div>

    <div class="install-block">
        <h3>Basic usage (3 lines)</h3>
        <pre><code>from toolwitness import ToolWitnessDetector

detector = ToolWitnessDetector()

@detector.tool()
def get_weather(city: str) -> dict:
    return {"city": city, "temp_f": 72}

detector.execute_sync("get_weather", {"city": "Miami"})
results = detector.verify_sync("Miami is 72&deg;F.")
# classification=VERIFIED, confidence=0.95</code></pre>
    </div>

    <details class="install-block">
        <summary>OpenAI adapter</summary>
        <pre><code>from openai import OpenAI
from toolwitness.adapters.openai import wrap
from toolwitness.storage.sqlite import SQLiteStorage

client = wrap(OpenAI(), storage=SQLiteStorage())
# Use client normally &mdash; tool calls are monitored</code></pre>
    </details>

    <details class="install-block">
        <summary>Anthropic adapter</summary>
        <pre><code>from anthropic import Anthropic
from toolwitness.adapters.anthropic import wrap
from toolwitness.storage.sqlite import SQLiteStorage

client = wrap(Anthropic(), storage=SQLiteStorage())</code></pre>
    </details>

    <details class="install-block">
        <summary>LangChain middleware</summary>
        <pre><code>from toolwitness.adapters.langchain import ToolWitnessMiddleware

middleware = ToolWitnessMiddleware(
    on_fabrication="raise",
    storage=SQLiteStorage(),
)
# Add as a callback to your LangChain agent</code></pre>
    </details>

    <details class="install-block">
        <summary>MCP adapter</summary>
        <pre><code>from toolwitness.adapters.mcp import MCPMonitor

monitor = MCPMonitor()
monitor.on_tool_call(params={
    "name": "get_weather",
    "arguments": {"city": "Miami"},
})
monitor.on_tool_result(
    tool_name="get_weather",
    result={"temp_f": 72},
)
results = monitor.verify("Miami is 72&deg;F.")</code></pre>
    </details>

    <details class="install-block">
        <summary>CrewAI decorator</summary>
        <pre><code>from toolwitness.adapters.crewai import monitored_tool

@monitored_tool
def get_weather(city: str) -> str:
    return '{"city": "Miami", "temp_f": 72}'

output = get_weather(city="Miami")
results = get_weather.toolwitness.verify("Miami is 72&deg;F.")</code></pre>
    </details>

    <div class="install-block">
        <h3>CLI</h3>
        <pre><code>toolwitness check --last 5                         # Recent results
toolwitness check --fail-if "failure_rate > 0.05"  # CI gate
toolwitness stats                                  # Per-tool rates
toolwitness watch                                  # Live tail
toolwitness report --format html                   # HTML report
toolwitness dashboard                              # This dashboard
toolwitness export --format json                   # Data export</code></pre>
    </div>
</section>"""


def _section_unique() -> str:
    return """
<section id="unique">
    <h2>What Makes ToolWitness Unique</h2>

    <div class="unique-grid">
        <div class="unique-card">
            <h4>Category-defining</h4>
            <p>&ldquo;Silent failure detection&rdquo; is barely named as
            a category. ToolWitness defines it &mdash; the first tool
            purpose-built to verify agent truthfulness.</p>
        </div>
        <div class="unique-card">
            <h4>Framework-agnostic</h4>
            <p>Five adapters across the major agent frameworks.
            Not locked to one ecosystem. Swap OpenAI for Anthropic
            &mdash; ToolWitness still works.</p>
        </div>
        <div class="unique-card">
            <h4>Cryptographic proof</h4>
            <p>HMAC-signed execution receipts that the model
            <strong>cannot forge</strong>. Not just logging &mdash;
            mathematical proof that a tool actually ran.</p>
        </div>
        <div class="unique-card">
            <h4>Multi-turn chain verification</h4>
            <p>Catches data corruption across sequential tool calls.
            If Tool B&rsquo;s input doesn&rsquo;t match Tool A&rsquo;s
            output, ToolWitness flags the chain break.</p>
        </div>
        <div class="unique-card">
            <h4>Built-in remediation</h4>
            <p>Not just &ldquo;you have a problem&rdquo; but
            &ldquo;here&rsquo;s how to fix it.&rdquo; Every failure
            includes actionable fix suggestions with code examples.</p>
        </div>
        <div class="unique-card">
            <h4>Free and local</h4>
            <p>No account. No cloud. No cost. Install, run, and see
            results in under a minute. Open source forever.</p>
        </div>
    </div>
</section>"""


def _css() -> str:
    return """<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background: #0f172a; color: #e2e8f0; line-height: 1.6; }

nav { position: sticky; top: 0; z-index: 50; background: #1e293b;
  border-bottom: 1px solid #334155; padding: 0.75rem 2rem;
  display: flex; justify-content: space-between; align-items: center;
  max-width: 1200px; margin: 0 auto; }
.nav-brand { color: #f1f5f9; text-decoration: none; font-weight: 700;
  font-size: 1rem; }
.nav-links { display: flex; gap: 1.5rem; }
.nav-links a { color: #94a3b8; text-decoration: none; font-size: 0.85rem;
  font-weight: 500; }
.nav-links a:hover, .nav-links a.active { color: #f1f5f9; }

section { max-width: 1000px; margin: 0 auto; padding: 3rem 2rem; }
footer { max-width: 1000px; margin: 0 auto; padding: 2rem;
  border-top: 1px solid #334155; color: #475569; font-size: 0.8rem;
  text-align: center; }
footer a { color: #93c5fd; text-decoration: none; }

h2 { font-size: 1.5rem; margin-bottom: 1rem; color: #f1f5f9; }
h3 { font-size: 1.1rem; margin-bottom: 0.75rem; color: #e2e8f0; }
h4 { font-size: 0.95rem; margin-bottom: 0.4rem; color: #f1f5f9; }
.section-intro { color: #94a3b8; margin-bottom: 1.5rem; font-size: 1.05rem; }

/* Hero */
.hero { text-align: center; padding: 5rem 2rem 4rem; }
.hero h1 { font-size: 2.5rem; line-height: 1.2; margin-bottom: 1.25rem;
  background: linear-gradient(135deg, #e2e8f0 0%, #93c5fd 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text; }
.hero-sub { font-size: 1.15rem; color: #94a3b8; max-width: 700px;
  margin: 0 auto 2rem; }
.hero-cta { display: flex; gap: 1rem; justify-content: center; }
.btn { padding: 0.6rem 1.5rem; border-radius: 8px; text-decoration: none;
  font-weight: 600; font-size: 0.9rem; transition: all 0.2s; }
.btn-primary { background: #3b82f6; color: white; }
.btn-primary:hover { background: #2563eb; }
.btn-secondary { background: #334155; color: #e2e8f0;
  border: 1px solid #475569; }
.btn-secondary:hover { background: #475569; }

/* Problem */
.two-col { display: grid; grid-template-columns: 1fr 1fr;
  gap: 1.25rem; margin-bottom: 2rem; }
.problem-card { background: #1e293b; padding: 1.5rem; border-radius: 12px;
  border: 1px solid #334155; }
.problem-icon { font-size: 2rem; margin-bottom: 0.75rem; color: #ef4444; }
.comparison { margin: 2rem 0; }

table { width: 100%; border-collapse: collapse; margin-top: 0.75rem; }
th, td { text-align: left; padding: 0.6rem 0.75rem;
  border-bottom: 1px solid #334155; font-size: 0.85rem; }
th { color: #64748b; font-size: 0.7rem; text-transform: uppercase;
  letter-spacing: 0.05em; background: #1e293b; }
.yes { color: #4ade80; }
.no { color: #f87171; font-weight: 600; }
.partial { color: #fbbf24; }
.highlight-row { background: #172554; }
.highlight-row td { border-bottom-color: #1e3a5f; }

.badge-v { background: #052e16; color: #4ade80; padding: 0.15rem 0.5rem;
  border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
.badge-e { background: #422006; color: #fcd34d; padding: 0.15rem 0.5rem;
  border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
.badge-f { background: #450a0a; color: #fca5a5; padding: 0.15rem 0.5rem;
  border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
.badge-s { background: #450a0a; color: #fca5a5; padding: 0.15rem 0.5rem;
  border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
.badge-u { background: #1e293b; color: #94a3b8; padding: 0.15rem 0.5rem;
  border-radius: 4px; font-size: 0.75rem; font-weight: 700; }

.classification-table { margin-top: 2rem; }

/* How it works */
.steps { display: flex; align-items: flex-start; gap: 0.5rem;
  margin-bottom: 2rem; flex-wrap: wrap; justify-content: center; }
.step { background: #1e293b; padding: 1.25rem; border-radius: 12px;
  border: 1px solid #334155; flex: 1; min-width: 180px; max-width: 220px; }
.step-num { width: 32px; height: 32px; border-radius: 50%;
  background: #3b82f6; color: white; display: flex; align-items: center;
  justify-content: center; font-weight: 700; font-size: 0.9rem;
  margin-bottom: 0.75rem; }
.step-arrow { color: #475569; font-size: 1.5rem; padding-top: 2rem; }

.adapters { text-align: center; margin-top: 1rem; }
.adapter-list { display: flex; gap: 0.75rem; justify-content: center;
  flex-wrap: wrap; margin: 0.75rem 0; }
.adapter-badge { background: #334155; color: #e2e8f0;
  padding: 0.4rem 1rem; border-radius: 6px; font-size: 0.85rem;
  font-weight: 600; border: 1px solid #475569; }
.adapter-note { color: #64748b; font-size: 0.85rem; margin-top: 0.5rem; }

/* Privacy */
.trust-box { background: #0c1222; border: 2px solid #1e3a5f;
  border-radius: 12px; padding: 1.5rem; margin-bottom: 2rem; }
.trust-table th { background: #0c1222; }
.trust-table td:first-child { color: #4ade80; }
.trust-table td:last-child { color: #f87171; }

.trust-grid { display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 1rem; }
.trust-card { background: #1e293b; padding: 1.25rem; border-radius: 10px;
  border: 1px solid #334155; }
.trust-card h4 { color: #93c5fd; }

/* Install */
.install-block { background: #1e293b; padding: 1.25rem; border-radius: 10px;
  border: 1px solid #334155; margin-bottom: 1rem; }
.install-block h3 { margin-bottom: 0.5rem; }
pre { background: #0f172a; padding: 0.75rem 1rem; border-radius: 6px;
  overflow-x: auto; font-size: 0.8rem; line-height: 1.5;
  margin: 0.5rem 0; }
code { font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  color: #93c5fd; }
details { cursor: pointer; }
details summary { color: #93c5fd; font-weight: 600; font-size: 0.9rem;
  padding: 0.5rem 0; }
details[open] summary { margin-bottom: 0.5rem; }

/* Unique */
.unique-grid { display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 1rem; }
.unique-card { background: #1e293b; padding: 1.25rem; border-radius: 10px;
  border: 1px solid #334155; }
.unique-card h4 { color: #93c5fd; }

@media (max-width: 800px) {
  .hero h1 { font-size: 1.75rem; }
  .two-col, .trust-grid, .unique-grid {
    grid-template-columns: 1fr; }
  .steps { flex-direction: column; align-items: center; }
  .step-arrow { transform: rotate(90deg); padding: 0; }
  .step { max-width: 100%; }
}
</style>"""
