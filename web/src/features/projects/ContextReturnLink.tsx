import { ArrowLeft } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { projectReturn } from "./contextNavigation";

export function ContextReturnLink({ project }: { project: number }) {
  const [params] = useSearchParams();
  if (!params.has("returnTo") && !(params.get("view") === "products" && params.get("display") === "market")) return null;
  const back = projectReturn(project, params.get("returnTo"), 0, true);
  return <Link className="sp-context-return" to={back.href}><ArrowLeft size={15} aria-hidden="true" />{back.label}</Link>;
}
