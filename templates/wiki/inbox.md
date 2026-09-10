# Inbox

Facts the agent ran into but could not file: no existing page fits, and the
shape of a new page is not clear yet (one fact alone rarely justifies a page).
Each line is a single unfiled fact, plain prose, with its source.

Line format:

    - <fact, one sentence> (source: <session id, file path, URL, or "conversation with <role>">, seen: <YYYY-MM-DD>)

When two or three inbox lines turn out to be the same topic, that is a new
page: create `pages/<slug>.md`, move the facts into it, add it to `index.md`,
and delete the lines here.

<!-- entries below this line -->
