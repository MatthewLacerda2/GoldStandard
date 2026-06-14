import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { createItem, listItems } from "@/lib/api/items";
import type { Item } from "@/lib/schemas/items";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function ItemsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const itemsQuery = useQuery<Item[]>({
    queryKey: ["items"],
    queryFn: listItems,
  });

  const createMutation = useMutation({
    mutationFn: createItem,
    onSuccess: () => {
      setName("");
      setDescription("");
      void queryClient.invalidateQueries({ queryKey: ["items"] });
    },
  });

  function handleSubmit(event: React.FormEvent): void {
    event.preventDefault();
    if (!name.trim()) return;
    createMutation.mutate({ name, description: description || null });
  }

  return (
    <section className="mx-auto flex max-w-3xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-h1">{t("items.heading")}</h1>
        <p className="text-body text-muted-foreground">
          {t("items.subheading")}
        </p>
      </div>

      <form className="flex gap-2" onSubmit={handleSubmit}>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("items.form.namePlaceholder")}
        />
        <Input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t("items.form.descriptionPlaceholder")}
        />
        <Button type="submit" disabled={createMutation.isPending}>
          {t("items.form.submit")}
        </Button>
      </form>

      {itemsQuery.isLoading ? (
        <p className="text-body text-muted-foreground">{t("items.loading")}</p>
      ) : itemsQuery.isError ? (
        <p className="text-body text-destructive">{t("items.error")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("items.columns.name")}</TableHead>
              <TableHead>{t("items.columns.description")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {itemsQuery.data && itemsQuery.data.length > 0 ? (
              itemsQuery.data.map((item) => (
                <TableRow key={item.id}>
                  <TableCell>{item.name}</TableCell>
                  <TableCell>{item.description}</TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={2} className="text-muted-foreground">
                  {t("items.empty")}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

export const Route = createFileRoute("/")({ component: ItemsPage });
