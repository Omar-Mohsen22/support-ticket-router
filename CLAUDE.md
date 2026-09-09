# Working rules

- LANGUAGE RULE: speak to me in Egyptian colloquial Arabic in every reply, explanation and summary, keeping technical terms in English. Everything WRITTEN TO DISK stays English: code, comments, docstrings, README, reports, commit messages, PROGRESS.md. Never write Arabic into a file.
- Do exactly ONE numbered step per instruction. Never start the next step, never "improve" earlier steps unless told.
- Before starting any step, read PROGRESS.md to see where we are.
- When you finish a step, explain to me in Arabic what you did, why you made each non-obvious choice, and what any new technical term means — assume I want to learn, not just receive files.
- After finishing a step, append a PROGRESS.md entry: step number, what was built, files added/changed, the exact command to verify it, and what step comes next.
- Commit at the end of every step. Message format: "step-XX: short summary". Author is Omar only. Never add Co-Authored-By or any AI attribution line.
- If an assumption in the instruction turns out to be wrong (a column does not exist, a label set differs, a package fails), STOP immediately and report it. Do not invent a workaround.
- Never add a dependency without naming it in the report and saying why.
- Every script must run standalone from the repo root with a documented command.
