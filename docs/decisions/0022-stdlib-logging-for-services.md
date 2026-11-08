# 0022. Services log through stdlib logging with structured fields

Status: accepted; the JSON formatter it left for later now exists (0051), services unchanged

Context: `.claude/rules/layers.md` says to log structured JSON through the logging port. `core/ports.py` has no logging port and core is off limits for this task.
Decision: Services use `logging.getLogger(__name__)`. The source, attempt, delay and reason are written into the message text, so they appear with the default formatter, and also passed in `extra` (`source`, `attempt`, `delay_seconds`, `reason`). No JSON formatter is installed yet. Logged values are source names and adapter error text, never credentials, titles or email content.
Alternative: Add a `Logger` port to core, or install a JSON formatter in the composition root now.
Reason: The reason reaches the log output today, and the `extra` fields let a JSON formatter configured in the composition root later emit them without changing services.
Where: `src/command_center/services/sync.py`.
Revisit when: A logging port is added to core, the composition root configures JSON output, or structured JSON logging with correlation id arrives with distributed mode.
