import { Card, CardContent } from "@/components/ui/card";

/** Заглушка вкладки до наполнения данными (F1–F3). */
export function TabStub({ title, fillIn }: { title: string; fillIn: string }) {
  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold">{title}</h1>
      <Card>
        <CardContent className="py-12 text-center text-sm text-muted">
          {fillIn}
        </CardContent>
      </Card>
    </div>
  );
}
