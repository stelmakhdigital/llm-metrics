import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";

export default function TabsLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="min-h-screen">
      <Header />
      <Sidebar />
      <main className="ml-24 px-6 py-5">{children}</main>
    </div>
  );
}
