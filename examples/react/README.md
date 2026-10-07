# React example

A blog front end. `PostList` fetches posts into state and renders a `PostCard` for each one (in another file).

**The change:**
- `Author.name` is renamed to `displayName`
- `Post.tags` is removed
- `Post.publishedAt` can now be `null`

```bash
breakscope analyze examples/react/api/v1.yaml examples/react/api/v2.yaml examples/react
```

**Expected:** 3 locations.
- `p.tags` in `PostList.tsx` is **high**: `fetch` → `setPosts` → `posts.filter(...)`.
- `post.author.name` and `post.publishedAt` in `PostCard.tsx` are **medium**: followed through `<PostCard post={p} />`.
- `SiteFooter`'s `owner.name` is a look-alike and is not reported.
