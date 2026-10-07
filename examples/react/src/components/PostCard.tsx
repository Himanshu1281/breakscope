import type { Post } from "../types";

export function PostCard({ post }: { post: Post }) {
  const published = new Date(post.publishedAt); // affected: response.property.became_nullable
  return (
    <article>
      <h3>{post.title}</h3>
      <p>
        by {post.author.name} {/* affected: response.property.removed */}
        on {published.toLocaleDateString()}
      </p>
    </article>
  );
}

export function SiteFooter({ owner }: { owner: { name: string } }) {
  return <footer>© {owner.name}</footer>;
}
