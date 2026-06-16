/**
 * Fetch top-level comments AND their nested replies for a batch of post URNs
 * using LinkedIn's internal Voyager API.
 *
 * Called via: page.evaluate(FETCH_COMMENTS_JS, [urns, maxTopLevel, maxRepliesPerComment])
 *   urns                 – array of LinkedIn post URNs
 *   maxTopLevel          – max top-level comments per post (default 50)
 *   maxRepliesPerComment – max replies per top-level comment (default 25)
 *
 * Returns: { [urn]: [{author, text, has_external_url, is_reply, comment_urn, parent_comment_urn, rank}] }
 */
async ([urns, maxTopLevel, maxRepliesPerComment]) => {
    maxTopLevel          = maxTopLevel          || 50;
    maxRepliesPerComment = maxRepliesPerComment || 25;

    // ── Auth: CSRF token from cookie ─────────────────────────────────────────
    const csrf = document.cookie
        .split("; ")
        .find(r => r.startsWith("JSESSIONID="))
        ?.split("=")[1]
        ?.replace(/"/g, "");
    if (!csrf) return { _error: "no_csrf" };

    const URL_RE = /https?:\/\/[^\s"'<>]+/;

    function apiHeaders() {
        return {
            "csrf-token":                csrf,
            "accept":                    "application/json",
            "x-restli-protocol-version": "2.0.0",
        };
    }

    // ── Field extractors (defensive – LinkedIn changes paths between versions) ──
    function extractText(el) {
        return el?.commentary?.text?.text      ||
               el?.commentary?.text            ||
               el?.comment?.values?.[0]?.value ||
               null;
    }

    function extractAuthor(el) {
        return el?.commenter?.name?.text ||
               el?.commenter?.name       ||
               el?.actor?.name?.text     ||
               el?.actor?.name           ||
               null;
    }

    /**
     * Grab the LinkedIn comment URN.
     * The Voyager API exposes it under several possible keys depending on
     * the decoration version; try all common ones.
     */
    function extractCommentUrn(el) {
        return el?.["$id"]            ||
               el?.entityUrn          ||
               el?.urn                ||
               el?.commentV2?.["$id"] ||
               null;
    }

    function makeComment(el, isReply, parentUrn) {
        const text = extractText(el);
        if (!text) return null;
        return {
            author:             String(extractAuthor(el) || ""),
            text:               String(text),
            has_external_url:   URL_RE.test(String(text)),
            is_reply:           Boolean(isReply),
            comment_urn:        extractCommentUrn(el) || null,
            parent_comment_urn: parentUrn || null,
        };
    }

    // ── Generic paged fetch ──────────────────────────────────────────────────
    async function pagedFetch(baseUrl, maxItems, isReply, parentUrn) {
        const items = [];
        let   start = 0;
        const PAGE  = 25;

        while (items.length < maxItems) {
            let data;
            try {
                const resp = await fetch(`${baseUrl}&count=${PAGE}&start=${start}`, {
                    credentials: "include",
                    headers:     apiHeaders(),
                });
                if (!resp.ok) break;
                data = await resp.json();
            } catch (_) { break; }

            const elements = data?.elements || [];
            if (elements.length === 0) break;

            for (const el of elements) {
                const c = makeComment(el, isReply, parentUrn);
                if (c) {
                    c.rank = items.length;
                    items.push(c);
                }
                if (items.length >= maxItems) break;
            }

            const total   = data?.paging?.total ?? null;
            const fetched = start + elements.length;
            if (total !== null && fetched >= total) break;
            if (elements.length < PAGE)             break;
            if (items.length   >= maxItems)         break;

            start += PAGE;
            await new Promise(r => setTimeout(r, 1000 + Math.random() * 1000));
        }
        return items;
    }

    // ── Per-post fetch (top-level + replies) ─────────────────────────────────
    const results = {};

    for (const urn of urns) {
        const allComments = [];

        // 1. Top-level comments
        const topLevelUrl =
            `https://www.linkedin.com/voyager/api/feed/comments` +
            `?updateId=${encodeURIComponent(urn)}`;

        const topLevel = await pagedFetch(topLevelUrl, maxTopLevel, false, null);

        for (const comment of topLevel) {
            comment.rank = allComments.length;
            allComments.push(comment);

            // 2. Replies for this comment.
            // We attempt this whenever we have a comment URN — pagedFetch returns
            // immediately (empty) when LinkedIn says there are no replies.
            const commentUrn = comment.comment_urn;
            if (!commentUrn) continue;

            const replyUrl =
                `https://www.linkedin.com/voyager/api/feed/comments` +
                `?parentCommentUrn=${encodeURIComponent(commentUrn)}`;

            const replies = await pagedFetch(
                replyUrl,
                maxRepliesPerComment,
                true,
                commentUrn,
            );

            for (const reply of replies) {
                reply.rank = allComments.length;
                allComments.push(reply);
            }

            if (replies.length > 0) {
                await new Promise(r => setTimeout(r, 800 + Math.random() * 800));
            }
        }

        results[urn] = allComments;
        await new Promise(r => setTimeout(r, 1200 + Math.random() * 1500));
    }

    return results;
}
