"use client";

import { useEffect } from "react";

const PRODUCT_NAME = "VisibilityStack";

export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = `${title} | ${PRODUCT_NAME}`;
  }, [title]);
}
