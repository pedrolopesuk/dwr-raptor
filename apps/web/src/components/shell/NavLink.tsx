"use client";

import type { AnchorHTMLAttributes, ReactNode } from "react";

import { useRouter } from "next/navigation";

/**
 * Client-side navigation link. A real anchor (keyboard, middle-click and
 * "copy link" all work) that routes through the Next router.
 */
export function NavLink({
  href,
  current,
  children,
  onClick,
  ...rest
}: {
  href: string;
  current?: boolean;
  children: ReactNode;
} & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">) {
  const router = useRouter();
  return (
    <a
      {...rest}
      href={href}
      aria-current={current ? "page" : undefined}
      onClick={(event) => {
        onClick?.(event);
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        ) {
          return;
        }
        event.preventDefault();
        router.push(href);
      }}
    >
      {children}
    </a>
  );
}
