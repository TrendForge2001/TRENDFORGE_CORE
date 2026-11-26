import Workspace from "@/components/workspace";
import { views, type View } from "@/lib/model";

export function generateStaticParams() {
  return views.map((view) => ({ view }));
}

export default async function Page({
  params,
}: {
  params: Promise<{ view: View }>;
}) {
  const { view } = await params;
  return <Workspace view={view} />;
}
