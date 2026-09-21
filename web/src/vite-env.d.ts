/// <reference types="vite/client" />

declare module "virtual:blog.md" {
  const markdown: string;
  export default markdown;
}

declare module "markdown-it";
