() => {
    const URL_RE = /https?:\/\/[^\s"'<>]+/;
    const results = [];
    const seenUrns = new Set();

    // 1. Try modern SDUI component selectors
    const sduiContainers = Array.from(document.querySelectorAll(
        '[componentkey^="CommentComponentReference_"], [componentkey^="ReplyComponentReference_"], [componentkey*="urn:li:comment"]'
    ));

    if (sduiContainers.length > 0) {
        let currentParentUrn = null;

        for (const c of sduiContainers) {
            const componentKey = c.getAttribute('componentkey') || '';
            const match = componentKey.match(/urn:li:comment:[^"')\s]+/);
            const commentUrn = match ? match[0] : null;

            if (commentUrn && seenUrns.has(commentUrn)) continue;
            if (commentUrn) seenUrns.add(commentUrn);

            // Author: prefer avatar img alt (handles personal and company profiles)
            const avatarImg = c.querySelector('img[alt*="profile" i], img[alt*="company" i]');
            let author = null;
            if (avatarImg && avatarImg.alt) {
                author = avatarImg.alt
                    .replace(/^View\s+(company:\s*)?/i, '')
                    .replace(/(?:[’']s|[’']|\b)\s*(profile|company).*$/i, '')
                    .trim();
            }
            if (!author) {
                const authorLink = Array.from(c.querySelectorAll('a')).find(a => 
                    (a.href.includes('/in/') || a.href.includes('/company/')) && a.innerText.trim().length > 0
                );
                if (authorLink) {
                    author = authorLink.innerText.split('\n')[0]
                        .replace(/Premium Profile.*$/i, '')
                        .replace(/Verified Profile.*$/i, '')
                        .trim();
                }
            }

            // Text: explicitly look for data-testid="expandable-text-box" first
            let textBox = c.querySelector('[data-testid="expandable-text-box"]');
            if (!textBox) {
                // Look for text paragraphs that do not belong to the author link
                const paragraphs = Array.from(c.querySelectorAll('p')).filter(p => !p.closest('a[href*="/in/"]') && !p.closest('a[href*="/company/"]'));
                if (paragraphs.length > 0) {
                    textBox = paragraphs[0];
                }
            }
            let text = textBox ? textBox.innerText.trim() : '';
            if (text) {
                text = text.replace(/(?:\s*…\s*more|\s*\.\.\.\s*more)$/i, '').trim();
            }

            // Reply detection:
            // Top-level comment avatars are at left offset ~12px relative to comment container,
            // while reply comment avatars are indented at offset >= 25px (typically 52px).
            const img = c.querySelector('img');
            const cRect = c.getBoundingClientRect();
            const imgRect = img ? img.getBoundingClientRect() : null;
            const relativeOffset = imgRect ? Math.round(imgRect.left - cRect.left) : 0;

            const isReply = relativeOffset >= 25 ||
                            componentKey.startsWith('ReplyComponentReference_') || 
                            componentKey.toLowerCase().includes('reply') || 
                            !!c.closest('[componentkey*="reply" i]');

            let parentCommentUrn = null;
            if (!isReply) {
                currentParentUrn = commentUrn;
            } else {
                parentCommentUrn = currentParentUrn;
            }

            if (text) {
                results.push({
                    author: author || null,
                    text: text,
                    has_external_url: URL_RE.test(text),
                    is_reply: isReply,
                    comment_urn: commentUrn || null,
                    parent_comment_urn: parentCommentUrn || null,
                });
            }
        }
        return results;
    }

    // 2. Fallback to legacy selectors
    const legacyArticles = document.querySelectorAll('article.comments-comment-entity, .comments-comment-item');
    for (const art of legacyArticles) {
        const authorEl = art.querySelector(
            '.comments-comment-meta__description-title, ' +
            '.comments-post-meta__name-text, ' +
            '[class*="actor-name"], ' +
            '.update-components-actor__name span[aria-hidden="true"], ' +
            'span.comments-post-meta__name'
        );
        const author = authorEl ? authorEl.innerText.trim() : null;

        const textEl = art.querySelector(
            '.comments-comment-item__main-content, ' +
            '[class*="comment-item__main-content"], ' +
            '.comments-comment-item-content-body, ' +
            'span[dir="ltr"]'
        );
        let text = textEl ? textEl.innerText.trim() : null;
        if (text) {
            text = text.replace(/(?:\s*…\s*more|\s*\.\.\.\s*more)$/i, '').trim();
        }
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
