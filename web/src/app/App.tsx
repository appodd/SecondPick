import { useMemo } from "react";
import { RouterProvider } from "react-router-dom";

import { createAppRouter } from "./router";

export function App() {
  const router = useMemo(() => createAppRouter(), []);

  return <RouterProvider router={router} />;
}
