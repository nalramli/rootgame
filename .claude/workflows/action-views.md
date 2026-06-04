---
description: Rules and examples for writing Action Views
---

## Purpose

Corresponds with a game action that can be taken. The view walks the user through the choices they need to make to do the game action. In the final step, the view will call a transaction function to modify the game state and respond with "completed" so that the client knows something has changed.

Base definition: `GameActionView` (`game/views/action_views/general.py`)

---

## Structure

- **GET**: Returns the first step. Use `self.first_step` if static; compute in `get()` if the first step depends on DB state (e.g. an Event view whose GET varies based on current event state).
- **POST**: All POSTs route through `post()` → `route_post()`. Each route calls a `post_<name>` method that either returns the next step (`generate_step`) or executes and completes.
- **Execution pattern**: Every handler that executes a transaction should be named `post_execute_<action>`, registered in `route_post`, and always end with `return self.generate_completed_step()`. Non-execution handlers validate inputs and return the next `generate_step`.
- **Validation**: Override `validate_player` and `validate_timing`. Use `isinstance()` checks to avoid cross-phase collisions.
- **Events**: If a pending `Event` model drives the view's multi-phase flow, use the re-GET state machine pattern (see below) rather than returning the next step inline from a `post_execute_*` handler.
- **Schema tagging**: Always use `@extend_schema` on GET and POST. Required for frontend type safety.
- **Transactions**: Call with `atomic_game_action(fn)(...)` inside a try/except that re-raises as `ValidationError`.

---

## Step Generation

### `generate_step(name, prompt, endpoint, payload_details, accumulated_payload, options, request, game_id)`
Returns the next step to the client. Pass `request=request, game_id=game_id` to opt into mid-flow interceptor checking (see Interceptors below).

### `generate_completing_step(accumulated_payload, request, game_id, execution_route)`
Used when all inputs have been collected and the next action is execution. Checks interceptors first:
- **If an interceptor condition fires**: returns the interceptor's entry step; embeds `_execution_route` and all payload in `accumulated_payload` for later resume.
- **If no interceptor fires**: calls `self.route_post(request, game_id, execution_route)` directly — i.e. the `post_execute_<action>` handler runs immediately and returns `completed`.

### `generate_completed_step()`
Returns `{"name": "completed"}`. Always the final return from a `post_execute_*` handler.

---

## Event State Machine (re-GET pattern)

Use this pattern when a view spans multiple distinct phases that are each persisted to a DB `Event` model — i.e. the boundary between phases can survive a server restart or be inspected from the outside.

**Rule**: every `post_execute_*` handler executes exactly one atomic action and returns `generate_completed_step()`. It never decides what comes next. The client re-GETs after every `completed`, and `get()` reads the event's current DB state to determine which step to serve.

```
GET  → event.move_completed=False → serve "use_or_skip" step

POST /execute_move  → emigre_move(...)  → completed
GET  → event.move_completed=True  → serve "battle_choice" step

POST /execute_battle → emigre_battle(...) → completed
GET  → event is resolved, no longer current → normal turn action
```

**Why not return the next step inline from `post_execute_move`?**  
The transaction may have side effects that change which step is correct (e.g. `emigre_move` calls `emigre_failure` when the destination has no enemies, which resolves the event entirely). The `get()` re-read handles all outcomes uniformly without branching logic in the POST handler.

**Contrast with single-phase views**: a view that collects inputs and executes once (e.g. `RatsCommandMoveView`) does not need this pattern — `generate_completing_step` → `post_execute_move` → `completed` is the full flow.

---

## Interceptors

An `InterceptorActionView` is a reusable sub-flow that injects itself between steps of a parent view when a condition is met. State travels entirely through `accumulated_payload` — no DB model needed.

### Declaring interceptors on a parent view

```python
class MyView(GameActionView):
    interceptors = [{"view": WarlordMoveInterceptorView()}]
```

An optional `"condition"` key can override the interceptor's default condition:
```python
interceptors = [{"view": WarlordMoveInterceptorView(), "condition": my_condition_fn}]
# condition signature: (parent_view, request, game_id) -> bool
```

### Two interception modes

**Terminal** (most common): fired from `generate_completing_step`. Use when all step data is collected and the next step is execution.

```
POST /count   →  post_count validates, calls generate_completing_step(..., execution_route="execute_move")
                 → interceptor fires → returns interceptor step; payload includes _execution_route
POST /warlord →  interceptor handles, pass_back → _resume_after_interceptor
                 → no _deferred_step → reads _execution_route → route_post → post_execute_move → completed
```

**Mid-flow**: fired from `generate_step(..., request=request, game_id=game_id)`. Use when the interceptor answer needs to be carried forward as accumulated payload into a later step.

```
POST /origin  →  post_origin calls generate_step("destination", ..., request=r, game_id=g)
                 → interceptor fires → returns interceptor step; _deferred_step embedded in payload
POST /warlord →  interceptor handles, pass_back → _resume_after_interceptor
                 → _deferred_step present → merges interceptor answer into acc payload → returns deferred step
POST /destination → resumes normal flow, move_warlord is in request.data
```

### Writing an `InterceptorActionView`

Subclass `InterceptorActionView`. Define:
- `interceptor_name: str` — unique identifier
- `interceptor_routes: list[str]` — route names this interceptor owns (e.g. `["warlord"]`)
- `condition(view, request, game_id) -> bool` — when to activate
- `entry_step(request, game_id, context_payload) -> dict` — first step shown to the player
- `route_post` / `post_<route>` handlers — call `self.pass_back(request)` when done

`pass_back(request)` signals completion; all collected data is already in `request.data`.

Existing interceptors: `WarlordMoveInterceptorView` (`game/views/action_views/rats/interceptors.py`) — fires when the Rats Warlord is in the origin clearing of any move.

---

## payload_details

- Clearings: `clearing_number`
- Cards: name string, looked up in `CardsEP` TextChoice
- Factions/players: faction name string, looked up in `Faction` TextChoice
- **No primary keys** in action views — use descriptive names/labels
- **Route naming**: kebab-case (e.g. `/api/woodland-alliance/...`)

---

## Examples

- `game/views/action_views/battle.py`
- `game/views/action_views/wa/daylight.py`
- `game/views/action_views/rats/daylight.py` — `RatsCommandMoveView` (terminal interceptor pattern)
- `game/views/action_views/crafted_cards/eyrie_emigre.py` — re-GET state machine pattern: `get()` branches on `event.move_completed`; `post_execute_move` and `post_execute_battle` each return `completed` and leave the next-step decision to the next `get()`. Also uses terminal interceptor for the Warlord move.
- `game/views/action_views/rats/interceptors.py` — `WarlordMoveInterceptorView`
