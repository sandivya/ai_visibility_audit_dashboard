"use client";

import { useEffect } from "react";

const PRODUCT_NAME = "AI Visibility Audit";

export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = `${title} | ${PRODUCT_NAME}`;
  }, [title]);
}
