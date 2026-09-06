async (knownUrnsArray) => {
    const knownUrns = new Set(knownUrnsArray || []);
    async function reportProgress(payload) {
        try {
            if (typeof window.sgReportSavedPostsProgress === "function") {
                await window.sgReportSavedPostsProgress(payload);
            }
        } catch (_) {}
    }

    async function fetchWithTimeout(url, options, timeoutMs = 30000) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            return await fetch(url, { ...options, signal: controller.signal });
        } finally {
            clearTimeout(timer);
        }
    }

    const csrf = document.cookie
        .split("; ")
        .find(r => r.startsWith("JSESSIONID="))
        ?.split("=")[1]
        ?.replace(/"/g, "");
    if (!csrf) return { error: "CSRF token not found" };

    function findPosts(obj, results = []) {
        if (!obj || typeof obj !== "object") return results;
        if (obj.summary?.text && obj.trackingUrn) {
            results.push({
                author: obj.title?.text || null,
                subtitle: obj.primarySubtitle?.text || null,
                date: obj.secondarySubtitle?.text || null,
                content: obj.summary.text,
                urn: obj.trackingUrn
            });
        }
        if (Array.isArray(obj)) { obj.forEach(x => findPosts(x, results)); }
        else { Object.values(obj).forEach(x => findPosts(x, results)); }
        return results;
    }

    const raw = performance.getEntries()
        .find(x => x.name.includes("SEARCH_MY_ITEMS_SAVED_POSTS"))?.name;
    if (!raw) return { error: "No saved posts API URL in performance entries. Navigate to /my-items/saved-posts/ first." };

    // raw is already the full absolute URL — do not prepend the domain again
    const baseUrl = raw.replace("mark_bigpipe_", "").replace("_start", "");

    let allPosts = [], seenUrns = new Set(), start = 0, paginationToken = null;
    let pageCount = 0, paginationError = null;

    while (true) {
        let url = baseUrl.replace(/start:\d+/, `start:${start}`);
        if (paginationToken) {
            url = url.includes("paginationToken:")
                ? url.replace(/paginationToken:[^,)\s]+/, `paginationToken:${paginationToken}`)
                : url.replace("query:(", `paginationToken:${paginationToken},query:(`);
        }

        let res;
        try {
            res = await fetchWithTimeout(url, {
                credentials: "include",
                headers: {
                    "csrf-token": csrf,
                    "accept": "application/json",
                    "x-restli-protocol-version": "2.0.0"
                }
            });
        } catch (error) {
            paginationError = `request failed at page ${pageCount + 1}: ${error?.message || error}`;
            await reportProgress({ phase: "pagination_error", pages: pageCount, extracted: allPosts.length });
            break;
        }
        if (!res.ok) {
            paginationError = `HTTP ${res.status} at page ${pageCount + 1}`;
            await reportProgress({ phase: "pagination_error", pages: pageCount, extracted: allPosts.length });
            break;
        }

        const json = await res.json();
        const posts = findPosts(json);
        let newCount = 0;
        let metKnown = false;
        for (const p of posts) {
            if (knownUrns.has(p.urn)) {
                metKnown = true;
                break;
            }
            if (!seenUrns.has(p.urn)) { seenUrns.add(p.urn); allPosts.push(p); newCount++; }
        }
        pageCount++;
        await reportProgress({ phase: "pagination", pages: pageCount, extracted: allPosts.length });

        const nextToken = json?.data?.searchDashClustersByAll?.metadata?.paginationToken
            || json?.data?.data?.searchDashClustersByAll?.metadata?.paginationToken;

        if (metKnown || !nextToken || newCount === 0) break;
        paginationToken = nextToken;
        start += 10;

        await new Promise(r => setTimeout(r, 2000 + Math.random() * 2000));
    }

    // ── Stage 2: Hydrate reposts to recover original post content ────────────
    // Discover the GraphQL queryId from already-captured network requests as a fallback.
    const gqlQueryId = performance.getEntries()
        .flatMap(e => { try { return [new URL(e.name)]; } catch { return []; } })
        .filter(u => u.pathname.includes("voyager/api/graphql"))
        .map(u => u.searchParams.get("queryId"))
        .find(q => q && q.startsWith("voyagerFeedDashUpdates"))
        || null;

    function isLikelyRepost(post) {
        // Only trigger on posts LinkedIn explicitly marks as reposts.
        // Removed the content-length fallback — it caused false positives.
        return post.date && post.date.includes("Reposted");
    }

    // Match only post-type URNs (activity, share, ugcPost) — not member/profile/etc.
    function isPostUrn(urn) {
        return typeof urn === "string" && (
            urn.startsWith("urn:li:activity:") ||
            urn.startsWith("urn:li:share:") ||
            urn.startsWith("urn:li:ugcPost:")
        );
    }

    // Extract a clean post URN from a compound like urn:li:fs_feedUpdate:(V2,urn:li:activity:xxx)
    function extractPostUrn(urn) {
        if (!urn) return null;
        if (isPostUrn(urn)) return urn;
        const m = urn.match(/urn:li:(?:activity|share|ugcPost):[^,)]+/);
        return m ? m[0] : null;
    }

    // Primary path: REST /voyager/api/feed/updates/{urn} exposes resharedUpdate directly
    function getOriginalFromRest(data) {
        const update = data?.value?.["com.linkedin.voyager.feed.render.UpdateV2"];
        if (!update?.resharedUpdate) return null;
        // resharedUpdate may itself be wrapped in a type key or be the object directly
        const inner = update.resharedUpdate?.["com.linkedin.voyager.feed.render.UpdateV2"]
            || update.resharedUpdate;
        const content =
            inner?.commentary?.text?.text ||
            inner?.commentary?.text ||
            inner?.socialContent?.description?.text ||
            null;
        if (!content) return null;
        const rawUrn = inner?.dashEntityUrn || inner?.entityUrn || null;
        const urn = extractPostUrn(rawUrn);
        const author = inner?.actor?.name?.text || inner?.actor?.name || null;
        return { urn, content, author };
    }

    // Fallback: tree-walk restricted to post-type URNs
    function extractOriginalsFallback(data, wrapperUrn) {
        const found = [];
        const seen = new Set();
        function walk(obj) {
            if (!obj || typeof obj !== "object") return;
            const urn = obj.entityUrn || obj.trackingUrn;
            if (urn && isPostUrn(urn) && urn !== wrapperUrn && !seen.has(urn)) {
                const content =
                    obj.commentary?.text?.text ||
                    obj.commentary?.text ||
                    obj.summary?.text ||
                    obj.description?.text ||
                    null;
                const author =
                    obj.actor?.name?.text ||
                    obj.actor?.name ||
                    obj.title?.text ||
                    null;
                if (content) {
                    seen.add(urn);
                    found.push({ urn, content, author });
                }
            }
            if (Array.isArray(obj)) obj.forEach(walk);
            else {
                try { Object.values(obj).forEach(walk); } catch (_) {}
            }
        }
        walk(data);
        return found;
    }

    const hydrationErrors = [];
    const hydrationTotal = allPosts.filter(isLikelyRepost).length;
    let hydrated = 0;

    for (let i = 0; i < allPosts.length; i++) {
        const post = allPosts[i];
        if (!isLikelyRepost(post)) continue;

        let data = null;
        let errMsg = null;

        // Primary: REST feed endpoint — stable, no queryId required
        try {
            const restResp = await fetch(
                `https://www.linkedin.com/voyager/api/feed/updates/${encodeURIComponent(post.urn)}?moduleKey=feed-item%3Adesktop`,
                {
                    credentials: "include",
                    headers: {
                        "csrf-token": csrf,
                        "accept": "application/json",
                        "x-restli-protocol-version": "2.0.0"
                    }
                }
            );
            if (restResp.ok) {
                data = await restResp.json();
            } else {
                errMsg = `REST:${restResp.status}`;
            }
        } catch (e) {
            errMsg = `REST:err:${e.message}`;
        }

        // Fallback: GraphQL (requires valid queryId captured from page)
        if (!data && gqlQueryId) {
            try {
                const params = new URLSearchParams();
                params.set("variables",
                    `(commentsCount:0,likesCount:0,includeCommentsFirstReply:false,` +
                    `includeReactions:false,moduleKey:feed-item:desktop,urnOrNss:${post.urn})`);
                params.set("queryId", gqlQueryId);
                const gqlResp = await fetch(
                    "https://www.linkedin.com/voyager/api/graphql?" + params.toString(),
                    {
                        credentials: "include",
                        headers: {
                            "csrf-token": csrf,
                            "accept": "application/json",
                            "x-restli-protocol-version": "2.0.0"
                        }
                    }
                );
                if (gqlResp.ok) {
                    data = await gqlResp.json();
                    errMsg = null;
                } else {
                    errMsg = (errMsg ? errMsg + ", " : "") + `GQL:${gqlResp.status}`;
                }
            } catch (e) {
                errMsg = (errMsg ? errMsg + ", " : "") + `GQL:err:${e.message}`;
            }
        }

        if (!data) {
            hydrationErrors.push({ urn: post.urn, error: errMsg || "no_data" });
            await new Promise(r => setTimeout(r, 1200 + Math.random() * 1500));
            continue;
        }

        // Try direct resharedUpdate path first, then fall back to tree walk
        const orig = getOriginalFromRest(data)
            || extractOriginalsFallback(data, post.urn).pop()
            || null;

        if (orig) {
            const commentary = post.content && post.content.trim()
                ? post.content.trim()
                : null;
            // Include original author attribution so both voices are visible in the note
            const origHeader = orig.author ? `**${orig.author}** originally wrote:\n` : "";
            const combinedContent = commentary
                ? `${commentary}\n\n---\n\n${origHeader}${orig.content}`
                : `${origHeader}${orig.content}`;
            allPosts[i] = {
                ...post,
                author: orig.author || post.author,
                content: combinedContent,
                repost_author: post.author,
                repost_commentary: commentary,
                original_urn: orig.urn,
                is_repost: true
            };
        } else {
            hydrationErrors.push({ urn: post.urn, error: "no_originals_found" });
        }

        hydrated++;
        await reportProgress({
            phase: "hydration",
            pages: pageCount,
            extracted: allPosts.length,
            hydrated,
            hydrationTotal
        });

        await new Promise(r => setTimeout(r, 1200 + Math.random() * 1500));
    }

    return { posts: allPosts, hydrationErrors, paginationError };
}
