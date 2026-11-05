import { request } from "@/lib/api/client";
import type { Item, ItemCreate, ItemUpdate } from "@/lib/schemas/items";

/** The typed items SDK — one function per backend `/items` endpoint. */

export function listItems(): Promise<Item[]> {
  return request<Item[]>("/items");
}

/** @keep the worked example's SDK covers every `/items` endpoint; no page calls this one yet. */
export function getItem(id: string): Promise<Item> {
  return request<Item>(`/items/${id}`);
}

export function createItem(payload: ItemCreate): Promise<Item> {
  return request<Item>("/items", { method: "POST", body: payload });
}

/** @keep the worked example's SDK covers every `/items` endpoint; no page calls this one yet. */
export function updateItem(id: string, payload: ItemUpdate): Promise<Item> {
  return request<Item>(`/items/${id}`, { method: "PUT", body: payload });
}

/** @keep the worked example's SDK covers every `/items` endpoint; no page calls this one yet. */
export function deleteItem(id: string): Promise<void> {
  return request<void>(`/items/${id}`, { method: "DELETE" });
}
