() => {
    const URL_RE = /https?:\/\/[^\s"'<>]+/;
    const results = [];
    const articles = document.querySelectorAll('article.comments-comment-entity');
    for (const art of articles) {
        // Author: inside the lockup/title span
        const authorEl = art.querySelector(
            '.comments-comment-meta__description-title, ' +
            '.comments-post-meta__name-text, ' +
            '[class*="actor-name"], ' +
            '.update-components-actor__name span[aria-hidden="true"], ' +
            'span.comments-post-meta__name'
        );
        const author = authorEl ? authorEl.innerText.trim() : null;

        // Comment text: the main content span
        const textEl = art.querySelector(
            '.comments-comment-item__main-content, ' +
            '[class*="comment-item__main-content"], ' +
            '.comments-comment-item-content-body, ' +
            'span[dir="ltr"]'
        );
        const text = textEl ? textEl.innerText.trim() : null;

        // Detect replies: nested inside a .comments-replies-list container
        const isReply = art.closest('.comments-replies-list') !== null;

        if (text) {
            results.push({
                author: author || null,
                text: text,
                has_external_url: URL_RE.test(text),
                is_reply: isReply,
                comment_urn: null,
                parent_comment_urn: null,
            });
        }
    }
    return results;
}
