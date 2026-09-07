# tau2 airline integration

A Supervisor + Lookup + Booking LangGraph team running on the τ²-bench airline environment
(vendored under `vendor/`, MIT, see `vendor/VENDOR.md`). The environment gives us real tools, a
real database, and an objective evaluator (DB replay + communicated facts) with no LLM judge.

```
python -m firebreak.integrations.tau2_airline.runner --task 39 --model fake
python -m firebreak.integrations.tau2_airline.runner --task 39 --model fake \
    --inject message_corruption:lookup:1:swap_first_eligible_reservation --out cascade.jsonl
```

The first cascade: the lookup specialist's report to the supervisor is corrupted so that one
reservation eligible for cancellation is swapped with one that is not. The supervisor believes
the report, instructs booking, and booking cancels the wrong reservation. The τ² evaluator then
fails the task. Firebreak reports the source, the path lookup → supervisor → booking →
`cancel_reservation`, and the harmful action.

`--model openai` runs the same team on any OpenAI-compatible endpoint (`OPENAI_BASE_URL`,
`FIREBREAK_MODEL`); the customer is then played by the vendored τ² user simulator.
