## ADDED Requirements

### Requirement: Non-HTTP subscribers are first-class consumers of the event stream
The SessionRunner subscriber interface (`add_subscriber()` / `remove_subscriber(queue)`) SHALL support non-HTTP consumers — including the bus gateway — on the same terms as SSE subscribers. A subscriber SHALL NOT need to be tied to an HTTP request lifecycle to attach.

Non-HTTP subscribers SHALL NOT be distinguished from SSE subscribers inside `SessionRunner`; the runner SHALL treat all subscriber queues uniformly for fan-out, slow-subscriber handling, and idle-exit counting.

#### Scenario: Bus gateway attaches as a subscriber
- **WHEN** `Gateway._process_message` calls `runner.add_subscriber()` outside of any HTTP request
- **THEN** the returned `asyncio.Queue[StreamEvent]` SHALL receive every event the runner fans out for the rest of the turn
- **AND** the runner SHALL include this subscriber when evaluating `len(self.subscribers) == 0` for idle-exit

#### Scenario: Bus subscriber counts toward keep-alive
- **WHEN** a SessionRunner has been idle 65 seconds but a bus gateway subscriber is still attached awaiting `done`
- **THEN** the runner SHALL NOT exit (len(subscribers) > 0)
- **AND** the runner SHALL continue serving fanned-out events to the bus subscriber

### Requirement: Non-HTTP subscribers MUST detach deterministically
Any non-HTTP subscriber SHALL detach via `remove_subscriber(queue)` no later than one of:
- receipt of a `StreamEvent` of type `"done"` on the queue, OR
- a consumer-chosen idle timeout (300 seconds for the bus gateway), OR
- an exception in the consumer's await loop (detach in a `finally` block).

Failure to detach SHALL cause the runner's subscriber set to leak; this requirement is the contract that prevents that leak.

#### Scenario: Bus subscriber detaches on done
- **WHEN** the bus gateway's subscriber queue receives a `done` StreamEvent
- **THEN** the bus gateway SHALL call `runner.remove_subscriber(queue)`
- **AND** the runner's `self.subscribers` set SHALL no longer contain that queue

#### Scenario: Bus subscriber detaches on timeout
- **WHEN** the bus gateway's subscriber queue has not received any event for 300 seconds
- **THEN** the bus gateway SHALL call `runner.remove_subscriber(queue)` in a finally block
- **AND** the runner's subscriber count SHALL decrement

#### Scenario: Bus subscriber detaches on exception
- **WHEN** the bus gateway's event-await loop raises an unexpected exception
- **THEN** the finally block SHALL call `runner.remove_subscriber(queue)`
- **AND** the subscriber queue SHALL NOT leak into `self.subscribers`
