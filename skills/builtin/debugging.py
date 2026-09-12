"""Built-in skill: debugging patterns."""

NAME = "debugging"
DESCRIPTION = "Systematic debugging methodology"
TRIGGERS = ["bug", "error", "crash", "fail", "broken", "debug", "fix", "trace", "stack trace"]

PROMPT = """
You are in DEBUGGING mode. Follow this systematic approach:

1. REPRODUCE: Can you trigger the bug reliably? What are the exact steps?
2. ISOLATE: Narrow down WHERE it happens. Use binary search on code changes.
3. HYPOTHESIZE: What's your theory? What would CONFIRM it? What would DISPROVE it?
4. TEST HYPOTHESIS: Add logging, check state, trace execution. Be the scientist.
5. FIX: Once confirmed, apply minimal fix. Don't refactor unrelated code.
6. PREVENT: Add a test that catches this bug. How could this class of bug be prevented?

Common patterns to check first:
- Null/None access (AttributeError, NullPointerException)
- Off-by-one errors (index out of bounds)
- Race conditions (check for async/threaded code)
- Type mismatches (wrong type passed)
- State corruption (check mutation side effects)
- Missing await (async code)
- Incorrect assumptions (validate ALL inputs)
"""