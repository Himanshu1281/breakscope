export interface Author {
  name: string;
  avatar?: string;
}

export interface Post {
  slug: string;
  title: string;
  author: Author;
  tags: string[];
  publishedAt: string;
}
