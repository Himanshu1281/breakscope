import { useEffect, useState } from "react";

import type { Post } from "../types";

export function usePost(slug: string) {
  const [post, setPost] = useState<Post | null>(null);
  useEffect(() => {
    fetch(`/posts/${slug}`)
      .then((res) => res.json())
      .then(setPost);
  }, [slug]);
  return post;
}
