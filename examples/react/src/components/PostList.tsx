import { useEffect, useState } from "react";

import type { Post } from "../types";
import { PostCard } from "./PostCard";

export function PostList() {
  const [posts, setPosts] = useState<Post[]>([]);

  useEffect(() => {
    fetch("/posts")
      .then((res) => res.json())
      .then((data: Post[]) => setPosts(data));
  }, []);

  const tagged = posts.filter((p) => p.tags.includes("featured")); // affected: response.property.removed

  return (
    <section>
      <h2>{tagged.length} featured</h2>
      {posts.map((p) => (
        <PostCard key={p.slug} post={p} />
      ))}
    </section>
  );
}
