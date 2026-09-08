# Episode — tau2_task39_qwen14b_clean.jsonl

episode `tau2-39-7e8e66` · thread `tau2-39-7e8e66` · 3 turns
τ² task 39 · model openai · outcome PASSED · faults none

```
EpisodeGraph
  └── TurnGraph
        └── TaskRun
              └── Event
```

A turn is a Firebreak-assigned analysis unit, stamped by whoever recorded the run. By convention one external interaction is recorded as one turn, but nothing enforces that. `step` is LangGraph's super-step counter for the whole thread, so a turn's steps do not start at zero and one step can hold several task runs.

## Episode

| turn | invokes | steps | agent tasks | events | checkpoints | wall time |
|---|---|---|---|---|---|---|
| 0 | 1 | -1–1 | 1 | 14 | 3 | 1.4s |
| 1 | 1 | 2–6 | 3 | 52 | 5 | 18.1s |
| 2 | 1 | 7–11 | 3 | 40 | 5 | 18.2s |

The dotted `next` arrows are recording order, not causality. The 2 thick arrows are relations that actually cross a turn boundary.

```mermaid
flowchart LR
  turn_0["<b>turn 0</b><br/>1 agent tasks · steps -1–1<br/>14 events · 3 checkpoints"]
  turn_1["<b>turn 1</b><br/>3 agent tasks · steps 2–6<br/>52 events · 5 checkpoints"]
  turn_2["<b>turn 2</b><br/>3 agent tasks · steps 7–11<br/>40 events · 5 checkpoints"]
  turn_0 -.->|next| turn_1
  turn_1 -.->|next| turn_2
  turn_0 ==>|derived_from · verified<br/>messages:v3| turn_1
  turn_1 ==>|derived_from · verified<br/>messages:v8| turn_2
  classDef turn fill:#eef7ff,stroke:#4477aa;
  class turn_0,turn_1,turn_2 turn;
```

### Relations that cross a turn boundary

| kind | from turn | to turn | carrier | evidence |
|---|---|---|---|---|
| `derived_from` (verified) | 0 | 1 | `messages:v3` | element ids recorded per version |
| `derived_from` (verified) | 1 | 2 | `messages:v8` | element ids recorded per version |

## Turn 0

1 agent task runs (`supervisor@1`), 1 internal, 3 state versions, 3 WRITE · 1 READ · 1 TRIGGER · 1 DERIVED_FROM, 0 in / 1 out across the boundary.

```mermaid
flowchart LR
  t___input____1__turn_0_(["__input__@-1 (turn 0)"])
  t_supervisor_1__turn_0_["supervisor@1 (turn 0)"]
  s_branch_to_supervisor_v2{{"branch:to:supervisor:v2"}}
  s_messages_v2(("messages:v2"))
  s_messages_v3(("messages:v3"))
  x_out_0[/"turn 1<br/>messages:v5"/]
  t___input____1__turn_0_ -->|WRITE| s_messages_v2
  t___input____1__turn_0_ -->|WRITE| s_branch_to_supervisor_v2
  t_supervisor_1__turn_0_ -->|WRITE| s_messages_v3
  s_messages_v2 -->|READ| t_supervisor_1__turn_0_
  s_branch_to_supervisor_v2 -.->|TRIGGER| t_supervisor_1__turn_0_
  s_messages_v2 -. verified .-> s_messages_v3
  s_messages_v3 -. derived · verified .-> x_out_0
  classDef state fill:#fff3c4,stroke:#b8860b;
  classDef boundary fill:#f0f0f0,stroke:#999,stroke-dasharray:3 3;
  class s_branch_to_supervisor_v2,s_messages_v2,s_messages_v3 state;
```

## Turn 1

3 agent task runs (`supervisor@4`, `lookup@5`, `supervisor@6`), 1 internal, 7 state versions, 7 WRITE · 3 READ · 3 TRIGGER · 3 DERIVED_FROM, 1 in / 1 out across the boundary.

```mermaid
flowchart LR
  t___input___2__turn_1_(["__input__@2 (turn 1)"])
  t_supervisor_4__turn_1_["supervisor@4 (turn 1)"]
  t_lookup_5__turn_1_["lookup@5 (turn 1)"]
  t_supervisor_6__turn_1_["supervisor@6 (turn 1)"]
  s_branch_to_supervisor_v5{{"branch:to:supervisor:v5"}}
  s_messages_v5(("messages:v5"))
  s_branch_to_lookup_v6{{"branch:to:lookup:v6"}}
  s_messages_v6(("messages:v6"))
  s_branch_to_supervisor_v7{{"branch:to:supervisor:v7"}}
  s_messages_v7(("messages:v7"))
  s_messages_v8(("messages:v8"))
  x_in_0[/"turn 0<br/>messages:v3"/]
  x_out_0[/"turn 2<br/>messages:v10"/]
  t___input___2__turn_1_ -->|WRITE| s_messages_v5
  t___input___2__turn_1_ -->|WRITE| s_branch_to_supervisor_v5
  t_supervisor_4__turn_1_ -->|WRITE| s_messages_v6
  t_supervisor_4__turn_1_ -->|WRITE| s_branch_to_lookup_v6
  t_lookup_5__turn_1_ -->|WRITE| s_messages_v7
  t_lookup_5__turn_1_ -->|WRITE| s_branch_to_supervisor_v7
  t_supervisor_6__turn_1_ -->|WRITE| s_messages_v8
  s_messages_v5 -->|READ| t_supervisor_4__turn_1_
  s_messages_v6 -->|READ| t_lookup_5__turn_1_
  s_messages_v7 -->|READ| t_supervisor_6__turn_1_
  s_branch_to_supervisor_v5 -.->|TRIGGER| t_supervisor_4__turn_1_
  s_branch_to_lookup_v6 -.->|TRIGGER| t_lookup_5__turn_1_
  s_branch_to_supervisor_v7 -.->|TRIGGER| t_supervisor_6__turn_1_
  s_messages_v5 -. verified .-> s_messages_v6
  s_messages_v6 -. verified .-> s_messages_v7
  s_messages_v7 -. verified .-> s_messages_v8
  x_in_0 -. derived · verified .-> s_messages_v5
  s_messages_v8 -. derived · verified .-> x_out_0
  classDef state fill:#fff3c4,stroke:#b8860b;
  classDef boundary fill:#f0f0f0,stroke:#999,stroke-dasharray:3 3;
  class s_branch_to_lookup_v6,s_branch_to_supervisor_v5,s_branch_to_supervisor_v7,s_messages_v5,s_messages_v6,s_messages_v7,s_messages_v8 state;
```

## Turn 2

3 agent task runs (`supervisor@9`, `booking@10`, `supervisor@11`), 1 internal, 7 state versions, 7 WRITE · 3 READ · 3 TRIGGER · 3 DERIVED_FROM, 1 in / 0 out across the boundary.

```mermaid
flowchart LR
  t___input___7__turn_2_(["__input__@7 (turn 2)"])
  t_supervisor_9__turn_2_["supervisor@9 (turn 2)"]
  t_booking_10__turn_2_["booking@10 (turn 2)"]
  t_supervisor_11__turn_2_["supervisor@11 (turn 2)"]
  s_branch_to_supervisor_v10{{"branch:to:supervisor:v10"}}
  s_messages_v10(("messages:v10"))
  s_branch_to_booking_v11{{"branch:to:booking:v11"}}
  s_messages_v11(("messages:v11"))
  s_branch_to_supervisor_v12{{"branch:to:supervisor:v12"}}
  s_messages_v12(("messages:v12"))
  s_messages_v13(("messages:v13"))
  x_in_0[/"turn 1<br/>messages:v8"/]
  t___input___7__turn_2_ -->|WRITE| s_messages_v10
  t___input___7__turn_2_ -->|WRITE| s_branch_to_supervisor_v10
  t_supervisor_9__turn_2_ -->|WRITE| s_messages_v11
  t_supervisor_9__turn_2_ -->|WRITE| s_branch_to_booking_v11
  t_booking_10__turn_2_ -->|WRITE| s_messages_v12
  t_booking_10__turn_2_ -->|WRITE| s_branch_to_supervisor_v12
  t_supervisor_11__turn_2_ -->|WRITE| s_messages_v13
  s_messages_v10 -->|READ| t_supervisor_9__turn_2_
  s_messages_v11 -->|READ| t_booking_10__turn_2_
  s_messages_v12 -->|READ| t_supervisor_11__turn_2_
  s_branch_to_supervisor_v10 -.->|TRIGGER| t_supervisor_9__turn_2_
  s_branch_to_booking_v11 -.->|TRIGGER| t_booking_10__turn_2_
  s_branch_to_supervisor_v12 -.->|TRIGGER| t_supervisor_11__turn_2_
  s_messages_v10 -. verified .-> s_messages_v11
  s_messages_v11 -. verified .-> s_messages_v12
  s_messages_v12 -. verified .-> s_messages_v13
  x_in_0 -. derived · verified .-> s_messages_v10
  classDef state fill:#fff3c4,stroke:#b8860b;
  classDef boundary fill:#f0f0f0,stroke:#999,stroke-dasharray:3 3;
  class s_branch_to_booking_v11,s_branch_to_supervisor_v10,s_branch_to_supervisor_v12,s_messages_v10,s_messages_v11,s_messages_v12,s_messages_v13 state;
```

---

Relation-level evidence and the field each relation came from are in the `.provenance.txt` and `.provenance.md` beside this file.
