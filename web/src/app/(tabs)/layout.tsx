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
      <main className="ml-0 px-4 py-4 pb-24 md:ml-24 md:px-6 md:py-5 md:pb-5">{children}</main>
    </div>
  );
}
