# jagarin-research

Research artifacts for **Jagarin** — an AI-native personal duty agent system built on three
interlocking contributions: the DAWN scoring heuristic, the ARIA commercial identity layer,
and the ACE protocol for institutional-to-agent communication.

---

## Papers

| Title | arXiv |
|-------|-------|
| Jagarin: A Hibernating Personal Duty Agent with Ephemeral Cloud Escalation | [arXiv:2603.05069](https://arxiv.org/abs/2603.05069) |
| DAWN: A Duty-Aware Wake Network Heuristic for Adaptive Mobile Agent Scheduling | forthcoming |
| ACE: An Agent-Centric Exchange Protocol for Institutional-to-Personal-Agent Communication | forthcoming |

---

## Evaluation (`eval/`)

Monte Carlo simulation comparing DAWN against three fixed-threshold baselines across all 12
duty types (1 000 trials each, seed 42).

```bash
python eval/dawn_simulation.py
```

Produces a precision × fire-rate table and saves `dawn_eval_results.json`.
Results cited in Table 1 of paper2.

---

## Formal Specification (`ace/`)

TLA⁺ model of the ACE message lifecycle. Verified properties:

| Property | Type | Description |
|----------|------|-------------|
| `NoSilentLoss` | Safety | Every received message reaches REGISTERED or REJECTED |
| `ScopeCompliance` | Safety | Agent never acts outside declared ACE-SCOPE |
| `RegistrationValidity` | Safety | Every registered duty is DAWN-computable |
| `EventualTermination` | Liveness | Every received message eventually terminates |
| `EventualRegistration` | Liveness | Every valid message eventually registers a duty |

Run with TLC model checker:

```bash
tlc ace/ace_lifecycle.tla -config ace/ace_lifecycle.cfg
```

JSON-LD context for ACE semantic layer: [`ace/ace_jsonld_context.json`](ace/ace_jsonld_context.json)

---

## Related Repositories

- **[jagarin](https://github.com/ravikiran438/jagarin)** — Flutter app (DAWN engine, 4-tab inbox, notification system) *(coming soon)*
- **[jagarin-backend](https://github.com/ravikiran438/jagarin-backend)** — FastAPI backend (ARIA relay, ACE ingest, ephemeral Gemini agent)

---

## Citation

If you use this work, please cite:

```bibtex
@misc{kadaboina2026jagarin,
  title  = {Jagarin: A Hibernating Personal Duty Agent with Ephemeral Cloud Escalation},
  author = {Kadaboina, Ravi Kiran},
  year   = {2026},
  eprint = {2603.05069},
  archivePrefix = {arXiv}
}
```

---

## License

Code (`eval/`, `ace/`) — [MIT License](LICENSE)
Papers (`papers/`) — [CC BY-NC-ND 4.0](papers/LICENSE) — attribution required, no commercial use, no derivatives

Patent rights reserved separately. The license governs copyright only.
